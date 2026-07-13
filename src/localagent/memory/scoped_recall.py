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
    "你知道我",
    "你还记得",
    "记得我",
    "告诉我",
    "请问",
    "什么",
    "怎么",
    "怎样",
    "哪些",
    "哪个",
    "为什么",
    "是不是",
    "有没有",
    "能不能",
    "可不可以",
    "知道",
    "哪里",
    "哪儿",
    "如何",
    "多少",
)
_QUERY_STOP_CHARS = frozenset(
    "的吗呢啊吧呀么了哦哈嗯你我他她它谁何在是有被把和与及对到得地"
)
_QUERY_SYNONYMS: dict[str, frozenset[str]] = {
    "住": frozenset({"住", "居住", "住在", "住址", "住所", "位于"}),
    "居住": frozenset({"住", "居住", "住在", "住址", "住所"}),
    "住在": frozenset({"住", "居住", "住在", "住址"}),
    "住址": frozenset({"住", "居住", "住址", "住所"}),
    "位于": frozenset({"位于", "住", "居住", "住在"}),
}


def _clean_query_text(text: str) -> str:
    cleaned = text
    for phrase in sorted(_QUERY_STOP_PHRASES, key=len, reverse=True):
        if phrase in cleaned:
            cleaned = cleaned.replace(phrase, " ")
    return cleaned


def _cjk_terms(token: str, *, for_query: bool) -> set[str]:
    terms: set[str] = set()
    if len(token) >= 2:
        for i in range(len(token) - 1):
            bigram = token[i : i + 2]
            if for_query and all(ch in _QUERY_STOP_CHARS for ch in bigram):
                continue
            terms.add(bigram)
    for ch in token:
        if for_query and ch in _QUERY_STOP_CHARS:
            continue
        terms.add(ch)
    return terms


def _expand_query_terms(terms: set[str]) -> set[str]:
    expanded = set(terms)
    for term in list(terms):
        synonyms = _QUERY_SYNONYMS.get(term)
        if synonyms:
            expanded.update(synonyms)
    return expanded


def _tokenize(text: str, *, for_query: bool = False) -> set[str]:
    source = _clean_query_text(text) if for_query else text
    terms: set[str] = set()
    for token in _TOKEN_RE.findall(source.lower()):
        if _CJK_RE.fullmatch(token):
            terms.update(_cjk_terms(token, for_query=for_query))
        else:
            terms.add(token)
    if for_query:
        terms = _expand_query_terms(terms)
        terms.difference_update(_QUERY_STOP_CHARS)
        for phrase in _QUERY_STOP_PHRASES:
            terms.discard(phrase)
    return terms


def _semantic_score(query: str, text: str) -> float:
    q_terms = _tokenize(query, for_query=True)
    t_terms = _tokenize(text)
    if not q_terms:
        return 0.0
    overlap = len(q_terms & t_terms)
    return overlap / len(q_terms)


def _recency_score(effective_at: str) -> float:
    """Higher score for more recently recorded memories (no explicit time intent)."""
    if not effective_at:
        return 0.5
    try:
        created = datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
        now = datetime.now(created.tzinfo) if created.tzinfo else datetime.now()
        days = max(0.0, (now - created).total_seconds() / 86400.0)
        half_life = max(config.RECENCY_HALFLIFE_DAYS, 1.0)
        return math.pow(0.5, days / half_life)
    except Exception:
        return 0.5


def _temporal_score(effective_at: str, anchor_date: str | None) -> float:
    if not effective_at:
        return 0.5
    if not anchor_date:
        return _recency_score(effective_at)
    try:
        created = datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
        anchor = datetime.fromisoformat(anchor_date)
        if created.tzinfo and anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=created.tzinfo)
        days = abs((created - anchor).total_seconds()) / 86400.0
        half_life = config.TIME_DECAY_HALFLIFE_DAYS
        return math.pow(0.5, days / half_life)
    except Exception:
        return 0.5


def _compactness_bonus(text: str) -> float:
    """Prefer short personal facts over long diary/noise chunks."""
    length = len(text.strip())
    if length <= 24:
        return 0.18
    if length <= 60:
        return 0.08
    return 0.0


def _blend_score(sem: float, temp: float, text: str) -> float:
    blended = config.SEMANTIC_WEIGHT * sem + (1 - config.SEMANTIC_WEIGHT) * temp
    return min(1.0, blended + _compactness_bonus(text))


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
        text = str(hit.get("text") or "")
        searchable = " ".join(
            part for part in (
                text,
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
            blended = _blend_score(max(float(sem), base_score * 0.5), temp, text)
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


def scoped_recall(
    query: str,
    *,
    max_results: int = 10,
    facts: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Recall memories with semantic + temporal scoring."""
    profile = load_core_profile()
    intent = parse_temporal_intent(query, profile)
    store = get_memory_store()
    candidate_facts = facts if facts is not None else store.all_facts()

    scored: list[tuple[float, dict[str, Any]]] = []
    for fact in candidate_facts:
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
        blended = _blend_score(sem, temp, fact.text)
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
