"""Navigation state for interactive news brief (testable without TUI)."""

from __future__ import annotations

from dataclasses import dataclass

from localagent.i18n import t
from localagent.news.brief import format_article_detail
from localagent.news.rank import RankedArticle


@dataclass
class BriefNavState:
    """Cursor + viewport over a ranked article list."""

    items: list[RankedArticle]
    day: str = ""
    index: int = 0
    list_window: int = 10
    message: str = ""

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
        self.message = ""

    def set_index(self, index: int) -> None:
        if self.empty:
            return
        self.index = index
        self._clamp()
        self.message = ""

    def goto_one_based(self, article_no: int) -> bool:
        """Jump to 1-based article number; returns False if out of range."""
        if self.empty:
            return False
        if article_no < 1 or article_no > self.total:
            return False
        self.set_index(article_no - 1)
        return True

    def remove_current(self) -> RankedArticle | None:
        """Remove current item (e.g. after skip). Returns removed item."""
        if self.empty:
            return None
        removed = self.items.pop(self.index)
        if self.index >= self.total and self.total:
            self.index = self.total - 1
        self._clamp()
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

    def detail_text(self) -> str:
        """Full skim detail panel for the current article (TUI detail area)."""
        if self.empty:
            return t("news.browser_empty")
        cur = self.current()
        assert cur is not None
        return format_article_detail(
            cur.article,
            mode="skim",
            reasons=list(cur.reasons) if cur.reasons else None,
        )

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
            text = t("news.browser_detail_above", n=start) + "\n" + text
        remaining = len(lines) - (start + len(window))
        if remaining > 0:
            text += "\n" + t("news.browser_detail_more", n=remaining)
        return text
