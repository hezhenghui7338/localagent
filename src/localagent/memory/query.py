"""Structured memory query: filter by tags/time, sort, and semantic match."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from localagent import config
from localagent.memory.core_profile import load_core_profile
from localagent.memory.backend import get_memory_backend
from localagent.memory.scoped_recall import (
    _intent_temporal_score,
    _lexical_overlap_score,
    _storage_time,
)
from localagent.memory.store import MemoryFact, get_memory_store
from localagent.memory.temporal import memory_effective_time, memory_recorded_time, parse_timestamp
from localagent.memory.temporal_intent import parse_temporal_intent

SortOrder = Literal["newest", "oldest", "relevance"]
TimeField = Literal["effective", "recorded"]


def _parse_date(value: str) -> datetime | None:
    return parse_timestamp(value)


def _fact_tags(fact: MemoryFact) -> list[str]:
    meta = fact.metadata or {}
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        return [tags] if tags else []
    return [str(tag).strip() for tag in tags if str(tag).strip()]


def _searchable_text(fact: MemoryFact) -> str:
    meta = fact.metadata or {}
    return " ".join(
        part for part in (
            fact.text,
            str(meta.get("title") or ""),
            str(meta.get("summary") or ""),
            " ".join(_fact_tags(fact)),
            fact.section_heading,
        )
        if part
    )


def _matches_tags(fact: MemoryFact, tags: list[str], *, mode: str) -> bool:
    if not tags:
        return True
    fact_tags = {tag.lower() for tag in _fact_tags(fact)}
    wanted = {tag.strip().lower() for tag in tags if tag.strip()}
    if not wanted:
        return True
    if mode == "all":
        return wanted.issubset(fact_tags)
    return bool(wanted & fact_tags)


def _fact_time(fact: MemoryFact, *, time_field: TimeField) -> str:
    if time_field == "recorded":
        return memory_recorded_time(metadata=fact.metadata, created_at=fact.created_at)
    return memory_effective_time(metadata=fact.metadata, created_at=fact.created_at)


def _in_time_range(
    fact: MemoryFact,
    *,
    since: datetime | None,
    until: datetime | None,
    time_field: TimeField = "effective",
) -> bool:
    if not since and not until:
        return True
    stamp = _fact_time(fact, time_field=time_field)
    created = _parse_date(stamp)
    if created is None:
        return True
    if since and created < since:
        return False
    if until and created > until:
        return False
    return True


def _fact_to_hit(fact: MemoryFact, *, score: float = 0.0, **extra: Any) -> dict[str, Any]:
    effective_at = memory_effective_time(metadata=fact.metadata, created_at=fact.created_at)
    return {
        "id": fact.id,
        "text": fact.text,
        "score": score,
        "source_file": fact.source_file,
        "section_heading": fact.section_heading,
        "created_at": effective_at,
        "metadata": fact.metadata,
        **extra,
    }


def list_memory_tags(*, limit: int = 50) -> list[tuple[str, int]]:
    """Return unique tags with occurrence counts, sorted by count desc."""
    counts: dict[str, int] = {}
    for fact in get_memory_store().all_facts():
        for tag in _fact_tags(fact):
            key = tag.lower()
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:limit]


def query_memories(
    *,
    query: str = "",
    tags: list[str] | None = None,
    tag_mode: str = "any",
    since: str | None = None,
    until: str | None = None,
    sort: SortOrder = "newest",
    limit: int = 20,
    time_field: TimeField = "effective",
) -> list[dict[str, Any]]:
    """Query memories with optional semantic match, tag/time filters, and sorting."""
    query = query.strip()
    since_dt = _parse_date(since) if since else None
    until_dt = _parse_date(until) if until else None
    if until_dt:
        until_dt = until_dt.replace(hour=23, minute=59, second=59)

    if query and sort == "relevance":
        candidates = get_memory_backend().recall(query, max_results=max(limit * 3, 20))
    else:
        candidates = [
            _fact_to_hit(fact)
            for fact in get_memory_store().all_facts()
        ]

    intent = parse_temporal_intent(query, load_core_profile()) if query else None

    hits: list[dict[str, Any]] = []
    for hit in candidates:
        fact_like = MemoryFact(
            id=str(hit.get("id") or ""),
            text=str(hit.get("text") or ""),
            source_file=str(hit.get("source_file") or ""),
            section_heading=str(hit.get("section_heading") or ""),
            created_at=str(hit.get("created_at") or ""),
            metadata=dict(hit.get("metadata") or {}),
        )
        if not _matches_tags(fact_like, tags or [], mode=tag_mode):
            continue
        if not _in_time_range(
            fact_like,
            since=since_dt,
            until=until_dt,
            time_field=time_field,
        ):
            continue

        if query and sort != "relevance":
            searchable = _searchable_text(fact_like)
            lexical = _lexical_overlap_score(query, searchable)
            effective_at = memory_effective_time(
                metadata=fact_like.metadata,
                created_at=fact_like.created_at,
            )
            storage_at = _storage_time(
                metadata=fact_like.metadata,
                created_at=fact_like.created_at,
            )
            temp = (
                _intent_temporal_score(
                    effective_at=effective_at,
                    storage_at=storage_at,
                    intent=intent,
                )
                if intent
                else 0.5
            )
            # Soft lexical boost only — never drop on zero overlap.
            lex_weight = (
                min(float(config.SEMANTIC_WEIGHT), 0.60)
                if intent and intent.raises_temporal_weight
                else float(config.SEMANTIC_WEIGHT)
            )
            blended = lex_weight * lexical + (1 - lex_weight) * temp
            hit = dict(hit)
            hit["score"] = blended
            hit["semantic_score"] = lexical
            hit["lexical_score"] = lexical
            hit["temporal_score"] = temp
            if intent:
                hit["anchor"] = intent.to_dict()
        elif sort == "relevance" and query:
            hit = dict(hit)

        # Surface recorded time for archive-style answers.
        if time_field == "recorded":
            hit = dict(hit)
            hit["created_at"] = _fact_time(fact_like, time_field="recorded")

        hits.append(hit)

    effective_sort = sort
    if effective_sort == "relevance" and not query:
        effective_sort = "newest"

    if effective_sort == "relevance":
        hits.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    elif effective_sort == "oldest":
        hits.sort(key=lambda hit: hit.get("created_at", ""))
    else:
        hits.sort(key=lambda hit: hit.get("created_at", ""), reverse=True)

    return hits[:limit]
