"""Session-scoped Cold indexing for document / news deep chat."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from localagent.ingest.chunker import chunk_for_rag
from localagent.knowledge.indexer import get_knowledge_indexer

logger = logging.getLogger(__name__)

ORIGIN_DOC_SESSION = "doc_session"


def news_source_key(article_id: str) -> str:
    aid = (article_id or "").strip() or "unknown"
    return f"news:{aid}"


def summarize_source_key(path: str | Path) -> str:
    resolved = str(Path(path).expanduser().resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    name = Path(resolved).name
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:40]
    return f"sum:{safe}:{digest}"


def index_document_session(
    source_key: str,
    text: str,
    *,
    title: str = "",
) -> int:
    """Chunk + index text under ``source_key`` with origin=doc_session.

    Replaces any previous chunks for the same key. Does not symlink into kb/.
    """
    key = (source_key or "").strip()
    body = (text or "").strip()
    if not key:
        return 0
    if not body:
        get_knowledge_indexer().remove_by_source_file(key)
        return 0
    chunks = chunk_for_rag(body, filename=key)
    for chunk in chunks:
        chunk.metadata = {
            **(chunk.metadata or {}),
            "origin": ORIGIN_DOC_SESSION,
            "title": (title or "").strip() or key,
            "chunk_kind": "body",
        }
    n = get_knowledge_indexer().index_chunks(filename=key, chunks=chunks)
    logger.info("doc session indexed source=%s chunks=%s", key, n)
    return n


def retrieve_document_chunks(
    query: str,
    *,
    source_key: str,
    top_k: int | None = None,
) -> list[dict]:
    """Hybrid retrieve restricted to one document session source_key."""
    from localagent import config
    from localagent.knowledge.hybrid import get_hybrid_retriever

    key = (source_key or "").strip()
    if not key:
        return []
    k = top_k if top_k is not None else config.DOC_SESSION_RETRIEVE_TOP_K
    return get_hybrid_retriever().retrieve(query, top_k=k, source_file=key)


def format_retrieval_block(hits: list[dict], *, source_key: str = "") -> str:
    if not hits:
        return "\n".join(
            [
                "[当前文档检索结果（无命中片段）]",
                f"source: {source_key}" if source_key else "",
                "未检索到相关原文片段；请基于速读卡如实说明依据不足，勿编造细节。",
            ]
        ).strip()
    lines = [
        "[当前文档检索结果（已预加载，请优先据此回答；引用时用 〔§…|p.…〕）]",
    ]
    if source_key:
        lines.append(f"source: {source_key}")
    for i, hit in enumerate(hits, start=1):
        meta = hit.get("metadata") or {}
        heading = str(meta.get("heading") or "").strip()
        text = str(hit.get("text") or "").strip()
        score = hit.get("score_rrf")
        score_s = f"{float(score):.3f}" if score is not None else "?"
        label = heading or f"片段{i}"
        lines.append(f"### [{i}] {label} (rrf={score_s})")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip()
