"""Interactive news brief browser ([/] navigate, Enter deep-chat, o open)."""

from __future__ import annotations

import shutil
from typing import Any

from localagent import config
from localagent.i18n import t
from localagent.news.mark import mark_article
from localagent.news.nav import BriefNavState
from localagent.news.open_url import open_in_browser
from localagent.news.rank import RankedArticle
from localagent.news.store import NewsStore
from localagent.ui.clipboard import copy_text


def _help_text() -> str:
    return t("news.browser_help")


def _term_width() -> int:
    try:
        return max(40, shutil.get_terminal_size(fallback=(80, 24)).columns)
    except Exception:
        return 80


def _truncate(text: str, width: int) -> str:
    raw = (text or "").replace("\n", " ").strip()
    if width <= 1:
        return "…"
    w = 0
    out: list[str] = []
    for ch in raw:
        ow = 2 if ord(ch) > 0x2E80 else 1
        if w + ow > width - 1:
            out.append("…")
            break
        out.append(ch)
        w += ow
    return "".join(out)


def parse_goto_article_no(raw: str, *, total: int) -> int | None:
    """Parse 1-based article number for goto mode; None if invalid."""
    text = (raw or "").strip()
    if not text or not text.isdigit():
        return None
    article_no = int(text)
    if article_no < 1 or article_no > total:
        return None
    return article_no


def render_browser_text(
    state: BriefNavState,
    *,
    plain_links: bool = False,
    detail_scroll: int = 0,
    detail_max_lines: int | None = None,
) -> str:
    """Pure text render of the browser UI (also used in tests)."""
    del plain_links  # Detail panel keeps bare URL at the bottom; no title links.
    width = _term_width()
    day = state.day or t("news.browser_today")
    help_text = _help_text()
    max_lines = (
        detail_max_lines
        if detail_max_lines is not None
        else config.SUMMARIZE_BROWSER_DETAIL_LINES
    )
    lines: list[str] = [
        t("news.browser_header", day=day, pos=state.position_label()),
        "─" * min(width, 60),
    ]
    if state.empty:
        lines.append(t("news.browser_empty"))
        lines.append("")
        lines.append(help_text)
        return "\n".join(lines)

    start, end = state.window_slice()
    if start > 0:
        lines.append("  …")
    for i in range(start, end):
        art = state.items[i].article
        marker = ">" if i == state.index else " "
        title = _truncate(art.title or art.url, width - 8)
        lines.append(f"{marker} {i + 1}. {title}")
    if end < state.total:
        lines.append("  …")

    lines.append("─" * min(width, 60))
    lines.append(
        state.detail_text_window(scroll=detail_scroll, max_lines=max_lines).rstrip()
    )

    if state.message:
        lines.append("")
        lines.append(f"· {state.message}")
    lines.append("")
    lines.append(help_text)
    lines.append(t("news.browser_scroll_hint"))
    return "\n".join(lines)


def _run_one_session(
    state: BriefNavState,
    *,
    store: NewsStore,
) -> str:
    """Run TUI until quit or read. In-app: navigate/open/mark/copy/help."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.data_structures import Point
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    result_holder: dict[str, str] = {"action": "quit"}
    scroll_row = [0]
    detail_scroll = [0]
    line_count = [1]
    detail_max_lines = config.SUMMARIZE_BROWSER_DETAIL_LINES
    goto_mode = [False]
    goto_buffer = [""]

    def _goto_prompt() -> str:
        return t(
            "news.browser_goto_prompt",
            total=state.total,
            input=goto_buffer[0],
        )

    def _enter_goto_mode(event: Any) -> None:
        goto_mode[0] = True
        goto_buffer[0] = ""
        state.message = _goto_prompt()
        event.app.invalidate()

    def _cancel_goto_mode() -> None:
        goto_mode[0] = False
        goto_buffer[0] = ""

    def _confirm_goto(event: Any) -> None:
        article_no = parse_goto_article_no(goto_buffer[0], total=state.total)
        if article_no is None:
            state.message = t("news.browser_goto_invalid", total=state.total)
            event.app.invalidate()
            return
        goto_mode[0] = False
        goto_buffer[0] = ""
        if state.goto_one_based(article_no):
            state.message = t(
                "news.browser_goto_done",
                current=article_no,
                total=state.total,
            )
            _reset_scroll()
        event.app.invalidate()

    class ScrollableFormattedTextControl(FormattedTextControl):
        """Cursor row drives Window scroll so long briefs can PageDown."""

        def create_content(self, width: int, height: int | None) -> Any:
            content = super().create_content(width, height)
            line_count[0] = max(1, content.line_count)
            before = scroll_row[0]
            scroll_row[0] = max(0, min(scroll_row[0], line_count[0] - 1))
            if scroll_row[0] != before:
                content = super().create_content(width, height)
                line_count[0] = max(1, content.line_count)
            return content

        def move_cursor_down(self) -> None:
            scroll_row[0] = min(scroll_row[0] + 1, max(0, line_count[0] - 1))

        def move_cursor_up(self) -> None:
            scroll_row[0] = max(0, scroll_row[0] - 1)

    def get_text() -> Any:
        text = render_browser_text(
            state,
            plain_links=True,
            detail_scroll=detail_scroll[0],
            detail_max_lines=detail_max_lines,
        )
        from prompt_toolkit.formatted_text import FormattedText

        header_prefix = t("news.browser_header", day="", pos="").split(" · ")[0]
        help_prefix = _help_text()[:4]
        prefix_skim = t("news.prefix_skim")
        section_labels = {
            t("news.section_detail"),
            t("news.section_viewpoints"),
            t("news.section_quotes"),
        }
        meta_prefixes = (
            t("news.meta_selected", reasons="").rstrip(),
            t("news.meta_published", bits="").rstrip(),
            t("news.meta_id", id="").rstrip(),
            t("news.meta_url", url="").rstrip(),
        )
        fragments: list[tuple[str, str]] = []
        after_title = False
        oneliner_done = False
        for line in text.splitlines(keepends=True):
            bare = line.rstrip("\n")
            if bare.startswith(">"):
                fragments.append(("class:selected", line))
                after_title = False
            elif bare.startswith("· "):
                fragments.append(("class:status", line))
                after_title = False
            elif bare.startswith(header_prefix) or bare.startswith(help_prefix):
                fragments.append(("class:header", line))
                after_title = False
            elif bare.startswith(prefix_skim):
                fragments.append(("class:title", line))
                after_title = True
                oneliner_done = False
            elif after_title and not oneliner_done and bare.strip():
                fragments.append(("class:oneliner", line))
                oneliner_done = True
                after_title = False
            elif bare in section_labels:
                fragments.append(("class:section", line))
            elif any(bare.startswith(p) for p in meta_prefixes if p):
                fragments.append(("class:meta", line))
            else:
                fragments.append(("", line))
        max_logical = max(0, len(fragments) - 1)
        if scroll_row[0] > max_logical:
            scroll_row[0] = max_logical
        return FormattedText(fragments)

    def get_cursor_position() -> Point:
        cap = max(0, line_count[0] - 1)
        y = max(0, min(scroll_row[0], cap))
        return Point(x=0, y=y)

    control = ScrollableFormattedTextControl(
        get_text,
        focusable=True,
        show_cursor=False,
        get_cursor_position=get_cursor_position,
    )
    window = Window(content=control, wrap_lines=True)
    kb = KeyBindings()
    in_goto_mode = Condition(lambda: goto_mode[0])

    def _exit(event: Any, action: str) -> None:
        result_holder["action"] = action
        event.app.exit()

    def _cur_art():
        item = state.current()
        return item.article if item else None

    def _reset_scroll() -> None:
        scroll_row[0] = 0
        detail_scroll[0] = 0
        window.vertical_scroll = 0

    def _detail_line_count() -> int:
        return len(state.detail_text().splitlines())

    def _scroll_up(event: Any) -> None:
        if goto_mode[0]:
            return
        if detail_scroll[0] > 0:
            detail_scroll[0] -= 1
        else:
            scroll_row[0] = max(0, scroll_row[0] - 1)
        event.app.invalidate()

    def _scroll_down(event: Any) -> None:
        if goto_mode[0]:
            return
        total_detail = _detail_line_count()
        if detail_max_lines > 0 and detail_scroll[0] + detail_max_lines < total_detail:
            detail_scroll[0] += 1
        else:
            scroll_row[0] = min(scroll_row[0] + 1, max(0, line_count[0] - 1))
        event.app.invalidate()

    def _item_prev(event: Any) -> None:
        if goto_mode[0]:
            return
        state.move(-1)
        _reset_scroll()
        event.app.invalidate()

    def _item_next(event: Any) -> None:
        if goto_mode[0]:
            return
        state.move(1)
        _reset_scroll()
        event.app.invalidate()

    def _page_down(event: Any) -> None:
        if goto_mode[0]:
            return
        total_detail = _detail_line_count()
        if detail_max_lines > 0 and detail_scroll[0] + detail_max_lines < total_detail:
            detail_scroll[0] = min(
                detail_scroll[0] + detail_max_lines,
                max(0, total_detail - detail_max_lines),
            )
        else:
            info = window.render_info
            if info is not None and info.displayed_lines:
                scroll_row[0] = max(info.last_visible_line(), scroll_row[0] + 1)
            else:
                scroll_row[0] += 10
            scroll_row[0] = max(0, min(scroll_row[0], max(0, line_count[0] - 1)))
        event.app.invalidate()

    def _page_up(event: Any) -> None:
        if goto_mode[0]:
            return
        if detail_scroll[0] > 0:
            detail_scroll[0] = max(0, detail_scroll[0] - detail_max_lines)
        else:
            info = window.render_info
            if info is not None and info.displayed_lines:
                scroll_row[0] = max(
                    0, min(info.first_visible_line(), scroll_row[0] - 1)
                )
            else:
                scroll_row[0] = max(0, scroll_row[0] - 10)
            window.vertical_scroll = 0
        event.app.invalidate()

    @kb.add("up")
    @kb.add("k")
    def _up(event: Any) -> None:
        _scroll_up(event)

    @kb.add("down")
    @kb.add("j")
    def _down(event: Any) -> None:
        _scroll_down(event)

    @kb.add("[")
    @kb.add("<")
    def _prev_item(event: Any) -> None:
        _item_prev(event)

    @kb.add("]")
    @kb.add(">")
    def _next_item(event: Any) -> None:
        _item_next(event)

    @kb.add("pagedown")
    @kb.add("c-f")
    @kb.add("space")
    def _pgdn(event: Any) -> None:
        _page_down(event)

    @kb.add("pageup")
    @kb.add("c-b")
    def _pgup(event: Any) -> None:
        _page_up(event)

    @kb.add("enter", filter=in_goto_mode)
    def _goto_confirm(event: Any) -> None:
        _confirm_goto(event)

    @kb.add("enter", filter=~in_goto_mode)
    def _read(event: Any) -> None:
        _exit(event, "read")

    @kb.add("g", eager=True)
    def _goto_start(event: Any) -> None:
        if goto_mode[0]:
            return
        _enter_goto_mode(event)

    for digit in "0123456789":

        @kb.add(digit, filter=in_goto_mode)
        def _goto_digit(event: Any, *, _digit: str = digit) -> None:
            goto_buffer[0] += _digit
            state.message = _goto_prompt()
            event.app.invalidate()

    @kb.add("backspace", filter=in_goto_mode)
    def _goto_backspace(event: Any) -> None:
        goto_buffer[0] = goto_buffer[0][:-1]
        state.message = _goto_prompt()
        event.app.invalidate()

    @kb.add("escape", filter=in_goto_mode)
    @kb.add("c-c", filter=in_goto_mode)
    def _goto_cancel(event: Any) -> None:
        _cancel_goto_mode()
        state.message = t("news.browser_goto_cancelled")
        event.app.invalidate()

    @kb.add("o", filter=~in_goto_mode)
    def _open(event: Any) -> None:
        art = _cur_art()
        if not art:
            return
        ok = open_in_browser(art.url)
        state.message = (
            t("news.browser_opened") if ok else t("news.browser_open_fail")
        )
        event.app.invalidate()

    @kb.add("b", filter=~in_goto_mode)
    def _bookmark(event: Any) -> None:
        art = _cur_art()
        if not art:
            return
        _a, msg = mark_article(art.id, "bookmark", store=store)
        state.message = msg
        event.app.invalidate()

    @kb.add("x", filter=~in_goto_mode)
    def _skip(event: Any) -> None:
        art = _cur_art()
        if not art:
            return
        _a, msg = mark_article(art.id, "skip", store=store)
        state.remove_current()
        state.message = msg
        _reset_scroll()
        if state.empty:
            _exit(event, "quit")
            return
        event.app.invalidate()

    @kb.add("c", filter=~in_goto_mode)
    def _copy(event: Any) -> None:
        art = _cur_art()
        if not art:
            return
        if copy_text(art.url):
            state.message = t("news.browser_copied")
        else:
            state.message = t("news.browser_copy_fail", url=art.url)
        event.app.invalidate()

    @kb.add("?", filter=~in_goto_mode)
    def _help(event: Any) -> None:
        state.message = _help_text().replace("\n", " | ")
        event.app.invalidate()

    @kb.add("q", filter=~in_goto_mode)
    @kb.add("escape", filter=~in_goto_mode)
    @kb.add("c-c", filter=~in_goto_mode)
    def _quit(event: Any) -> None:
        _exit(event, "quit")

    style = Style.from_dict(
        {
            "selected": "bold reverse",
            "status": "italic",
            "header": "bold",
            "title": "bold",
            "oneliner": "bold",
            "section": "bold",
            "meta": "italic ansibrightblack",
        }
    )
    app = Application(
        layout=Layout(window),
        key_bindings=kb,
        full_screen=True,
        mouse_support=False,
        style=style,
    )
    app.run()
    return result_holder["action"]


def should_enter_news_browser(*, no_ui: bool) -> bool:
    """Mirror summarize's should_enter_document_chat."""
    import sys

    if no_ui:
        return False
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def run_news_browser(
    ranked: list[RankedArticle],
    *,
    day: str = "",
    provider: str = "auto",
    store: NewsStore | None = None,
) -> int:
    """Interactive brief loop. Returns process exit code."""
    if not ranked:
        print(t("news.browser_no_items"))
        return 0

    store = store or NewsStore()
    state = BriefNavState(items=list(ranked), day=day)
    print(t("news.browser_enter"))
    print()

    while True:
        if state.empty:
            print(t("news.browser_list_empty"))
            return 0
        try:
            from localagent.ui.console import prepare_for_input

            prepare_for_input()
            action = _run_one_session(state, store=store)
        except KeyboardInterrupt:
            print()
            return 0
        except EOFError:
            print()
            return 0

        if action == "quit":
            print(t("news.browser_quit"))
            return 0

        if action == "read":
            cur = state.current()
            if cur is None:
                continue
            art = cur.article
            print()
            print(t("news.browser_reading", title=art.title or art.id))
            from localagent.news.chat_bridge import run_article_chat
            from localagent.news.read import read_article
            from localagent.ui.console import ActivityIndicator

            with ActivityIndicator("news", t("news.browser_fetching")):
                result = read_article(art.id, keep=False, plain_links=False, store=store)
            if result.error:
                state.message = t("news.browser_read_fail", error=result.error)
                print(t("news.msg_prefix", msg=state.message))
                continue
            run_article_chat(result, provider=provider)
            print()
            print(t("news.browser_back"))
            state.message = t("news.browser_chat_done")
            updated = store.get(art.id)
            if updated and state.current():
                state.items[state.index] = RankedArticle(
                    article=updated,
                    score=cur.score,
                    reasons=cur.reasons,
                )
            continue

    return 0
