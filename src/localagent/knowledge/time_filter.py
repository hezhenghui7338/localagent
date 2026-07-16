"""Date-range helpers for Cold knowledge / conversation chunks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from localagent.memory.temporal import in_time_window, memory_recorded_time, parse_timestamp, to_ymd


def chunk_recorded_at(metadata: dict[str, Any] | None) -> str:
    """Best conversation time from Cold chunk metadata."""
    meta = metadata or {}
    ymd = str(meta.get("recorded_at_ymd") or "").strip()
    if ymd:
        return ymd
    return memory_recorded_time(metadata=meta)


def parse_range_bounds(
    since: str | None,
    until: str | None,
) -> tuple[datetime | None, datetime | None]:
    since_dt = parse_timestamp(since) if since else None
    until_dt = parse_timestamp(until) if until else None
    if until_dt:
        until_dt = until_dt.replace(hour=23, minute=59, second=59)
    return since_dt, until_dt


def meta_in_range(
    metadata: dict[str, Any] | None,
    *,
    since: datetime | None,
    until: datetime | None,
) -> bool:
    """Hard filter: undated conversation chunks are excluded when a window is set."""
    if not since and not until:
        return True
    return in_time_window(
        chunk_recorded_at(metadata),
        since=since,
        until=until,
        keep_undated=False,
    )


def format_recorded_label(metadata: dict[str, Any] | None) -> str:
    stamp = chunk_recorded_at(metadata)
    ymd = to_ymd(stamp) or stamp
    return ymd
