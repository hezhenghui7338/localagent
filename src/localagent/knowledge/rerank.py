"""Cross-encoder reranking for Cold/Warm retrieval."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

HitTextFn = Callable[[dict[str, Any]], str]

_CE_USER_WARNED: set[str] = set()


@lru_cache(maxsize=2)
def load_cross_encoder(model_name: str):
    try:
        from sentence_transformers import CrossEncoder

        try:
            return CrossEncoder(model_name, local_files_only=True)
        except Exception:
            return CrossEncoder(model_name)
    except Exception as exc:
        logger.info("Cross-encoder unavailable (%s): %s", model_name, exc)
        return None


def cross_encoder_import_ok() -> bool:
    try:
        import sentence_transformers  # noqa: F401

        return True
    except Exception:
        return False


def normalize_backend(name: str) -> str:
    value = (name or "auto").strip().lower()
    if value in {"auto", "cross_encoder", "embed", "llm", "off"}:
        return value
    return "auto"


def cold_hit_text(hit: dict[str, Any]) -> str:
    meta = hit.get("metadata") or {}
    parts = [
        str(hit.get("text") or ""),
        str(meta.get("heading") or ""),
        str(meta.get("title") or ""),
        str(meta.get("source_file") or ""),
    ]
    return " ".join(p for p in parts if p).strip()


def memory_hit_text(hit: dict[str, Any]) -> str:
    meta = hit.get("metadata") or {}
    parts = [
        str(hit.get("text") or ""),
        str(meta.get("title") or ""),
        str(meta.get("summary") or ""),
        " ".join(str(t) for t in (meta.get("tags") or [])),
        " ".join(str(e) for e in (meta.get("entities") or [])),
    ]
    return " ".join(p for p in parts if p).strip()


def cross_encoder_rerank(
    query: str,
    hits: list[dict[str, Any]],
    *,
    model_name: str,
    hit_text_fn: HitTextFn,
) -> list[dict[str, Any]] | None:
    model = load_cross_encoder(model_name)
    if model is None:
        return None
    pairs = [(query, hit_text_fn(hit)[:1500] or " ") for hit in hits]
    try:
        scores = model.predict(pairs)
    except Exception as exc:
        logger.warning("Cross-encoder predict failed: %s", exc)
        return None
    scored: list[dict[str, Any]] = []
    for hit, score in zip(hits, scores):
        enriched = dict(hit)
        enriched["rerank_score"] = float(score)
        enriched["score"] = float(score)
        scored.append(enriched)
    scored.sort(key=lambda item: float(item.get("rerank_score") or 0.0), reverse=True)
    return scored


def _warn_cross_encoder_unavailable(*, backend: str, channel: str) -> None:
    msg = (
        f"CrossEncoder 精排不可用，已保持原序。"
        f"安装: pip install 'la-localagent[rerank]'"
    )
    logger.warning(
        "%s rerank backend=%s but CrossEncoder unavailable; keeping prior order. %s",
        channel,
        backend,
        "pip install 'la-localagent[rerank]'",
    )
    if channel in _CE_USER_WARNED:
        return
    _CE_USER_WARNED.add(channel)
    try:
        import sys

        if sys.stderr.isatty():
            print(f"[{channel}] {msg}", file=sys.stderr)
    except Exception:
        pass


def rerank_with_backend(
    query: str,
    hits: list[dict[str, Any]],
    *,
    enabled: bool,
    backend: str,
    model: str,
    candidates: int,
    max_results: int | None = None,
    hit_text_fn: HitTextFn,
    warn_channel: str = "rerank",
) -> list[dict[str, Any]]:
    """Rerank candidates; never raises — falls back to input order on failure."""
    if not hits:
        return []
    limit = max_results if max_results is not None else len(hits)
    if not enabled:
        return hits[:limit]

    normalized = normalize_backend(backend)
    if normalized == "off":
        return hits[:limit]

    pool = hits[: max(limit, candidates)]
    model_name = model or "cross-encoder/ms-marco-MiniLM-L-6-v2"

    if normalized in {"auto", "cross_encoder"}:
        ranked = cross_encoder_rerank(
            query,
            pool,
            model_name=model_name,
            hit_text_fn=hit_text_fn,
        )
        if ranked is not None:
            return ranked[:limit]
        _warn_cross_encoder_unavailable(backend=normalized, channel=warn_channel)
        return hits[:limit]

    return hits[:limit]


def rerank_cold_hits(
    query: str,
    hits: list[dict[str, Any]],
    *,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    from localagent import config

    return rerank_with_backend(
        query,
        hits,
        enabled=config.COLD_RERANK,
        backend=config.COLD_RERANK_BACKEND,
        model=config.COLD_RERANK_MODEL,
        candidates=config.COLD_RERANK_CANDIDATES,
        max_results=max_results,
        hit_text_fn=cold_hit_text,
        warn_channel="cold",
    )
