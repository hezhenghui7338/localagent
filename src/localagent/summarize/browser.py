"""Interactive segment browser TUI (↑↓ navigate, Enter deep-chat)."""

from __future__ import annotations

import shutil
import sys
import threading
from dataclasses import dataclass, field
from typing import Any

from localagent import config
from localagent.i18n import t
from localagent.summarize.document import SummarizeResult
from localagent.summarize.nav import SegmentNavState
from localagent.summarize.segment_cache import (
    ThrottledSegmentCacheWriter,
    schedule_segment_cache_save,
)
from localagent.summarize.segment_prefetch import SegmentPrefetchWorker, attach_prefetch_worker
from localagent.summarize.sessions import record_from_result, upsert_session


@dataclass
class BrowserUiState:
    """Cached prefetch/TUI counters refreshed on main thread (via refresh_interval)."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    dirty: bool = False
    done_count: int = 0
    prefetch_enabled: bool = True
    active_workers: int = 0

    def mark_dirty(self) -> None:
        with self.lock:
            self.dirty = True

    def sync_from(
        self,
        *,
        progress: Any,
        worker: SegmentPrefetchWorker | None,
        force: bool = False,
    ) -> None:
        with self.lock:
            if not force and not self.dirty:
                return
            self.done_count = int(progress.done_count())
            self.prefetch_enabled = bool(getattr(progress, "prefetch_enabled", True))
            if worker is not None:
                snap = worker.snapshot()
                self.active_workers = snap.active_workers
                self.prefetch_enabled = snap.enabled
            else:
                self.active_workers = 0
            self.dirty = False


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


def render_segment_browser_text(
    state: SegmentNavState,
    *,
    prefetch_enabled: bool = True,
    done_count: int | None = None,
    active_workers: int = 0,
    detail_scroll: int = 0,
    detail_max_lines: int | None = None,
) -> str:
    """Pure text render of the segment browser (used in tests)."""
    width = _term_width()
    done = done_count if done_count is not None else state.progress.done_count()
    max_lines = (
        detail_max_lines
        if detail_max_lines is not None
        else config.SUMMARIZE_BROWSER_DETAIL_LINES
    )
    lines: list[str] = [
        t(
            "summarize.browser_header",
            filename=state.filename,
            done=done,
            total=state.total,
        ),
        "─" * min(width, 60),
    ]
    if state.empty:
        lines.append(t("summarize.browser_empty"))
        lines.append("")
        lines.append(t("summarize.browser_help"))
        return "\n".join(lines)

    start, end = state.window_slice()
    if start > 0:
        lines.append("  …")
    for i in range(start, end):
        seg = state.progress.segments[i]
        marker = ">" if i == state.index else " "
        title = _truncate(seg.heading, width - 16)
        lines.append(f"{marker} {i + 1}. {title} {state.list_label(i)}")
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
    lines.append(
        state.prefetch_footer(
            enabled=prefetch_enabled,
            done=done,
            total=state.total,
            active=active_workers,
        )
    )
    lines.append(t("summarize.browser_help"))
    lines.append(t("summarize.browser_scroll_hint"))
    return "\n".join(lines)


def should_enter_segment_browser(*, no_ui: bool) -> bool:
    if no_ui:
        return False
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def run_segment_browser(
    result: SummarizeResult,
    *,
    provider: str = "auto",
    summarize_session_id: str | None = None,
    conversation_session_id: str | None = None,
    no_prefetch: bool = False,
    use_llm: bool = True,
) -> int:
    """Interactive segment list; Enter opens deep chat for ready segments."""
    progress = result.reading_progress
    if progress is None:
        return 1

    from localagent.persist.conversations import new_session_id

    sid = summarize_session_id or new_session_id()
    conv_id = conversation_session_id or sid
    state = SegmentNavState(
        progress=progress,
        filename=result.filename,
        index=progress.current_index,
    )
    cache_writer = ThrottledSegmentCacheWriter()
    ui_state = BrowserUiState()
    ui_state.sync_from(progress=progress, worker=None, force=True)

    def _persist_session() -> None:
        upsert_session(
            record_from_result(
                result,
                session_id=sid,
                conversation_session_id=conv_id,
            )
        )

    def _persist_cache(*, full_md: bool = False) -> None:
        schedule_segment_cache_save(
            cache_writer,
            result,
            provider=provider,
            full_md=full_md,
        )

    def _on_update(_index: int, summary: str) -> None:
        if _index == state.index:
            result.markdown = summary.strip()
        ui_state.mark_dirty()

    prefetch_on = config.SUMMARIZE_SEGMENT_PREFETCH and not no_prefetch
    worker = attach_prefetch_worker(
        result,
        provider=provider,
        use_llm=use_llm,
        enabled=prefetch_on,
        on_update=_on_update,
        on_persist=lambda: _persist_cache(full_md=False),
    )
    _persist_session()
    _persist_cache(full_md=False)

    print(t("summarize.browser_enter"))
    print()

    try:
        while True:
            if state.empty:
                print(t("summarize.browser_empty"))
                return 0
            try:
                from localagent.ui.console import prepare_for_input

                prepare_for_input()
                action = _run_one_session(
                    state,
                    worker=worker,
                    ui_state=ui_state,
                )
            except KeyboardInterrupt:
                print()
                return 0
            except EOFError:
                print()
                return 0

            if action == "quit":
                print(t("summarize.browser_quit"))
                return 0

            if action == "chat":
                if not progress.summary_ready(state.index):
                    state.message = t("summarize.browser_chat_blocked")
                    continue
                from localagent.summarize.chat_bridge import run_segment_chat

                print()
                print(
                    t(
                        "summarize.browser_reading",
                        current=state.index + 1,
                        total=state.total,
                        heading=progress.segments[state.index].heading,
                    )
                )
                run_segment_chat(
                    result,
                    state.index,
                    provider=provider,
                    summarize_session_id=sid,
                    conversation_session_id=conv_id,
                    deep_segment_only=True,
                )
                print()
                print(t("summarize.browser_back"))
                state.message = t("summarize.browser_chat_done")
                cache_writer.flush(full_md=True)
                _persist_session()
                continue
    finally:
        if worker:
            worker.stop()
        cache_writer.flush(full_md=True)


def _run_one_session(
    state: SegmentNavState,
    *,
    worker: SegmentPrefetchWorker | None,
    ui_state: BrowserUiState,
) -> str:
    from prompt_toolkit.application import Application
    from prompt_toolkit.data_structures import Point
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
    refresh_sec = float(config.SUMMARIZE_BROWSER_REFRESH_SEC)

    class ScrollableFormattedTextControl(FormattedTextControl):
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
        from prompt_toolkit.formatted_text import FormattedText

        ui_state.sync_from(progress=state.progress, worker=worker, force=False)
        with ui_state.lock:
            done = ui_state.done_count
            prefetch_on = ui_state.prefetch_enabled
            active = ui_state.active_workers
        text = render_segment_browser_text(
            state,
            prefetch_enabled=prefetch_on,
            done_count=done,
            active_workers=active,
            detail_scroll=detail_scroll[0],
            detail_max_lines=detail_max_lines,
        )
        fragments: list[tuple[str, str]] = []
        for line in text.splitlines(keepends=True):
            if line.startswith(">"):
                fragments.append(("class:selected", line))
            elif line.startswith("· "):
                fragments.append(("class:status", line))
            elif line.startswith("[summarize]"):
                fragments.append(("class:header", line))
            else:
                fragments.append(("", line))
        # refresh_interval 可能缩短文本；先按逻辑行数 clamp，避免 cursor 越界
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

    def _exit(event: Any, action: str) -> None:
        result_holder["action"] = action
        event.app.exit()

    def _reset_scroll() -> None:
        scroll_row[0] = 0
        detail_scroll[0] = 0
        window.vertical_scroll = 0

    def _detail_line_count() -> int:
        return len(state.detail_text().splitlines())

    def _scroll_up(event: Any) -> None:
        if detail_scroll[0] > 0:
            detail_scroll[0] -= 1
        else:
            scroll_row[0] = max(0, scroll_row[0] - 1)
        event.app.invalidate()

    def _scroll_down(event: Any) -> None:
        total_detail = _detail_line_count()
        if detail_max_lines > 0 and detail_scroll[0] + detail_max_lines < total_detail:
            detail_scroll[0] += 1
        else:
            scroll_row[0] = min(scroll_row[0] + 1, max(0, line_count[0] - 1))
        event.app.invalidate()

    def _seg_prev(event: Any) -> None:
        state.move(-1)
        _reset_scroll()
        event.app.invalidate()

    def _seg_next(event: Any) -> None:
        state.move(1)
        _reset_scroll()
        event.app.invalidate()

    def _page_down(event: Any) -> None:
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
    def _prev_segment(event: Any) -> None:
        _seg_prev(event)

    @kb.add("]")
    @kb.add(">")
    def _next_segment(event: Any) -> None:
        _seg_next(event)

    @kb.add("pagedown")
    @kb.add("c-f")
    @kb.add("space")
    def _pgdn(event: Any) -> None:
        _page_down(event)

    @kb.add("pageup")
    @kb.add("c-b")
    def _pgup(event: Any) -> None:
        _page_up(event)

    @kb.add("enter")
    @kb.add("r")
    def _read(event: Any) -> None:
        _exit(event, "chat")

    @kb.add("s")
    def _toggle_prefetch(event: Any) -> None:
        if worker is None:
            state.message = t("summarize.prefetch_unavailable")
        else:
            running = worker.toggle()
            state.message = (
                t("summarize.prefetch_started_msg")
                if running
                else t("summarize.prefetch_stopped_msg")
            )
        ui_state.mark_dirty()
        event.app.invalidate()

    @kb.add("?")
    def _help(event: Any) -> None:
        state.message = t("summarize.browser_help").replace("\n", " | ")
        event.app.invalidate()

    @kb.add("q")
    @kb.add("escape")
    @kb.add("c-c")
    def _quit(event: Any) -> None:
        _exit(event, "quit")

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
        full_screen=True,
        mouse_support=False,
        style=style,
        refresh_interval=refresh_sec,
        min_redraw_interval=0.5,
    )
    app.run()
    return result_holder["action"]
