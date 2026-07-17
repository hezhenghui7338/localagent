"""Interactive news brief browser (↑↓ navigate, o open, r deep-chat)."""

from __future__ import annotations

import shutil
from typing import Any

from localagent.news.brief import format_skim_card
from localagent.news.links import hyperlink
from localagent.news.mark import mark_article
from localagent.news.nav import BriefNavState
from localagent.news.open_url import open_in_browser
from localagent.news.rank import RankedArticle
from localagent.news.store import NewsStore
from localagent.ui.clipboard import copy_text


HELP_TEXT = (
    "键位: ↑↓/jk 切换  o/Enter 打开浏览器  s 速读  r 精读并深聊\n"
    "      b 收藏  x 跳过  c 复制链接  ? 帮助  q/Esc 退出"
)


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
    width = _term_width()
    day = state.day or "今日"
    lines: list[str] = [
        f"今日简报 · {day} · {state.position_label()}",
        "─" * min(width, 60),
    ]
    if state.empty:
        lines.append("（暂无条目）")
        lines.append("")
        lines.append(HELP_TEXT)
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
        title_link = hyperlink(art.title or art.url, art.url, force_plain=plain_links)
        lines.append(f"【当前】{title_link}")
        summary = art.display_summary() or "（暂无摘要）"
        if len(summary) > 280:
            summary = summary[:279] + "…"
        lines.append(f"一句话: {summary}")
        reason = "；".join(cur.reasons[:3]) if cur.reasons else "候选"
        lines.append(f"为何入选: {reason}")
        if art.published_at:
            lines.append(f"发布: {art.published_at[:10]}")
        lines.append(f"id: {art.id}")
        lines.append(f"原文: {art.url}")

    if state.message:
        lines.append("")
        lines.append(f"· {state.message}")
    lines.append("")
    lines.append(HELP_TEXT)
    return "\n".join(lines)


def _build_formatted(state: BriefNavState) -> Any:
    from prompt_toolkit.formatted_text import FormattedText

    # Prefer plain links inside prompt_toolkit (OSC 8 is unreliable here);
    # users open via `o` / Enter. Dump mode still uses OSC 8.
    text = render_browser_text(state, plain_links=True)
    fragments: list[tuple[str, str]] = []
    for line in text.splitlines(keepends=True):
        if line.startswith(">"):
            fragments.append(("class:selected", line))
        elif line.startswith("· "):
            fragments.append(("class:status", line))
        elif line.startswith("今日简报") or line.startswith("键位"):
            fragments.append(("class:header", line))
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
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout
    from prompt_toolkit.layout.containers import Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.styles import Style

    result_holder: dict[str, str] = {"action": "quit"}

    def get_text() -> Any:
        return _build_formatted(state)

    control = FormattedTextControl(get_text, focusable=True, show_cursor=False)
    window = Window(content=control, wrap_lines=True)
    kb = KeyBindings()

    def _exit(action: str) -> None:
        result_holder["action"] = action
        app.exit()

    def _cur_art():
        item = state.current()
        return item.article if item else None

    @kb.add("up")
    @kb.add("k")
    @kb.add("p")
    def _up(event: Any) -> None:
        state.move(-1)
        event.app.invalidate()

    @kb.add("down")
    @kb.add("j")
    @kb.add("n")
    def _down(event: Any) -> None:
        state.move(1)
        event.app.invalidate()

    @kb.add("o")
    @kb.add("enter")
    def _open(event: Any) -> None:
        art = _cur_art()
        if not art:
            return
        ok = open_in_browser(art.url)
        state.message = (
            f"已在浏览器打开"
            if ok
            else "打开浏览器失败，可按 c 复制链接"
        )
        event.app.invalidate()

    @kb.add("s")
    def _skim(event: Any) -> None:
        art = _cur_art()
        if not art:
            return
        store.set_status(art.id, "skimmed")
        refreshed = store.get(art.id) or art
        state.detail_mode = "skim"
        state.skim_text = format_skim_card(refreshed, plain_links=False)
        state.message = "已显示速读卡 · 再按 ↑↓ 返回摘要"
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
            state.message = "已复制原文链接到剪贴板"
        else:
            state.message = f"复制失败: {art.url}"
        event.app.invalidate()

    @kb.add("?")
    def _help(event: Any) -> None:
        state.message = HELP_TEXT.replace("\n", " | ")
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
        }
    )
    app = Application(
        layout=Layout(window),
        key_bindings=kb,
        full_screen=False,
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
        print("[news] 暂无条目。先运行 `la news sync`。")
        return 0

    store = store or NewsStore()
    state = BriefNavState(items=list(ranked), day=day)
    print("[news] 进入交互简报（↑↓ 切换 · o 打开 · r 精读深聊 · q 退出）")
    print()

    while True:
        if state.empty:
            print("[news] 列表已空。")
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
            print("[news] 已退出简报浏览器")
            return 0

        if action == "read":
            cur = state.current()
            if cur is None:
                continue
            art = cur.article
            print()
            print(f"[news] 精读: {art.title or art.id}")
            from localagent.news.chat_bridge import run_article_chat
            from localagent.news.read import read_article
            from localagent.ui.console import ActivityIndicator

            with ActivityIndicator("抓取并总结原文…"):
                result = read_article(art.id, keep=False, plain_links=False, store=store)
            if result.error:
                state.message = f"精读失败: {result.error}"
                print(f"[news] {state.message}")
                continue
            run_article_chat(result, provider=provider)
            print()
            print("[news] 已返回简报浏览器")
            state.message = "深聊结束 · 继续 ↑↓ 浏览"
            updated = store.get(art.id)
            if updated and state.current():
                state.items[state.index] = RankedArticle(
                    article=updated,
                    score=cur.score,
                    reasons=cur.reasons,
                )
            continue

    return 0
