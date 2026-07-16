"""Knowledge indexing service."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from localagent import config
from localagent.ingest.chunker import TextChunk
from localagent.knowledge.bm25_store import BM25Store
from localagent.knowledge.chroma_store import ChromaStore
from localagent.knowledge.hybrid import reset_hybrid_retriever

logger = logging.getLogger(__name__)


def _sanitize_chroma_meta(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in meta.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = value
        elif isinstance(value, (int, float)):
            out[key] = value
        else:
            out[key] = str(value)
    return out


class KnowledgeIndexer:
    def __init__(self) -> None:
        self.chroma = ChromaStore(config.CHROMA_DIR)
        self.bm25 = BM25Store(config.BM25_PATH)

    def index_chunks(self, *, filename: str, chunks: list[TextChunk]) -> int:
        self.remove_by_source_file(filename)
        if not chunks:
            return 0
        ids = [c.chunk_id for c in chunks]
        texts = [c.text for c in chunks]
        metas = [
            _sanitize_chroma_meta(
                {
                    "source_file": filename,
                    "heading": c.heading,
                    "index": c.index,
                    **c.metadata,
                }
            )
            for c in chunks
        ]
        # Sparse index first so keyword recall still works if dense embed hangs/fails.
        self.bm25.merge_build(ids, texts, metas)
        try:
            self.chroma.upsert(chunk_ids=ids, texts=texts, metadatas=metas)
        except Exception as exc:
            logger.warning(
                "Chroma upsert failed for %s (%s); BM25 index kept",
                filename,
                exc,
            )
        reset_hybrid_retriever()
        return len(chunks)

    def remove_by_source_file(self, filename: str) -> int:
        before = self.bm25.count()
        self.chroma.delete_by_source_file(filename)
        self.bm25.remove_by_source_file(filename)
        reset_hybrid_retriever()
        return before - self.bm25.count()

    def remove_by_origin(self, origin: str) -> int:
        before = self.bm25.count()
        self.chroma.delete_by_origin(origin)
        self.bm25.remove_by_origin(origin)
        reset_hybrid_retriever()
        return before - self.bm25.count()

    def iter_metas(self) -> Iterator[dict[str, Any]]:
        yield from self.bm25.metas

    def clear(self) -> None:
        self.chroma.reset()
        self.bm25.reset()
        reset_hybrid_retriever()

    def count(self) -> int:
        return self.bm25.count()


_indexer: KnowledgeIndexer | None = None


def get_knowledge_indexer() -> KnowledgeIndexer:
    global _indexer
    if _indexer is None:
        _indexer = KnowledgeIndexer()
    return _indexer


def reset_knowledge_indexer() -> None:
    global _indexer
    _indexer = None
