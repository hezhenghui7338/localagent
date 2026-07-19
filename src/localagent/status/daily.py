"""Daily Actions surface — news / pending / workspace / aware signals."""

from __future__ import annotations

from dataclasses import dataclass, field

from localagent.news.store import today_synced
from localagent.pending.queue import pending_count


@dataclass(frozen=True)
class DailyActionsStatus:
    news_synced_today: bool
    pending_count: int
    todo_count: int
    aware_suggestion_count: int = 0
    aware_events_today: int = 0
    todo_previews: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def has_signal(self) -> bool:
        return (
            self.news_synced_today
            or self.pending_count > 0
            or self.todo_count > 0
            or self.aware_suggestion_count > 0
            or self.aware_events_today > 0
        )


def collect_daily_actions_status(*, todo_limit: int = 50) -> DailyActionsStatus:
    """Gather lightweight local signals for banner / `la status`."""
    todos = 0
    previews: list[tuple[str, str]] = []
    try:
        from localagent.workspace.tasks import remind_due, task_count_open

        todos = task_count_open()
        for item in remind_due(limit=min(2, max(0, todo_limit))):
            previews.append((item.id, item.title))
    except Exception:
        todos = 0
        previews = []

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

    aware_sug = 0
    aware_events = 0
    try:
        from localagent.aware.store import events_count_today
        from localagent.aware.suggestion import suggestion_count

        aware_sug = suggestion_count()
        aware_events = events_count_today()
    except Exception:
        pass

    return DailyActionsStatus(
        news_synced_today=news,
        pending_count=pending,
        todo_count=todos,
        aware_suggestion_count=aware_sug,
        aware_events_today=aware_events,
        todo_previews=tuple(previews),
    )


def format_daily_actions_lines(status: DailyActionsStatus | None = None) -> list[str]:
    """Short lines for welcome banner / status command."""
    status = status or collect_daily_actions_status()
    news = "今日新闻已就绪" if status.news_synced_today else "今日新闻未 sync"
    lines = [
        f"新闻 · {news}",
        f"记忆 pending · {status.pending_count}",
        f"workspace 待办 · {status.todo_count}",
    ]
    for tid, title in status.todo_previews:
        short = title if len(title) <= 36 else title[:33] + "..."
        lines.append(f"  → [{tid}] {short}")
    if status.todo_count > 0:
        lines.append("  la workspace tasks / done <id>")
    lines.append(
        f"aware · 今日事件 {status.aware_events_today} / suggestion {status.aware_suggestion_count}"
    )
    return lines


def format_daily_actions_report(status: DailyActionsStatus | None = None) -> str:
    """Daily Actions-only report (kept for tests / callers that want the short surface).

    Prefer :func:`localagent.status.report.format_status_report` for `la status`.
    """
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
        "  la workspace tasks     # 托管待办（done/dismiss/snooze）",
        "  la workspace add \"…\" --why \"…\"  # 显式添加待办",
        "  la workspace scan      # 诊断扫描代码 TODO（未入队）",
        "  la aware               # 当前状态 + 近 3 小时动态",
        "  la aware --since 1w    # 最近一周变化",
        "  la aware suggestion    # 感知建议（approve/reject 为其子命令）",
        "  la aware ungrant …     # 解除监测授权",
    ]
    return "\n".join(lines)
