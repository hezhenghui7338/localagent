"""Candidate reranking for memory recall (cross-encoder / embed / LLM)."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

from localagent import config

logger = logging.getLogger(__name__)

_ID_LINE_RE = re.compile(r"^\s*(\d+)\s*[).:\-]\s*", re.MULTILINE)


@lru_cache(maxsize=2)
def _load_cross_encoder(model_name: str):
    try:
        from sentence_transformers import CrossEncoder

        return CrossEncoder(model_name)
    except Exception as exc:
        logger.info("Cross-encoder unavailable (%s): %s", model_name, exc)
        return None


def _normalize_backend(name: str) -> str:
    value = (name or "auto").strip().lower()
    if value in {"auto", "cross_encoder", "embed", "llm", "off"}:
        return value
    return "auto"


def _hit_text(hit: dict[str, Any]) -> str:
    meta = hit.get("metadata") or {}
    parts = [
        str(hit.get("text") or ""),
        str(meta.get("title") or ""),
        str(meta.get("summary") or ""),
        " ".join(str(t) for t in (meta.get("tags") or [])),
        " ".join(str(e) for e in (meta.get("entities") or [])),
    ]
    return " ".join(p for p in parts if p).strip()


def _cross_encoder_rerank(query: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    model_name = config.MEMORY_RERANK_MODEL or "cross-encoder/ms-marco-MiniLM-L-6-v2"
    model = _load_cross_encoder(model_name)
    if model is None:
        return None
    pairs = [(query, _hit_text(hit)[:1500] or " ") for hit in hits]
    try:
        scores = model.predict(pairs)
    except Exception as exc:
        logger.warning("Cross-encoder predict failed: %s", exc)
        return None
    scored = []
    for hit, score in zip(hits, scores):
        enriched = dict(hit)
        enriched["rerank_score"] = float(score)
        enriched["score"] = float(score)
        scored.append(enriched)
    scored.sort(key=lambda item: float(item.get("rerank_score") or 0.0), reverse=True)
    return scored


def _embed_rerank(query: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    try:
        from localagent.memory.embeddings import cosine_similarity, embed_texts
    except Exception as exc:
        logger.debug("embed rerank import failed: %s", exc)
        return None
    texts = [_hit_text(hit)[:1500] or " " for hit in hits]
    try:
        vectors = embed_texts([query, *texts])
    except Exception as exc:
        logger.debug("embed rerank failed: %s", exc)
        return None
    if len(vectors) != len(texts) + 1:
        return None
    q_vec = vectors[0]
    scored = []
    for hit, vec in zip(hits, vectors[1:]):
        sim = cosine_similarity(q_vec, vec)
        enriched = dict(hit)
        # Blend with prior score so RRF signal is not fully discarded.
        prior = float(hit.get("score") or 0.0)
        blended = 0.75 * sim + 0.25 * prior
        enriched["rerank_score"] = blended
        enriched["score"] = blended
        scored.append(enriched)
    scored.sort(key=lambda item: float(item.get("rerank_score") or 0.0), reverse=True)
    return scored


def _llm_rerank(query: str, hits: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    if len(hits) <= 1:
        return list(hits)
    try:
        from localagent.models.router import ChatMessage, get_model_router
    except Exception:
        return None

    lines = []
    for index, hit in enumerate(hits, start=1):
        snippet = _hit_text(hit).replace("\n", " ")
        if len(snippet) > 220:
            snippet = snippet[:219] + "…"
        lines.append(f"{index}. {snippet}")
    prompt = (
        "你是记忆检索重排器。根据用户问题，把下列候选记忆按相关性从高到低排序。\n"
        "只输出编号序列，用逗号分隔，例如: 3,1,5,2\n"
        "不要解释。\n\n"
        f"问题: {query}\n\n候选:\n" + "\n".join(lines)
    )
    try:
        reply = get_model_router().chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.0,
            usage_command="memory_rerank",
        )
    except Exception as exc:
        logger.debug("LLM rerank failed: %s", exc)
        return None
    order: list[int] = []
    for match in re.finditer(r"\d+", reply or ""):
        value = int(match.group(0))
        if 1 <= value <= len(hits) and value not in order:
            order.append(value)
    if len(order) < max(1, len(hits) // 2):
        return None
    ranked: list[dict[str, Any]] = []
    seen: set[int] = set()
    for value in order:
        idx = value - 1
        if idx in seen:
            continue
        seen.add(idx)
        enriched = dict(hits[idx])
        enriched["rerank_score"] = float(len(hits) - len(ranked))
        enriched["score"] = float(enriched["rerank_score"])
        ranked.append(enriched)
    for idx, hit in enumerate(hits):
        if idx not in seen:
            ranked.append(dict(hit))
    return ranked


def rerank_memory_hits(
    query: str,
    hits: list[dict[str, Any]],
    *,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    """Rerank candidates; never raises — falls back to input order on failure."""
    if not hits:
        return []
    limit = max_results if max_results is not None else len(hits)
    if not config.MEMORY_RERANK:
        return hits[:limit]

    backend = _normalize_backend(config.MEMORY_RERANK_BACKEND)
    if backend == "off":
        return hits[:limit]

    candidates = hits[: max(limit, config.MEMORY_RERANK_CANDIDATES)]
    ranked: list[dict[str, Any]] | None = None

    if backend in {"auto", "cross_encoder"}:
        ranked = _cross_encoder_rerank(query, candidates)
        if ranked is not None:
            return ranked[:limit]
        if backend == "cross_encoder":
            logger.debug("cross_encoder requested but unavailable; keeping prior order")
            return hits[:limit]
        # auto: do not fall through to embed/llm (too slow/noisy for default chat path)
        return hits[:limit]

    if backend == "embed":
        ranked = _embed_rerank(query, candidates)
        if ranked is not None:
            return ranked[:limit]
        return hits[:limit]

    if backend == "llm":
        ranked = _llm_rerank(query, candidates)
        if ranked is not None:
            return ranked[:limit]

    return hits[:limit]
