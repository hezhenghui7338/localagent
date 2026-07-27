"""Local wall-clock timezone for user-facing dates/times (LA_TZ)."""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def reset_tz_cache() -> None:
    """Clear cached LA_TZ resolution (tests / env reload)."""
    resolve_local_tz.cache_clear()


@lru_cache(maxsize=1)
def resolve_local_tz() -> timezone | ZoneInfo:
    """IANA zone from LA_TZ, else system local timezone."""
    name = os.getenv("LA_TZ", "").strip()
    if name:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:
            pass
    local = datetime.now().astimezone()
    tz = local.tzinfo
    if tz is None:
        return timezone.utc
    return tz


def local_now() -> datetime:
    """Current wall clock in LA_TZ (or system local)."""
    return datetime.now(resolve_local_tz())


def local_today() -> date:
    """Calendar date in LA_TZ (or system local)."""
    return local_now().date()


def to_local_dt(ts: str | datetime | None) -> datetime | None:
    """Project an ISO timestamp or datetime to LA_TZ wall clock."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts
    else:
        text = str(ts).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    tz = resolve_local_tz()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)
