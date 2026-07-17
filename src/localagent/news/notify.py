"""Startup notification when today's news sync is ready."""

from __future__ import annotations

from datetime import datetime

from localagent import config
from localagent.news.profile import load_news_profile
from localagent.news.store import (
    mark_ready_notified,
    ready_already_notified,
    today_synced,
)


def past_sync_time(*, now: datetime | None = None) -> bool:
    """True when local clock is at/after configured auto-sync time."""
    now = now or datetime.now()
    profile = load_news_profile()
    hour = profile.auto_sync_hour if config.NEWS_AUTO_SYNC else config.NEWS_AUTO_SYNC_HOUR
    minute = (
        profile.auto_sync_minute
        if config.NEWS_AUTO_SYNC
        else config.NEWS_AUTO_SYNC_MINUTE
    )
    return (now.hour, now.minute) >= (hour, minute)


def should_notify_news_ready(*, now: datetime | None = None) -> bool:
    if not past_sync_time(now=now):
        return False
    if not today_synced():
        return False
    if ready_already_notified():
        return False
    return True


def news_ready_message() -> str:
    return "[news] 今日更新已准备好，可随时查看：la news brief"


def maybe_print_news_ready(*, now: datetime | None = None) -> bool:
    """Print ready notice once per day after sync time. Returns True if printed."""
    if not should_notify_news_ready(now=now):
        return False
    print(news_ready_message())
    mark_ready_notified()
    return True
