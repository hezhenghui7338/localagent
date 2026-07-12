"""Scoped memory recall with temporal weighting."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from localagent import config
from localagent.memory.core_profile import load_core_profile
from localagent.memory.temporal import memory_effective_time
from localagent.memory.store import get_memory_store
from localagent.memory.temporal_intent import parse_temporal_intent


_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+")
_QUERY_STOP_PHRASES = (
    "什么",
    "怎么",
    "哪些",
    "哪个",
    "为什么",
    "是不是",
    "有没有",
    "能不能",
    "可不可以",
)
_QUERY_STOP_CHARS = frozenset("的吗呢啊吧呀么了哦哈嗯")


def _expand_token(token: str) -> set[str]:
    if _CJK_RE.fullmatch(token):
        return set(token)
    return {token}


def _tokenize(text: str, *, for_query: bool = False) -> set[str]:
    terms: set[str] = set()
    for token in _TOKEN_RE.findall(text.lower()):
        terms.update(_expand_token(token))
    if for_query:
        for phrase in _QUERY_STOP_PHRASES:
            if phrase in text:
                terms.difference_update(phrase)
        terms.difference_update(_QUERY_STOP_CHARS)
    return terms


def _semantic_score(query: str, text: str) -> float:
    q_terms = _tokenize(query, for_query=True)
    t_terms = _tokenize(text)
    if not q_terms:
        return 0.0
    overlap = len(q_terms & t_terms)
    return overlap / len(q_terms)


def _temporal_score(effective_at: str, anchor_date: str | None) -> float:
    if not effective_at or not anchor_date:
        return 0.5
    try:
        created = datetime.fromisoformat(effective_at)
        anchor = datetime.fromisoformat(anchor_date)
        days = abs((created - anchor).total_seconds()) / 86400.0
        half_life = config.TIME_DECAY_HALFLIFE_DAYS
        return math.pow(0.5, days / half_life)
    except Exception:
        return 0.5


def rerank_hits_temporally(
    query: str,
    hits: list[dict[str, Any]],
    *,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Re-rank recall hits with temporal intent (for Hindsight recall results)."""
    profile = load_core_profile()
    intent = parse_temporal_intent(query, profile)

    scored: list[tuple[float, dict[str, Any]]] = []
    for hit in hits:
        meta = hit.get("metadata") or {}
        searchable = " ".join(
            part for part in (
                str(hit.get("text") or ""),
                str(meta.get("title") or ""),
                str(meta.get("summary") or ""),
                " ".join(meta.get("tags") or []),
                str(hit.get("section_heading") or ""),
            )
            if part
        )
        sem = _semantic_score(query, searchable) if query.strip() else hit.get("score", 1.0)
        effective_at = memory_effective_time(
            metadata=hit.get("metadata"),
            created_at=str(hit.get("created_at") or ""),
        )
        temp = _temporal_score(effective_at, intent.anchor_date)
        base_score = float(hit.get("score") or 0.0)
        if query.strip():
            blended = config.SEMANTIC_WEIGHT * max(sem, base_score * 0.5) + (
                1 - config.SEMANTIC_WEIGHT
            ) * temp
        else:
            blended = base_score
        enriched = dict(hit)
        enriched["score"] = blended
        enriched["semantic_score"] = sem if query.strip() else None
        enriched["temporal_score"] = temp
        enriched["anchor"] = intent.to_dict()
        scored.append((blended, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in scored[:max_results]]


def scoped_recall(query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
    """Recall memories with semantic + temporal scoring."""
    profile = load_core_profile()
    intent = parse_temporal_intent(query, profile)
    store = get_memory_store()
    facts = store.all_facts()

    scored: list[tuple[float, dict[str, Any]]] = []
    for fact in facts:
        meta = fact.metadata or {}
        searchable = " ".join(
            part for part in (
                fact.text,
                str(meta.get("title") or ""),
                str(meta.get("summary") or ""),
                " ".join(meta.get("tags") or []),
                fact.section_heading,
            )
            if part
        )
        sem = _semantic_score(query, searchable)
        if sem <= 0:
            continue
        effective_at = memory_effective_time(metadata=fact.metadata, created_at=fact.created_at)
        temp = _temporal_score(effective_at, intent.anchor_date)
        blended = config.SEMANTIC_WEIGHT * sem + (1 - config.SEMANTIC_WEIGHT) * temp
        scored.append((
            blended,
            {
                "id": fact.id,
                "text": fact.text,
                "score": blended,
                "semantic_score": sem,
                "temporal_score": temp,
                "source_file": fact.source_file,
                "section_heading": fact.section_heading,
                "created_at": effective_at,
                "metadata": fact.metadata,
                "anchor": intent.to_dict(),
            },
        ))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:max_results]]
