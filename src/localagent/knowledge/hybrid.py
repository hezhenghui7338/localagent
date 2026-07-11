"""Hybrid retrieval: Chroma dense + BM25 sparse + RRF."""

from __future__ import annotations

from typing import Any

from localagent.knowledge.bm25_store import BM25Store
from localagent.knowledge.chroma_store import ChromaStore


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    rrf_k: int = 60,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for lst in ranked_lists:
        for rank, hit in enumerate(lst, start=1):
            cid = hit["chunk_id"]
            entry = by_id.setdefault(
                cid,
                {
                    "chunk_id": cid,
                    "text": hit.get("text", ""),
                    "metadata": hit.get("metadata", {}),
                    "score_rrf": 0.0,
                },
            )
            entry["score_rrf"] += 1.0 / (rrf_k + rank)
            for key, val in hit.items():
                if key.startswith("score_") and key not in entry:
                    entry[key] = val
    fused = sorted(by_id.values(), key=lambda x: x["score_rrf"], reverse=True)
    if top_k is not None:
        fused = fused[:top_k]
    return fused


class HybridRetriever:
    def __init__(self, chroma: ChromaStore, bm25: BM25Store) -> None:
        self.chroma = chroma
        self.bm25 = bm25

    def retrieve(self, query: str, *, top_k: int = 10) -> list[dict[str, Any]]:
        dense = self.chroma.query(query, top_k=top_k)
        sparse = self.bm25.query(query, top_k=top_k)
        return reciprocal_rank_fusion([dense, sparse], top_k=top_k)


_retriever: HybridRetriever | None = None


def get_hybrid_retriever() -> HybridRetriever:
    global _retriever
    if _retriever is None:
        from localagent import config

        _retriever = HybridRetriever(
            ChromaStore(config.CHROMA_DIR),
            BM25Store(config.BM25_PATH),
        )
    return _retriever


def reset_hybrid_retriever() -> None:
    global _retriever
    _retriever = None
