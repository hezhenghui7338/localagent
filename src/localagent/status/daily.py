"""Daily Actions surface — news / pending / workspace signals."""

from __future__ import annotations

from dataclasses import dataclass

from localagent.news.store import today_synced
from localagent.pending.queue import pending_count


@dataclass(frozen=True)
class DailyActionsStatus:
    news_synced_today: bool
    pending_count: int
    todo_count: int

    @property
    def has_signal(self) -> bool:
        return self.news_synced_today or self.pending_count > 0 or self.todo_count > 0


def collect_daily_actions_status(*, todo_limit: int = 50) -> DailyActionsStatus:
    """Gather lightweight local signals for banner / `la status`."""
    todos = 0
    try:
        from localagent.workspace.context import resolve_workspace, scan_todos

        todos = len(scan_todos(resolve_workspace(), limit=todo_limit))
    except Exception:
        todos = 0

    pending = 0
    try:
        pending = pending_count()
    except Exception:
        pending = 0

    news = False
    try:
        news = today_synced()
    except Exception:
        news = False

    return DailyActionsStatus(
        news_synced_today=news,
        pending_count=pending,
        todo_count=todos,
    )


def format_daily_actions_lines(status: DailyActionsStatus | None = None) -> list[str]:
    """Short lines for welcome banner / status command."""
    status = status or collect_daily_actions_status()
    news = "今日新闻已就绪" if status.news_synced_today else "今日新闻未 sync"
    return [
        f"新闻 · {news}",
        f"记忆 pending · {status.pending_count}",
        f"workspace 待办 · {status.todo_count}",
    ]


def format_daily_actions_report(status: DailyActionsStatus | None = None) -> str:
    """Full `la status` output."""
    status = status or collect_daily_actions_status()
    lines = [
        "LocalAgent · Daily Actions",
        "Local First. Memory Forever. Actions Automated.",
        "",
        *format_daily_actions_lines(status),
        "",
        "提示：",
        "  la news brief          # 今日简报",
        "  la memory pending      # 审阅待写入记忆",
        "  la workspace --todos-only  # 工作区待办",
    ]
    return "\n".join(lines)
