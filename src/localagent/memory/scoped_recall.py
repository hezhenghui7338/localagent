"""Scoped memory recall with temporal weighting."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from localagent import config
from localagent.knowledge.bm25_store import tokenize as bm25_tokenize
from localagent.memory.core_profile import load_core_profile
from localagent.memory.store import get_memory_store
from localagent.memory.temporal import memory_effective_time
from localagent.memory.temporal_intent import TemporalIntent, parse_temporal_intent

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
_EN_QUERY_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "where",
        "what", "who", "whom", "which", "why", "how", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "must", "shall", "can", "to",
        "of", "in", "on", "at", "by", "for", "with", "about", "as", "into", "like",
        "through", "after", "before", "between", "from", "up", "down", "out", "off",
        "over", "under", "again", "further", "once", "here", "there", "all", "each",
        "few", "more", "most", "other", "some", "such", "no", "nor", "not", "only",
        "own", "same", "so", "than", "too", "very", "just", "also", "now", "i", "me",
        "my", "we", "our", "you", "your", "he", "she", "it", "they", "them", "their",
        "this", "that", "these", "those", "am",
    }
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
        terms.difference_update(_EN_QUERY_STOPWORDS)
        for phrase in _QUERY_STOP_PHRASES:
            terms.discard(phrase)
    return terms


def _lexical_overlap_score(query: str, text: str) -> float:
    """Token Jaccard-style overlap (lexical), not embedding similarity."""
    q_terms = _tokenize(query, for_query=True)
    t_terms = _tokenize(text)
    if not q_terms:
        return 0.0
    overlap = len(q_terms & t_terms)
    return overlap / len(q_terms)


# Back-compat alias — prefer _lexical_overlap_score in new code.
_semantic_score = _lexical_overlap_score


def _fact_searchable_text(fact: Any) -> str:
    meta = getattr(fact, "metadata", None) or {}
    entities = meta.get("entities") or []
    entity_text = " ".join(str(e) for e in entities) if isinstance(entities, list) else ""
    return " ".join(
        part
        for part in (
            getattr(fact, "text", "") or "",
            str(meta.get("title") or ""),
            str(meta.get("summary") or ""),
            " ".join(meta.get("tags") or []),
            entity_text,
            getattr(fact, "section_heading", "") or "",
            str(meta.get("speaker") or ""),
            str(meta.get("dia_id") or ""),
            str(meta.get("date_time") or ""),
        )
        if part
    )


_PORTER = None


def _stem_token(token: str) -> str:
    if len(token) < 4 or _CJK_RE.search(token):
        return token
    global _PORTER
    try:
        if _PORTER is None:
            from nltk.stem import PorterStemmer

            _PORTER = PorterStemmer()
        return _PORTER.stem(token)
    except Exception:
        for suffix in ("ing", "ers", "ies", "ied", "ed", "es", "s"):
            if token.endswith(suffix) and len(token) - len(suffix) >= 3:
                return token[: -len(suffix)]
        return token


def _memory_bm25_tokenize(text: str) -> list[str]:
    """BM25 tokens for memory recall; English terms are stemmed for better matching."""
    return [_stem_token(token) for token in bm25_tokenize(text)]


def _bm25_scores(query: str, corpus_texts: list[str]) -> list[float]:
    """Return raw BM25 scores aligned with corpus_texts."""
    if not corpus_texts:
        return []
    try:
        from rank_bm25 import BM25Okapi
    except Exception:
        return [0.0] * len(corpus_texts)

    tokenized = [_memory_bm25_tokenize(text) for text in corpus_texts]
    if not any(tokenized):
        return [0.0] * len(corpus_texts)
    bm25 = BM25Okapi(tokenized)
    scores = bm25.get_scores(_memory_bm25_tokenize(query))
    return [float(score) for score in scores]


def _normalize_scores(scores: list[float]) -> list[float]:
    if not scores:
        return []
    peak = max(scores)
    if peak <= 0:
        return [0.0] * len(scores)
    return [max(0.0, score / peak) for score in scores]


def _combine_lexical_scores(jaccard: float, bm25_norm: float) -> float:
    """Prefer strong BM25 matches while keeping Jaccard signal for short Chinese facts."""
    if bm25_norm <= 0 and jaccard <= 0:
        return 0.0
    return max(jaccard, bm25_norm) * 0.65 + min(jaccard, bm25_norm) * 0.35


def _parse_day(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except Exception:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except Exception:
        return None


def _recency_score(effective_at: str) -> float:
    """Higher score for more recently recorded memories (no explicit time intent)."""
    if not effective_at:
        return 0.5
    created = _parse_day(effective_at)
    if created is None:
        return 0.5
    now = datetime.now()
    days = max(0.0, (now - created).total_seconds() / 86400.0)
    half_life = max(config.RECENCY_HALFLIFE_DAYS, 1.0)
    return math.pow(0.5, days / half_life)


def _anchor_decay_score(effective_at: str, anchor_date: str | None) -> float:
    if not effective_at:
        return 0.5
    if not anchor_date:
        return _recency_score(effective_at)
    created = _parse_day(effective_at)
    anchor = _parse_day(anchor_date)
    if created is None or anchor is None:
        return 0.5
    days = abs((created - anchor).total_seconds()) / 86400.0
    half_life = max(config.TIME_DECAY_HALFLIFE_DAYS, 1.0)
    return math.pow(0.5, days / half_life)


def _temporal_score(effective_at: str, anchor_date: str | None) -> float:
    """Backward-compatible helper used by query.py and older call sites."""
    return _anchor_decay_score(effective_at, anchor_date)


def _scope_alignment_score(effective_at: str, intent: TemporalIntent) -> float:
    """Soft in/near/out window score; never hard-filters undated memories."""
    if not intent.has_time_scope:
        return 0.5
    created = _parse_day(effective_at)
    start = _parse_day(intent.scope_start or "")
    end = _parse_day(intent.scope_end or "")
    if created is None or start is None or end is None:
        return 0.35
    if start > end:
        start, end = end, start
    if start <= created <= end:
        return 1.0
    near = max(float(config.MEMORY_SCOPE_NEAR_DAYS), 1.0)
    if created < start:
        gap = (start - created).total_seconds() / 86400.0
    else:
        gap = (created - end).total_seconds() / 86400.0
    if gap <= near:
        return 0.5
    return 0.15


def _intent_temporal_score(
    *,
    effective_at: str,
    storage_at: str,
    intent: TemporalIntent,
) -> float:
    """Combine anchor decay + scope soft boost according to intent kind."""
    kind = intent.intent_kind
    if kind == "as_of_now":
        # Prefer recently recorded/current states over ancient occurred_at facts.
        recency = _recency_score(storage_at or effective_at)
        scope = _scope_alignment_score(effective_at, intent)
        return 0.7 * recency + 0.3 * scope
    if kind == "range":
        decay = _anchor_decay_score(effective_at, intent.anchor_date)
        scope = _scope_alignment_score(effective_at, intent)
        return 0.45 * decay + 0.55 * scope
    if kind in ("when_event", "duration"):
        # Question usually has no calendar; keep a light recency prior only.
        return 0.5
    if intent.anchor_date:
        return _anchor_decay_score(effective_at, intent.anchor_date)
    return _recency_score(storage_at or effective_at)


def _compactness_bonus(text: str) -> float:
    """Prefer short personal facts over long diary/noise chunks."""
    length = len(text.strip())
    if length <= 24:
        return 0.18
    if length <= 60:
        return 0.08
    return 0.0


def _storage_time(*, metadata: dict[str, Any] | None, created_at: str = "") -> str:
    """Prefer write/index time for recency when the query has no temporal anchor."""
    meta = metadata or {}
    for key in ("recorded_at", "indexed_at", "created_at"):
        value = str(meta.get(key) or "").strip()
        if value:
            return value
    return (created_at or "").strip()


def _semantic_weight_for_intent(intent: TemporalIntent) -> float:
    if intent.raises_temporal_weight:
        # Raise temporal share from ~25% to ~40% for range / as_of_now.
        return min(float(config.SEMANTIC_WEIGHT), 0.60)
    return float(config.SEMANTIC_WEIGHT)


def _blend_score(
    sem: float,
    temp: float,
    text: str,
    intent: TemporalIntent | None = None,
) -> float:
    weight = _semantic_weight_for_intent(intent) if intent is not None else float(config.SEMANTIC_WEIGHT)
    blended = weight * sem + (1 - weight) * temp
    return min(1.0, blended + _compactness_bonus(text))


def _hybrid_weights(intent: TemporalIntent) -> tuple[float, float, float, float, float]:
    """RRF / base / jaccard / temporal / entity weights for Mem0 finalize_hybrid_rank."""
    entity_w = 0.15 if config.MEMORY_RECALL_ENTITY_BOOST else 0.0
    if intent.raises_temporal_weight:
        return (0.48, 0.12, 0.08, 0.17, entity_w)
    if intent.prefers_event_neighbors:
        # WHEN/duration: keep RRF dominant; time barely helps without an anchor.
        return (0.60, 0.12, 0.10, 0.03, entity_w)
    return (0.60, 0.12, 0.08, 0.05, entity_w)

_EN_RECALL_STOPWORDS = _EN_QUERY_STOPWORDS | frozenset(
    {
        "caroline",
        "melanie",
        "mel",
        "when",
        "what",
        "where",
        "who",
        "whom",
        "which",
        "why",
        "how",
        "whose",
    }
)


def expand_recall_queries(query: str) -> list[str]:
    """Build lexical variants that recover keyword-heavy dialog turns."""
    raw = " ".join((query or "").split())
    if not raw:
        return []
    variants = [raw]
    # Drop possessives: "Caroline's identity" → "Caroline identity"
    variants.append(re.sub(r"'s\b", "", raw, flags=re.IGNORECASE))
    tokens = _TOKEN_RE.findall(raw.lower())
    content = [
        tok
        for tok in tokens
        if tok not in _EN_RECALL_STOPWORDS
        and tok not in _QUERY_STOP_CHARS
        and tok not in _QUERY_STOP_PHRASES
        and len(tok) > 2
    ]
    if content:
        variants.append(" ".join(content))
    # Keep multi-word quoted phrases as dedicated queries.
    for phrase in re.findall(r'"([^"]{2,80})"|“([^”]{2,80})”', raw):
        text = (phrase[0] or phrase[1]).strip()
        if text:
            variants.append(text)

    out: list[str] = []
    seen: set[str] = set()
    for item in variants:
        cleaned = " ".join(item.split())
        key = cleaned.lower()
        if cleaned and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


def rrf_fuse_hits(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    k: int | None = None,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion over multiple recall lists (by memory id)."""
    rrf_k = config.MEMORY_RECALL_RRF_K if k is None else k
    scores: dict[str, float] = {}
    best: dict[str, dict[str, Any]] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits):
            hit_id = str(hit.get("id") or "")
            if not hit_id:
                # Fall back to text fingerprint so anonymous hits still fuse.
                hit_id = f"text:{hash(str(hit.get('text') or ''))}"
            scores[hit_id] = scores.get(hit_id, 0.0) + 1.0 / (rrf_k + rank + 1)
            prev = best.get(hit_id)
            if prev is None or float(hit.get("score") or 0.0) >= float(prev.get("score") or 0.0):
                best[hit_id] = hit
    fused: list[dict[str, Any]] = []
    for hit_id, rrf_score in sorted(scores.items(), key=lambda item: item[1], reverse=True):
        hit = dict(best[hit_id])
        hit["rrf_score"] = rrf_score
        # Preserve a usable base score for downstream temporal blending.
        hit["score"] = max(float(hit.get("score") or 0.0), rrf_score)
        fused.append(hit)
    return fused


def expand_dialog_neighbors(
    hits: list[dict[str, Any]],
    facts: list[Any],
    *,
    window: int | None = None,
) -> list[dict[str, Any]]:
    """Pull ±N dialog turns from the same session into the candidate pool."""
    neighbor_window = config.MEMORY_RECALL_NEIGHBOR_WINDOW if window is None else window
    if neighbor_window <= 0 or not hits or not facts:
        return hits

    by_dia: dict[str, Any] = {}
    for fact in facts:
        dia = str((getattr(fact, "metadata", None) or {}).get("dia_id") or "")
        if dia:
            by_dia[dia] = fact

    dia_re = re.compile(r"^D(\d+):(\d+)$", re.IGNORECASE)
    existing_ids = {str(hit.get("id") or "") for hit in hits}
    existing_dias = {
        str((hit.get("metadata") or {}).get("dia_id") or "")
        for hit in hits
        if (hit.get("metadata") or {}).get("dia_id")
    }
    extras: list[dict[str, Any]] = []
    for hit in hits:
        dia = str((hit.get("metadata") or {}).get("dia_id") or "")
        match = dia_re.match(dia)
        if not match:
            continue
        session_num = int(match.group(1))
        turn_num = int(match.group(2))
        base_score = float(hit.get("score") or 0.0) * 0.85
        for delta in range(-neighbor_window, neighbor_window + 1):
            if delta == 0:
                continue
            neighbor_dia = f"D{session_num}:{turn_num + delta}"
            if neighbor_dia in existing_dias:
                continue
            fact = by_dia.get(neighbor_dia)
            if fact is None or str(fact.id) in existing_ids:
                continue
            existing_dias.add(neighbor_dia)
            existing_ids.add(str(fact.id))
            extras.append(
                {
                    "id": fact.id,
                    "text": fact.text,
                    "score": base_score,
                    "source_file": fact.source_file,
                    "section_heading": fact.section_heading,
                    "created_at": memory_effective_time(
                        metadata=fact.metadata,
                        created_at=fact.created_at,
                    ),
                    "metadata": fact.metadata,
                    "source": "neighbor",
                }
            )
    return hits + extras


def finalize_hybrid_rank(
    query: str,
    hits: list[dict[str, Any]],
    *,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Polish hybrid candidates while keeping RRF as the dominant signal.

    Full BM25 re-ranking over a neighbor-expanded pool previously drowned
    vector/RRF winners under common dialog keywords (speaker names, etc.).
    Time weight rises for range / as_of_now; WHEN/duration stays RRF-led.
    """
    if not hits:
        return []
    from localagent.memory.entities import entity_overlap_score, extract_entities

    profile = load_core_profile()
    intent = parse_temporal_intent(query, profile)
    w_rrf, w_base, w_jac, w_temp, w_ent = _hybrid_weights(intent)
    query_entities = extract_entities(query) if config.MEMORY_RECALL_ENTITY_BOOST else []

    rrf_values = [float(hit.get("rrf_score") or 0.0) for hit in hits]
    rrf_norm = _normalize_scores(rrf_values)
    base_values = [float(hit.get("score") or 0.0) for hit in hits]
    base_norm = _normalize_scores(base_values)

    scored: list[tuple[float, dict[str, Any]]] = []
    for index, hit in enumerate(hits):
        searchable = _hit_searchable_text(hit)
        jaccard = _lexical_overlap_score(query, searchable) if query.strip() else 0.0
        effective_at = memory_effective_time(
            metadata=hit.get("metadata"),
            created_at=str(hit.get("created_at") or ""),
        )
        storage_at = _storage_time(
            metadata=hit.get("metadata"),
            created_at=str(hit.get("created_at") or ""),
        )
        temp = _intent_temporal_score(
            effective_at=effective_at,
            storage_at=storage_at,
            intent=intent,
        )
        meta = hit.get("metadata") or {}
        hit_entities = meta.get("entities") or []
        if not isinstance(hit_entities, list):
            hit_entities = []
        ent = (
            entity_overlap_score(query_entities, hit_entities, searchable)
            if query_entities
            else 0.0
        )
        blended = (
            w_rrf * (rrf_norm[index] if index < len(rrf_norm) else 0.0)
            + w_base * (base_norm[index] if index < len(base_norm) else 0.0)
            + w_jac * jaccard
            + w_temp * temp
            + w_ent * ent
        )
        if str(hit.get("source") or "") == "neighbor":
            blended *= 0.92
        enriched = dict(hit)
        enriched["score"] = blended
        enriched["semantic_score"] = jaccard if query.strip() else None
        enriched["lexical_score"] = jaccard if query.strip() else None
        enriched["temporal_score"] = temp
        enriched["entity_score"] = ent
        enriched["anchor"] = intent.to_dict()
        scored.append((blended, enriched))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in scored[:max_results]]


def rerank_hits_temporally(
    query: str,
    hits: list[dict[str, Any]],
    *,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Re-rank engine recall hits with lexical overlap + temporal intent."""
    if not hits:
        return []
    profile = load_core_profile()
    intent = parse_temporal_intent(query, profile)

    scored: list[tuple[float, dict[str, Any]]] = []
    for hit in hits:
        text = str(hit.get("text") or "")
        searchable = _hit_searchable_text(hit)
        sem = _semantic_score(query, searchable) if query.strip() else float(hit.get("score") or 1.0)
        effective_at = memory_effective_time(
            metadata=hit.get("metadata"),
            created_at=str(hit.get("created_at") or ""),
        )
        storage_at = _storage_time(
            metadata=hit.get("metadata"),
            created_at=str(hit.get("created_at") or ""),
        )
        temp = _intent_temporal_score(
            effective_at=effective_at,
            storage_at=storage_at,
            intent=intent,
        )
        base_score = float(hit.get("score") or 0.0)
        if query.strip():
            blended = _blend_score(max(float(sem), base_score * 0.5), temp, text, intent)
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


def _hit_searchable_text(hit: dict[str, Any]) -> str:
    meta = hit.get("metadata") or {}
    entities = meta.get("entities") or []
    entity_text = " ".join(str(e) for e in entities) if isinstance(entities, list) else ""
    return " ".join(
        part
        for part in (
            str(hit.get("text") or ""),
            str(meta.get("title") or ""),
            str(meta.get("summary") or ""),
            " ".join(meta.get("tags") or []),
            entity_text,
            str(hit.get("section_heading") or ""),
            str(meta.get("speaker") or ""),
            str(meta.get("dia_id") or ""),
            str(meta.get("date_time") or ""),
        )
        if part
    )


def scoped_recall(
    query: str,
    *,
    max_results: int = 10,
    facts: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Recall memories with BM25 + lexical overlap and temporal scoring.

    Lexical signal ranks candidates but is never a hard discard gate —
    embedding backends should supply the primary semantic channel.
    """
    profile = load_core_profile()
    intent = parse_temporal_intent(query, profile)
    store = get_memory_store()
    candidate_facts = facts if facts is not None else store.all_facts()
    if not candidate_facts:
        return []

    corpus = [_fact_searchable_text(fact) for fact in candidate_facts]
    bm25_norm = _normalize_scores(_bm25_scores(query, corpus))

    scored: list[tuple[float, dict[str, Any]]] = []
    for index, fact in enumerate(candidate_facts):
        searchable = corpus[index]
        jaccard = _lexical_overlap_score(query, searchable)
        lexical = _combine_lexical_scores(jaccard, bm25_norm[index] if index < len(bm25_norm) else 0.0)
        effective_at = memory_effective_time(metadata=fact.metadata, created_at=fact.created_at)
        storage_at = _storage_time(metadata=fact.metadata, created_at=fact.created_at)
        temp = _intent_temporal_score(
            effective_at=effective_at,
            storage_at=storage_at,
            intent=intent,
        )
        # When lexical is zero, temporal/recency still ranks (no hard drop).
        blended = _blend_score(lexical, temp, fact.text, intent)
        scored.append((
            blended,
            {
                "id": fact.id,
                "text": fact.text,
                "score": blended,
                "semantic_score": lexical,
                "lexical_score": lexical,
                "jaccard_score": jaccard,
                "bm25_score": bm25_norm[index] if index < len(bm25_norm) else 0.0,
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


def scoped_recall_multi(
    queries: list[str],
    *,
    max_results: int = 10,
    facts: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Run lexical recall for several query variants and keep the best score per fact."""
    cleaned = [" ".join(q.split()) for q in queries if q and q.strip()]
    if not cleaned:
        return []
    if len(cleaned) == 1:
        return scoped_recall(cleaned[0], max_results=max_results, facts=facts)

    best: dict[str, dict[str, Any]] = {}
    for query in cleaned:
        for hit in scoped_recall(query, max_results=max(max_results * 2, 20), facts=facts):
            hit_id = str(hit.get("id") or "")
            if not hit_id:
                continue
            prev = best.get(hit_id)
            if prev is None or float(hit.get("score") or 0.0) > float(prev.get("score") or 0.0):
                best[hit_id] = hit
    ranked = sorted(best.values(), key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return ranked[:max_results]
