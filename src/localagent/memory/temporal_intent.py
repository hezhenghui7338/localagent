"""Parse temporal intent from user queries for scoped recall."""

from __future__ import annotations

import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from localagent.memory.core_profile import CoreProfile

IntentKind = Literal["none", "as_of_now", "range", "when_event", "duration"]


@dataclass
class TemporalIntent:
    intent_kind: IntentKind = "none"
    anchor_date: str | None = None
    anchor_label: str | None = None
    scope_start: str | None = None
    scope_end: str | None = None
    keywords: list[str] = field(default_factory=list)
    raw_query: str = ""
    reference_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_kind": self.intent_kind,
            "anchor_date": self.anchor_date,
            "anchor_label": self.anchor_label,
            "scope_start": self.scope_start,
            "scope_end": self.scope_end,
            "keywords": self.keywords,
            "raw_query": self.raw_query,
            "reference_date": self.reference_date,
        }

    @property
    def has_time_scope(self) -> bool:
        return bool(self.scope_start and self.scope_end)

    @property
    def raises_temporal_weight(self) -> bool:
        """Range / as-of-now queries should lean harder on time alignment."""
        return self.intent_kind in ("range", "as_of_now")

    @property
    def prefers_event_neighbors(self) -> bool:
        """WHEN / duration questions benefit from ±N dialog turns around evidence."""
        return self.intent_kind in ("when_event", "duration")


_AS_OF_NOW_RE = re.compile(
    r"(现在|目前|当前|如今|nowadays|currently|right\s+now|these\s+days|"
    r"\bnow\b|"
    r"(where|what).{0,40}\bnow\b|"
    r"\bas\s+of\s+(today|now)\b)",
    re.IGNORECASE,
)
_WHEN_EVENT_RE = re.compile(
    r"(什么时候|何时|哪一天|哪天|"
    r"\bwhen\s+did\b|\bwhen\s+was\b|\bwhen\s+is\b|\bwhen\s+were\b|"
    r"\bwhen\s+will\b|\bon\s+what\s+date\b|\bwhat\s+date\b)",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(
    r"(多久以前|多长时间|多久|"
    r"\bhow\s+long\s+ago\b|\bhow\s+long\b|\bfor\s+how\s+long\b)",
    re.IGNORECASE,
)

# (pattern, kind, days_offset or special tag)
_RELATIVE_CN = [
    (re.compile(r"上周|上个星期"), "week", -7),
    (re.compile(r"这周|这个星期|本周"), "week", 0),
    (re.compile(r"上个月|上月"), "month", -30),
    (re.compile(r"这个月|本月"), "month", 0),
    (re.compile(r"去年"), "year", -365),
    (re.compile(r"今年"), "year", 0),
    (re.compile(r"最近|近期"), "recent", -14),
]
_RELATIVE_EN = [
    (re.compile(r"\blast\s+week\b", re.I), "week", -7),
    (re.compile(r"\bthis\s+week\b", re.I), "week", 0),
    (re.compile(r"\blast\s+month\b", re.I), "month", -30),
    (re.compile(r"\bthis\s+month\b", re.I), "month", 0),
    (re.compile(r"\blast\s+year\b", re.I), "year", -365),
    (re.compile(r"\bthis\s+year\b", re.I), "year", 0),
    (re.compile(r"\byesterday\b", re.I), "day", -1),
    (re.compile(r"\btoday\b", re.I), "day", 0),
    (re.compile(r"\brecently\b|\blately\b", re.I), "recent", -14),
]

_YEAR_RE = re.compile(r"(20\d{2})年?")
_MONTH_RE = re.compile(r"(20\d{2})年(\d{1,2})月")
_EN_MONTH_YEAR_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(20\d{2})\b",
    re.IGNORECASE,
)
_EN_YEAR_ONLY_RE = re.compile(r"\bin\s+(20\d{2})\b", re.IGNORECASE)

_MONTH_NAME_TO_NUM = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _parse_reference(reference_date: str | datetime | None) -> datetime:
    if reference_date is None:
        return datetime.now()
    if isinstance(reference_date, datetime):
        return reference_date
    text = str(reference_date).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return datetime.now()


def _set_range(
    intent: TemporalIntent,
    *,
    anchor: datetime,
    scope_start: datetime,
    scope_end: datetime,
    label: str | None = None,
) -> None:
    intent.intent_kind = "range"
    intent.anchor_date = anchor.strftime("%Y-%m-%d")
    intent.scope_start = scope_start.strftime("%Y-%m-%d")
    intent.scope_end = scope_end.strftime("%Y-%m-%d")
    if label:
        intent.anchor_label = label


def _apply_relative_unit(
    intent: TemporalIntent,
    *,
    now: datetime,
    unit: str,
    offset: int,
) -> None:
    if unit == "day":
        day = (now + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        _set_range(intent, anchor=day, scope_start=day, scope_end=day)
        return
    if unit == "week":
        # Monday-start week containing the offset day.
        tip = now + timedelta(days=offset)
        start = (tip - timedelta(days=tip.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(days=6)
        _set_range(intent, anchor=start + timedelta(days=3), scope_start=start, scope_end=end)
        return
    if unit == "month":
        tip = now + timedelta(days=offset)
        start = tip.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last = monthrange(start.year, start.month)[1]
        end = start.replace(day=last)
        _set_range(
            intent,
            anchor=start.replace(day=min(15, last)),
            scope_start=start,
            scope_end=end,
        )
        return
    if unit == "year":
        year = now.year + (-1 if offset < 0 else 0)
        start = datetime(year, 1, 1)
        end = datetime(year, 12, 31)
        _set_range(intent, anchor=datetime(year, 6, 15), scope_start=start, scope_end=end)
        return
    # recent: trailing window ending at now
    start = now + timedelta(days=offset)
    _set_range(intent, anchor=now, scope_start=start, scope_end=now)


def parse_temporal_intent(
    query: str,
    profile: CoreProfile | None = None,
    *,
    reference_date: str | datetime | None = None,
) -> TemporalIntent:
    """Classify query time intent and optionally resolve a calendar scope.

    Intent kinds:
    - ``range``: explicit/relative calendar window (去年、last week、2023年5月)
    - ``as_of_now``: current-state questions (现在住哪)
    - ``when_event``: ask when an event happened (When did X…?) — usually no anchor
    - ``duration``: how long / 多久以前
    - ``none``: no temporal signal
    """
    now = _parse_reference(reference_date)
    intent = TemporalIntent(
        raw_query=query,
        keywords=_extract_keywords(query),
        reference_date=now.strftime("%Y-%m-%d"),
    )
    if not (query or "").strip():
        return intent

    # 1) Explicit calendar ranges win when present.
    month_match = _MONTH_RE.search(query)
    if month_match:
        year = int(month_match.group(1))
        month = int(month_match.group(2))
        last_day = monthrange(year, month)[1]
        _set_range(
            intent,
            anchor=datetime(year, month, min(15, last_day)),
            scope_start=datetime(year, month, 1),
            scope_end=datetime(year, month, last_day),
        )
    else:
        en_month = _EN_MONTH_YEAR_RE.search(query)
        if en_month:
            month = _MONTH_NAME_TO_NUM.get(en_month.group(1).lower()[:3], 0) or _MONTH_NAME_TO_NUM.get(
                en_month.group(1).lower(), 0
            )
            year = int(en_month.group(2))
            if month:
                last_day = monthrange(year, month)[1]
                _set_range(
                    intent,
                    anchor=datetime(year, month, min(15, last_day)),
                    scope_start=datetime(year, month, 1),
                    scope_end=datetime(year, month, last_day),
                )
        else:
            year_match = _YEAR_RE.search(query) or _EN_YEAR_ONLY_RE.search(query)
            if year_match:
                year = int(year_match.group(1))
                _set_range(
                    intent,
                    anchor=datetime(year, 6, 15),
                    scope_start=datetime(year, 1, 1),
                    scope_end=datetime(year, 12, 31),
                )

    # 2) Relative windows (fill only if no explicit calendar yet).
    if intent.intent_kind == "none":
        for pattern, unit, offset in _RELATIVE_CN + _RELATIVE_EN:
            if pattern.search(query):
                _apply_relative_unit(intent, now=now, unit=unit, offset=offset)
                break

    # 3) Life-profile anchors.
    if profile and intent.intent_kind == "none":
        for anchor in profile.life_anchors:
            if anchor.label in query or (anchor.description and anchor.description in query):
                intent.intent_kind = "range"
                intent.anchor_label = anchor.label
                intent.anchor_date = anchor.start
                intent.scope_start = anchor.start
                intent.scope_end = anchor.end or now.strftime("%Y-%m-%d")
                break

    # 4) as_of_now / when_event / duration — only when no calendar range already set.
    if intent.intent_kind == "none":
        if _AS_OF_NOW_RE.search(query):
            intent.intent_kind = "as_of_now"
            intent.anchor_date = now.strftime("%Y-%m-%d")
            intent.scope_start = (now - timedelta(days=90)).strftime("%Y-%m-%d")
            intent.scope_end = now.strftime("%Y-%m-%d")
        elif _DURATION_RE.search(query):
            intent.intent_kind = "duration"
        elif _WHEN_EVENT_RE.search(query):
            intent.intent_kind = "when_event"

    return intent


def _extract_keywords(query: str) -> list[str]:
    stop = {
        "的", "了", "是", "在", "我", "你", "他", "她", "什么", "怎么", "哪", "吗", "呢",
        "when", "what", "where", "who", "how", "did", "was", "were", "the", "a", "an",
    }
    tokens = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", query)
    return [t for t in tokens if t.lower() not in stop and len(t) > 1]
