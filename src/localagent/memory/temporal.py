"""Memory time resolution: occurred, recorded, and indexed timestamps."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# 2024年6月15日 / 2024年6月 / 2024年
_CJK_DATE_RE = re.compile(
    r"(20\d{2})\s*年(?:\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?)?"
)
# 2024-06-15 / 2024/06/15
_ISOISH_DATE_RE = re.compile(
    r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})"
)


def _normalize_date(year: int, month: int | None = None, day: int | None = None) -> str:
    month = month or 1
    day = day or 1
    month = max(1, min(12, month))
    day = max(1, min(31, day))
    return f"{year:04d}-{month:02d}-{day:02d}"


def extract_occurred_at(text: str) -> str | None:
    """Extract the first explicit calendar date mentioned in text."""
    text = text.strip()
    if not text:
        return None

    match = _ISOISH_DATE_RE.search(text)
    if match:
        year, month, day = (int(match.group(i)) for i in range(1, 4))
        return _normalize_date(year, month, day)

    match = _CJK_DATE_RE.search(text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2)) if match.group(2) else None
        day = int(match.group(3)) if match.group(3) else None
        return _normalize_date(year, month, day)

    return None


def effective_memory_time(
    *,
    occurred_at: str | None = None,
    recorded_at: str | None = None,
    indexed_at: str | None = None,
    created_at: str | None = None,
) -> str:
    """Return the best time for recall/sort: occurred > recorded > indexed > legacy created_at."""
    for candidate in (occurred_at, recorded_at, indexed_at, created_at):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return datetime.now().isoformat(timespec="seconds")


def resolve_memory_times(
    *,
    text: str = "",
    occurred_at: str | None = None,
    recorded_at: str | None = None,
    indexed_at: str | None = None,
    legacy_created_at: str | None = None,
    extract_occurred_from_text: bool = True,
) -> dict[str, str]:
    """Build normalized occurred/recorded/indexed fields for a memory fact."""
    if not occurred_at and extract_occurred_from_text and text:
        occurred_at = extract_occurred_at(text)

    if not recorded_at and legacy_created_at:
        recorded_at = legacy_created_at

    if not indexed_at:
        indexed_at = datetime.now().isoformat(timespec="seconds")

    effective = effective_memory_time(
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        indexed_at=indexed_at,
        created_at=legacy_created_at,
    )

    result: dict[str, str] = {"indexed_at": indexed_at, "effective_at": effective}
    if occurred_at:
        result["occurred_at"] = occurred_at
    if recorded_at:
        result["recorded_at"] = recorded_at
    return result


def memory_effective_time(*, metadata: dict[str, Any] | None, created_at: str = "") -> str:
    """Resolve effective time from a stored fact or recall hit."""
    meta = metadata or {}
    return effective_memory_time(
        occurred_at=str(meta.get("occurred_at") or "") or None,
        recorded_at=str(meta.get("recorded_at") or "") or None,
        indexed_at=str(meta.get("indexed_at") or "") or None,
        created_at=created_at or None,
    )
