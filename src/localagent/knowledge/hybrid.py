"""Hybrid retrieval: Chroma dense + BM25 sparse + RRF."""

from __future__ import annotations

import re
from typing import Any

from localagent.knowledge.bm25_store import BM25Store
from localagent.knowledge.chroma_store import ChromaStore
from localagent.knowledge.time_filter import meta_in_range, parse_range_bounds

_CONVERSATION_ORIGINS = frozenset({"chat", "chatgpt", "locomo"})
_USER_TURN_HEADER = re.compile(
    r"##\s*Turn\s+(\d+)\s*·\s*user\b",
    re.IGNORECASE,
)


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

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 10,
        since: str | None = None,
        until: str | None = None,
        conversation_only: bool = False,
    ) -> list[dict[str, Any]]:
        since_dt, until_dt = parse_range_bounds(since, until)
        origins = _CONVERSATION_ORIGINS if conversation_only else None
        # Over-fetch dense hits then hard-filter so in-window docs are not crowded out.
        fetch_k = top_k * 5 if (since_dt or until_dt or origins) else top_k
        dense = self.chroma.query(query, top_k=fetch_k)
        if since_dt or until_dt or origins is not None:
            dense = [
                hit
                for hit in dense
                if (origins is None or str((hit.get("metadata") or {}).get("origin") or "") in origins)
                and meta_in_range(hit.get("metadata"), since=since_dt, until=until_dt)
            ]
        sparse = self.bm25.query(
            query,
            fetch_k,
            since=since_dt,
            until=until_dt,
            origins=origins,
        )
        return reciprocal_rank_fusion([dense, sparse], top_k=top_k)

    def list_conversations_in_range(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """Enumerate Cold conversation chunks in a recorded_at window."""
        since_dt, until_dt = parse_range_bounds(since, until)
        return self.bm25.list_in_range(
            since=since_dt,
            until=until_dt,
            origins=_CONVERSATION_ORIGINS,
            prefer_summary=True,
            limit=limit,
        )

    def list_user_questions_in_range(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        """List user-turn questions from Cold body chunks (newest sessions first)."""
        from localagent.knowledge.time_filter import chunk_recorded_at

        since_dt, until_dt = parse_range_bounds(since, until)
        indices = self.bm25._candidate_indices(
            since=since_dt,
            until=until_dt,
            origins=_CONVERSATION_ORIGINS,
        )
        rows: list[tuple[str, int, dict[str, Any]]] = []
        for i in indices:
            meta = self.bm25.metas[i] or {}
            if str(meta.get("chunk_kind") or "") == "summary":
                continue
            text = (self.bm25.texts_raw[i] or "").strip()
            match = _USER_TURN_HEADER.search(text)
            if not match:
                continue
            # Body after the Turn header line.
            after = text[match.end() :].lstrip("\n")
            question = " ".join(after.split()).strip()
            if not question:
                continue
            turn = int(match.group(1))
            rows.append(
                (
                    chunk_recorded_at(meta),
                    turn,
                    {
                        "chunk_id": self.bm25.chunk_ids[i],
                        "text": question,
                        "metadata": meta,
                        "score_sparse": 1.0,
                        "score_rrf": 1.0,
                    },
                )
            )
        # Newest conversation first; within a session keep turn order.
        rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [row for _, _, row in rows[:limit]]


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
