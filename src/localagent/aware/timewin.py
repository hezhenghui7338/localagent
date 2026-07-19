"""Parse aware --since time windows + local clock / period labels."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from localagent.i18n import t

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

# Stable English keys for rollups / signals (not localized).
_PERIOD_KEYS = (
    (5, 8, "dawn"),
    (8, 12, "morning"),
    (12, 18, "afternoon"),
    (18, 20, "evening"),
    (20, 24, "night"),
)


@dataclass(frozen=True)
class QueryWindow:
    """Resolved time intent for aware retrieval."""

    since_token: str
    since_hours: float
    tier: str  # hot | episodes | rollup
    prefer_rollup: bool = False
    label: str = ""


def parse_since(value: str | None) -> str:
    """Normalize since token; default 1w when None or empty."""
    text = (value or DEFAULT_SINCE).strip().lower()
    if not _SINCE_RE.fullmatch(text):
        raise ValueError(t("aware.since_invalid", value=value))
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
    return t("aware.recent_n", n=n, unit=t(f"aware.unit_{unit}"))


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


def period_key(ts: str | datetime | None) -> str:
    """Stable English period bucket for storage / rollups."""
    local = to_local(ts)
    if local is None:
        return ""
    h = local.hour
    for lo, hi, key in _PERIOD_KEYS:
        if lo <= h < hi:
            return key
    return "late"


def period_label(ts: str | datetime | None) -> str:
    """Local hour bucket: dawn / morning / afternoon / evening / night / late."""
    key = period_key(ts)
    if not key:
        return ""
    return t(f"aware.period_{key}")


def since_token_to_hours(value: str | None) -> float:
    """Approximate hours covered by a since token (for legacy since_hours APIs)."""
    key = parse_since(value)
    n, unit = _split_since(key)
    if unit == "h":
        return float(n)
    if unit == "d":
        return float(n * 24)
    if unit == "w":
        return float(n * 24 * 7)
    if unit == "m":
        return float(n * 24 * 30)
    return float(n * 24 * 365)


def infer_query_window(query: str = "", *, default_token: str = "3h") -> QueryWindow:
    """Heuristic time intent from user text (rules first; no LLM)."""
    q = (query or "").strip().lower()
    if not q:
        tok = parse_since(default_token)
        return QueryWindow(
            since_token=tok,
            since_hours=since_token_to_hours(tok),
            tier="hot",
            prefer_rollup=False,
            label="default",
        )

    # Order matters: more specific / longer-horizon first.
    rules: list[tuple[re.Pattern[str], str, str, bool, str]] = [
        (re.compile(r"(上个月|上月|last\s*month|past\s*month)"), "1m", "rollup", True, "month"),
        (re.compile(r"(上周|上星期|last\s*week|past\s*week)"), "1w", "rollup", True, "last_week"),
        (
            re.compile(r"(这周|这一周|最近几天|这几天|this\s*week|past\s*few\s*days|recent\s*days)"),
            "1w",
            "rollup",
            True,
            "week",
        ),
        (re.compile(r"(昨天|昨日|昨晚|yesterday|last\s*night)"), "2d", "episodes", False, "yesterday"),
        (
            re.compile(
                r"(今天|今日|今早|今天上午|今天下午|今晚|今天晚上|\btoday\b|this\s*morning|"
                r"this\s*afternoon|tonight)"
            ),
            "1d",
            "episodes",
            False,
            "today",
        ),
        (
            re.compile(
                r"(刚才|刚刚|现在|此刻|在听|正在听|在看什么|just\s*now|right\s*now|"
                r"currently|what\s*am\s*i\s*(listening|watching))"
            ),
            "3h",
            "hot",
            False,
            "now",
        ),
        (re.compile(r"(最近|recently|lately)"), "3h", "hot", False, "recent"),
    ]
    for pat, token, tier, prefer_rollup, label in rules:
        if pat.search(q):
            tok = parse_since(token)
            return QueryWindow(
                since_token=tok,
                since_hours=since_token_to_hours(tok),
                tier=tier,
                prefer_rollup=prefer_rollup,
                label=label,
            )
    tok = parse_since(default_token)
    return QueryWindow(
        since_token=tok,
        since_hours=since_token_to_hours(tok),
        tier="episodes",
        prefer_rollup=False,
        label="fallback",
    )


def day_part_label(ts: str | datetime | None) -> str:
    """Coarse day/night label for narrative: day / night / late."""
    local = to_local(ts)
    if local is None:
        return ""
    h = local.hour
    if 5 <= h < 18:
        return t("aware.daypart_day")
    if 18 <= h < 24:
        return t("aware.daypart_night")
    return t("aware.daypart_late")


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
