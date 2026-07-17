"""Navigation state for interactive news brief (testable without TUI)."""

from __future__ import annotations

from dataclasses import dataclass, field

from localagent.news.rank import RankedArticle


@dataclass
class BriefNavState:
    """Cursor + viewport over a ranked article list."""

    items: list[RankedArticle]
    day: str = ""
    index: int = 0
    list_window: int = 10
    message: str = ""
    detail_mode: str = "summary"  # summary | skim
    skim_text: str = ""

    def __post_init__(self) -> None:
        self._clamp()

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def empty(self) -> bool:
        return self.total == 0

    def current(self) -> RankedArticle | None:
        if self.empty:
            return None
        return self.items[self.index]

    def _clamp(self) -> None:
        if self.empty:
            self.index = 0
            return
        self.index = max(0, min(self.index, self.total - 1))

    def move(self, delta: int) -> None:
        if self.empty:
            return
        self.index = (self.index + delta) % self.total
        self.detail_mode = "summary"
        self.skim_text = ""
        self.message = ""

    def set_index(self, index: int) -> None:
        if self.empty:
            return
        self.index = index
        self._clamp()
        self.detail_mode = "summary"
        self.skim_text = ""

    def remove_current(self) -> RankedArticle | None:
        """Remove current item (e.g. after skip). Returns removed item."""
        if self.empty:
            return None
        removed = self.items.pop(self.index)
        if self.index >= self.total and self.total:
            self.index = self.total - 1
        self._clamp()
        self.detail_mode = "summary"
        self.skim_text = ""
        return removed

    def window_slice(self) -> tuple[int, int]:
        """Return [start, end) indices visible in the list viewport."""
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
