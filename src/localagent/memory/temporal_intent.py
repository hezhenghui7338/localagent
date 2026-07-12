"""Parse temporal intent from user queries for scoped recall."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from localagent.memory.core_profile import CoreProfile, LifeAnchor


@dataclass
class TemporalIntent:
    anchor_date: str | None = None
    anchor_label: str | None = None
    scope_start: str | None = None
    scope_end: str | None = None
    keywords: list[str] = field(default_factory=list)
    raw_query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "anchor_date": self.anchor_date,
            "anchor_label": self.anchor_label,
            "scope_start": self.scope_start,
            "scope_end": self.scope_end,
            "keywords": self.keywords,
            "raw_query": self.raw_query,
        }


_RELATIVE_PATTERNS = [
    (re.compile(r"上周|上个星期"), -7),
    (re.compile(r"上个月|上月"), -30),
    (re.compile(r"去年"), -365),
    (re.compile(r"今年"), 0),
    (re.compile(r"最近|近期"), -14),
]

_YEAR_RE = re.compile(r"(20\d{2})年?")
_MONTH_RE = re.compile(r"(20\d{2})年(\d{1,2})月")


def parse_temporal_intent(query: str, profile: CoreProfile | None = None) -> TemporalIntent:
    now = datetime.now()
    intent = TemporalIntent(raw_query=query, keywords=_extract_keywords(query))

    for pattern, days_offset in _RELATIVE_PATTERNS:
        if pattern.search(query):
            from datetime import timedelta

            anchor = now + timedelta(days=days_offset)
            intent.anchor_date = anchor.strftime("%Y-%m-%d")
            intent.scope_start = (anchor - timedelta(days=30)).strftime("%Y-%m-%d")
            intent.scope_end = now.strftime("%Y-%m-%d")
            break

    month_match = _MONTH_RE.search(query)
    if month_match:
        year = int(month_match.group(1))
        month = int(month_match.group(2))
        from calendar import monthrange

        last_day = monthrange(year, month)[1]
        intent.anchor_date = f"{year}-{month:02d}-15"
        intent.scope_start = f"{year}-{month:02d}-01"
        intent.scope_end = f"{year}-{month:02d}-{last_day:02d}"
    else:
        year_match = _YEAR_RE.search(query)
        if year_match and not intent.anchor_date:
            year = int(year_match.group(1))
            intent.anchor_date = f"{year}-06-15"
            intent.scope_start = f"{year}-01-01"
            intent.scope_end = f"{year}-12-31"

    if profile:
        for anchor in profile.life_anchors:
            if anchor.label in query or (anchor.description and anchor.description in query):
                intent.anchor_label = anchor.label
                intent.anchor_date = anchor.start
                intent.scope_start = anchor.start
                intent.scope_end = anchor.end or now.strftime("%Y-%m-%d")
                break

    return intent


def _extract_keywords(query: str) -> list[str]:
    stop = {"的", "了", "是", "在", "我", "你", "他", "她", "什么", "怎么", "哪", "吗", "呢"}
    tokens = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", query)
    return [t for t in tokens if t not in stop and len(t) > 1]
