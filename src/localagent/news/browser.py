"""Interactive news brief browser (↑↓ navigate, o open, r deep-chat)."""

from __future__ import annotations

import shutil
from typing import Any

from localagent.i18n import t
from localagent.news.brief import format_article_detail, format_skim_card
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


def render_browser_text(state: BriefNavState, *, plain_links: bool = False) -> str:
    """Pure text render of the browser UI (also used in tests)."""
    del plain_links  # Detail panel keeps bare URL at the bottom; no title links.
    width = _term_width()
    day = state.day or t("news.browser_today")
    help_text = _help_text()
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
    cur = state.current()
    assert cur is not None
    art = cur.article

    if state.detail_mode == "skim" and state.skim_text:
        lines.append(state.skim_text.rstrip())
    else:
        lines.append(
            format_article_detail(
                art,
                mode="summary",
                reasons=list(cur.reasons) if cur.reasons else None,
                rule_width=min(width, 60),
            )
        )

    if state.message:
        lines.append("")
        lines.append(f"· {state.message}")
    lines.append("")
    lines.append(help_text)
    return "\n".join(lines)


def _build_formatted(state: BriefNavState) -> Any:
    from prompt_toolkit.formatted_text import FormattedText

    # Title links are plain text; users open via `o` / Enter.
    text = render_browser_text(state, plain_links=True)
    header_prefix = t("news.browser_header", day="", pos="").split(" · ")[0]
    help_prefix = _help_text().split("\n", 1)[0][:4]
    prefix_current = t("news.prefix_current")
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
        elif bare.startswith(prefix_current) or bare.startswith(prefix_skim):
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
    return FormattedText(fragments)


def _run_one_session(
    state: BriefNavState,
    *,
    store: NewsStore,
) -> str:
    """Run TUI until quit or read. In-app: navigate/open/skim/mark/copy/help."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.data_structures import Point
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    result_holder: dict[str, str] = {"action": "quit"}
    scroll_row = [0]
    line_count = [1]

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
        return _build_formatted(state)

    def get_cursor_position() -> Point:
        y = max(0, min(scroll_row[0], max(0, line_count[0] - 1)))
        return Point(x=0, y=y)

    control = ScrollableFormattedTextControl(
        get_text,
        focusable=True,
        show_cursor=False,
        get_cursor_position=get_cursor_position,
    )
    window = Window(content=control, wrap_lines=True)
    kb = KeyBindings()

    def _exit(action: str) -> None:
        result_holder["action"] = action
        app.exit()

    def _cur_art():
        item = state.current()
        return item.article if item else None

    def _reset_scroll() -> None:
        scroll_row[0] = 0
        window.vertical_scroll = 0

    def _page_down(event: Any) -> None:
        info = window.render_info
        if info is not None and info.displayed_lines:
            scroll_row[0] = max(info.last_visible_line(), scroll_row[0] + 1)
        else:
            scroll_row[0] += 10
        scroll_row[0] = max(0, min(scroll_row[0], max(0, line_count[0] - 1)))
        event.app.invalidate()

    def _page_up(event: Any) -> None:
        info = window.render_info
        if info is not None and info.displayed_lines:
            scroll_row[0] = max(
                0, min(info.first_visible_line(), scroll_row[0] - 1)
            )
        else:
            scroll_row[0] = max(0, scroll_row[0] - 10)
        # Re-anchor so the cursor row sits near the bottom (prior page).
        window.vertical_scroll = 0
        event.app.invalidate()

    @kb.add("up")
    @kb.add("k")
    @kb.add("p")
    def _up(event: Any) -> None:
        state.move(-1)
        _reset_scroll()
        event.app.invalidate()

    @kb.add("down")
    @kb.add("j")
    @kb.add("n")
    def _down(event: Any) -> None:
        state.move(1)
        _reset_scroll()
        event.app.invalidate()

    @kb.add("pagedown")
    @kb.add("c-f")
    @kb.add("space")
    def _pgdn(event: Any) -> None:
        _page_down(event)

    @kb.add("pageup")
    @kb.add("c-b")
    def _pgup(event: Any) -> None:
        _page_up(event)

    @kb.add("o")
    @kb.add("enter")
    def _open(event: Any) -> None:
        art = _cur_art()
        if not art:
            return
        ok = open_in_browser(art.url)
        state.message = (
            t("news.browser_opened") if ok else t("news.browser_open_fail")
        )
        event.app.invalidate()

    @kb.add("s")
    def _skim(event: Any) -> None:
        art = _cur_art()
        if not art:
            return
        store.set_status(art.id, "skimmed")
        refreshed = store.get(art.id) or art
        cur = state.current()
        state.detail_mode = "skim"
        state.skim_text = format_skim_card(
            refreshed,
            reasons=list(cur.reasons) if cur and cur.reasons else None,
        )
        state.message = t("news.browser_skim_shown")
        _reset_scroll()
        event.app.invalidate()

    @kb.add("r")
    def _read(_event: Any) -> None:
        _exit("read")

    @kb.add("b")
    def _bookmark(event: Any) -> None:
        art = _cur_art()
        if not art:
            return
        _a, msg = mark_article(art.id, "bookmark", store=store)
        state.message = msg
        event.app.invalidate()

    @kb.add("x")
    def _skip(event: Any) -> None:
        art = _cur_art()
        if not art:
            return
        _a, msg = mark_article(art.id, "skip", store=store)
        state.remove_current()
        state.message = msg
        _reset_scroll()
        if state.empty:
            _exit("quit")
            return
        event.app.invalidate()

    @kb.add("c")
    def _copy(event: Any) -> None:
        art = _cur_art()
        if not art:
            return
        if copy_text(art.url):
            state.message = t("news.browser_copied")
        else:
            state.message = t("news.browser_copy_fail", url=art.url)
        event.app.invalidate()

    @kb.add("?")
    def _help(event: Any) -> None:
        state.message = _help_text().replace("\n", " | ")
        event.app.invalidate()

    @kb.add("q")
    @kb.add("escape")
    @kb.add("c-c")
    def _quit(_event: Any) -> None:
        _exit("quit")

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
        full_screen=False,
        mouse_support=True,
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
