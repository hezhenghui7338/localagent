"""Navigation state for interactive segment browser (testable without TUI)."""

from __future__ import annotations

from dataclasses import dataclass

from localagent.i18n import t
from localagent.summarize.segment_reader import ReadingProgress


@dataclass
class SegmentNavState:
    """Cursor + viewport over document segments."""

    progress: ReadingProgress
    filename: str
    index: int = 0
    list_window: int = 10
    message: str = ""

    def __post_init__(self) -> None:
        if self.progress.total:
            self.index = max(0, min(self.index, self.progress.total - 1))
        else:
            self.index = 0

    @property
    def total(self) -> int:
        return self.progress.total

    @property
    def empty(self) -> bool:
        return self.total == 0

    def current_index(self) -> int:
        return self.index

    def move(self, delta: int) -> None:
        if self.empty:
            return
        self.index = (self.index + delta) % self.total
        self.message = ""

    def set_index(self, index: int) -> None:
        if self.empty:
            return
        self.index = max(0, min(index, self.total - 1))
        self.message = ""

    def window_slice(self) -> tuple[int, int]:
        if self.empty:
            return 0, 0
        half = max(1, self.list_window // 2)
        start = max(0, self.index - half)
        end = min(self.total, start + self.list_window)
        start = max(0, end - self.list_window)
        return start, end

    def position_label(self) -> str:
        if self.empty:
            return "0/0"
        return f"{self.index + 1}/{self.total}"

    def status_icon(self, index: int) -> str:
        status = self.progress.segment_status_at(index)
        if status == "running":
            return t("summarize.browser_icon_running")
        if status == "failed":
            return t("summarize.browser_icon_failed")
        if status == "done" or self.progress.summary_ready(index):
            return t("summarize.browser_icon_done")
        return t("summarize.browser_icon_pending")

    def list_label(self, index: int) -> str:
        seg = self.progress.segments[index]
        heading = seg.heading
        if len(heading) > 48:
            heading = heading[:47] + "…"
        icon = self.status_icon(index)
        return f"{icon} · {seg.char_count}{t('summarize.browser_chars_suffix')}"

    def detail_text(self) -> str:
        if self.empty:
            return t("summarize.browser_empty")
        if self.progress.summary_ready(self.index):
            summary = ""
            if self.index < len(self.progress.segment_summaries):
                summary = self.progress.segment_summaries[self.index]
            return (summary or "").strip() or t("summarize.browser_empty_summary")
        status = self.progress.segment_status_at(self.index)
        if status == "running":
            return t("summarize.browser_running")
        if status == "failed":
            return t("summarize.browser_failed")
        return t("summarize.browser_pending")

    def detail_text_window(self, *, scroll: int = 0, max_lines: int = 0) -> str:
        full = self.detail_text()
        lines = full.splitlines()
        if max_lines <= 0:
            max_lines = len(lines) if lines else 0
        if not lines or (scroll <= 0 and len(lines) <= max_lines):
            return full
        start = max(0, min(scroll, max(0, len(lines) - 1)))
        window = lines[start : start + max_lines]
        text = "\n".join(window)
        if start > 0:
            text = t("summarize.browser_detail_above", n=start) + "\n" + text
        remaining = len(lines) - (start + len(window))
        if remaining > 0:
            text += "\n" + t("summarize.browser_detail_more", n=remaining)
        return text

    def prefetch_footer(
        self,
        *,
        enabled: bool,
        done: int,
        total: int,
        active: int = 0,
    ) -> str:
        if not enabled:
            return t("summarize.prefetch_stopped", done=done, total=total, active=active)
        return t("summarize.prefetch_status", done=done, total=total, active=active)
