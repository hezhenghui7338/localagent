"""Daily Actions surface — news / pending / workspace / aware signals."""

from __future__ import annotations

from dataclasses import dataclass, field

from localagent.i18n import t
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
    news = t("daily.news_ready") if status.news_synced_today else t("daily.news_unsynced")
    lines = [
        t("daily.news_line", news=news),
        t("daily.pending_line", n=status.pending_count),
        t("daily.todo_line", n=status.todo_count),
    ]
    for tid, title in status.todo_previews:
        short = title if len(title) <= 36 else title[:33] + "..."
        lines.append(f"  → [{tid}] {short}")
    if status.todo_count > 0:
        lines.append("  la workspace tasks / done <id>")
    lines.append(
        t(
            "daily.aware_line",
            events=status.aware_events_today,
            sug=status.aware_suggestion_count,
        )
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
        t("status.tips_header"),
        t("status.tip_news"),
        t("status.tip_pending"),
        t("status.tip_tasks"),
        t("status.tip_add"),
        t("status.tip_scan"),
        t("status.tip_aware"),
        t("status.tip_aware_since"),
        t("status.tip_aware_sug"),
        t("status.tip_ungrant"),
    ]
    return "\n".join(lines)
