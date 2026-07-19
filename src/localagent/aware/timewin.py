"""Parse aware --since time windows + local clock / period labels."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

# Common suggestions for help / tab completion (not an exhaustive allow-list).
SINCE_CHOICES = ("3h", "1d", "1w", "1m", "1y", "2d", "7d")
DEFAULT_SINCE = "1w"

_SINCE_RE = re.compile(r"^(\d+)([hdwmy])$")

_UNIT_DELTA = {
    "h": lambda n: timedelta(hours=n),
    "d": lambda n: timedelta(days=n),
    "w": lambda n: timedelta(days=7 * n),
    "m": lambda n: timedelta(days=30 * n),
    "y": lambda n: timedelta(days=365 * n),
}

_UNIT_LABEL = {
    "h": "小时",
    "d": "天",
    "w": "周",
    "m": "个月",
    "y": "年",
}


def parse_since(value: str | None) -> str:
    """Normalize since token; default 1w when None or empty."""
    text = (value or DEFAULT_SINCE).strip().lower()
    if not _SINCE_RE.fullmatch(text):
        raise ValueError(
            f"无效 --since: {value!r}（格式: <N>h|<N>d|<N>w|<N>m|<N>y，如 3h、2d、1w）"
        )
    return text


def _split_since(key: str) -> tuple[int, str]:
    match = _SINCE_RE.fullmatch(key)
    assert match is not None
    return int(match.group(1)), match.group(2)


def since_to_datetime(value: str | None, *, now: datetime | None = None) -> datetime:
    key = parse_since(value)
    n, unit = _split_since(key)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - _UNIT_DELTA[unit](n)


def label_since(value: str | None) -> str:
    key = parse_since(value)
    n, unit = _split_since(key)
    return f"最近 {n} {_UNIT_LABEL[unit]}"


def parse_ts(ts: str | datetime | None) -> datetime | None:
    """Parse ISO timestamp (or datetime) to aware datetime; None if invalid."""
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
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def to_local(ts: str | datetime | None) -> datetime | None:
    """Convert ISO/datetime to local timezone."""
    dt = parse_ts(ts)
    if dt is None:
        return None
    return dt.astimezone()


def period_label(ts: str | datetime | None) -> str:
    """Local hour bucket: 清晨/上午/下午/傍晚/晚上/深夜."""
    local = to_local(ts)
    if local is None:
        return ""
    h = local.hour
    if 5 <= h < 8:
        return "清晨"
    if 8 <= h < 12:
        return "上午"
    if 12 <= h < 18:
        return "下午"
    if 18 <= h < 20:
        return "傍晚"
    if 20 <= h < 24:
        return "晚上"
    return "深夜"


def day_part_label(ts: str | datetime | None) -> str:
    """Coarse day/night label for narrative: 白天 / 晚上 / 深夜."""
    local = to_local(ts)
    if local is None:
        return ""
    h = local.hour
    if 5 <= h < 18:
        return "白天"
    if 18 <= h < 24:
        return "晚上"
    return "深夜"


def format_clock(
    ts: str | datetime | None,
    *,
    with_date: bool | None = None,
    ref: datetime | None = None,
) -> str:
    """Local clock: ``22:15`` same day, ``07-18 22:15`` when with_date or cross-day vs ref."""
    local = to_local(ts)
    if local is None:
        return ""
    if with_date is None:
        ref_local = (ref or datetime.now().astimezone()).astimezone()
        with_date = local.date() != ref_local.date()
    if with_date:
        return local.strftime("%m-%d %H:%M")
    return local.strftime("%H:%M")


def format_span(start: str | datetime | None, end: str | datetime | None) -> str:
    """Local span like ``22:15–23:40`` or ``07-18 22:15–07-19 01:10``."""
    a = to_local(start)
    b = to_local(end) or a
    if a is None:
        return ""
    if b is None:
        return format_clock(a, with_date=True)
    cross = a.date() != b.date()
    today = datetime.now().astimezone().date()
    if cross:
        return f"{format_clock(a, with_date=True)}–{format_clock(b, with_date=True)}"
    if a.date() != today:
        return f"{format_clock(a, with_date=True)}–{format_clock(b, with_date=False)}"
    return f"{format_clock(a, with_date=False)}–{format_clock(b, with_date=False)}"


def format_period_span(start: str | datetime | None, end: str | datetime | None) -> str:
    """Card prefix: ``晚上 22:15–23:40`` (period from start)."""
    span = format_span(start, end)
    if not span:
        return ""
    period = period_label(start) or period_label(end)
    if period:
        return f"{period} {span}"
    return span


def format_now_local() -> str:
    """Current local wall clock for prompt injection."""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def dominant_period(timestamps: list[Any]) -> str:
    """Most common period_label among timestamps; empty if none."""
    counts: dict[str, int] = {}
    for ts in timestamps:
        label = period_label(ts)
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def dominant_day_part(timestamps: list[Any]) -> str:
    """Most common day_part_label among timestamps."""
    counts: dict[str, int] = {}
    for ts in timestamps:
        label = day_part_label(ts)
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]
