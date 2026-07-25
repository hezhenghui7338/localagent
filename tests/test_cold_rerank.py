"""Unit tests for Cold RAG rerank pipeline."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from localagent.knowledge.bm25_store import BM25Store
from localagent.knowledge.hybrid import HybridRetriever, reciprocal_rank_fusion
from localagent.knowledge.rerank import rerank_cold_hits


def test_rerank_off_preserves_rrf_order(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("localagent.config.COLD_RERANK", False)
    bm25 = BM25Store(tmp_path / "bm25.pkl")
    bm25.build(
        ["a", "b"],
        ["alpha keyword content", "beta keyword content"],
        [{"source_file": "a.md"}, {"source_file": "b.md"}],
    )
    chroma = MagicMock()
    chroma.query.return_value = [
        {
            "chunk_id": "a",
            "text": "alpha keyword content",
            "metadata": {"source_file": "a.md"},
            "score_dense": 0.9,
        },
        {
            "chunk_id": "b",
            "text": "beta keyword content",
            "metadata": {"source_file": "b.md"},
            "score_dense": 0.5,
        },
    ]
    retriever = HybridRetriever(chroma, bm25)
    hits = retriever.retrieve("alpha", top_k=2)
    assert [h["chunk_id"] for h in hits] == ["a", "b"]


def test_rerank_on_reorders_via_mock(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("localagent.config.COLD_RERANK", True)
    monkeypatch.setattr("localagent.config.COLD_RERANK_CANDIDATES", 10)
    monkeypatch.setattr("localagent.config.COLD_FETCH_MULTIPLIER", 2)

    def fake_rerank(query, hits, *, max_results=None):
        reversed_hits = list(reversed(hits))
        for idx, hit in enumerate(reversed_hits):
            enriched = dict(hit)
            enriched["rerank_score"] = float(idx + 1)
            reversed_hits[idx] = enriched
        limit = max_results if max_results is not None else len(reversed_hits)
        return reversed_hits[:limit]

    monkeypatch.setattr(
        "localagent.knowledge.rerank.rerank_cold_hits",
        fake_rerank,
    )

    bm25 = BM25Store(tmp_path / "bm25.pkl")
    bm25.build(
        ["a", "b"],
        ["alpha keyword content", "beta keyword content"],
        [{"source_file": "a.md"}, {"source_file": "b.md"}],
    )
    chroma = MagicMock()
    chroma.query.return_value = [
        {
            "chunk_id": "a",
            "text": "alpha keyword content",
            "metadata": {"source_file": "a.md"},
            "score_dense": 0.9,
        },
        {
            "chunk_id": "b",
            "text": "beta keyword content",
            "metadata": {"source_file": "b.md"},
            "score_dense": 0.5,
        },
    ]
    retriever = HybridRetriever(chroma, bm25)
    hits = retriever.retrieve("alpha", top_k=2)
    assert [h["chunk_id"] for h in hits] == ["b", "a"]
    assert hits[0].get("rerank_score") == 1.0


def test_rerank_cold_hits_off_returns_input(monkeypatch):
    monkeypatch.setattr("localagent.config.COLD_RERANK", False)
    hits = [
        {"chunk_id": "a", "text": "aaa", "score_rrf": 0.9},
        {"chunk_id": "b", "text": "bbb", "score_rrf": 0.5},
    ]
    out = rerank_cold_hits("query", hits, max_results=2)
    assert [h["chunk_id"] for h in out] == ["a", "b"]


def test_reciprocal_rank_fusion_respects_rrf_k():
    dense = [{"chunk_id": "x", "text": "x", "score_dense": 1.0}]
    sparse = [{"chunk_id": "y", "text": "y", "score_sparse": 1.0}]
    fused = reciprocal_rank_fusion([dense, sparse], rrf_k=10, top_k=2)
    assert len(fused) == 2
    assert fused[0]["score_rrf"] == pytest.approx(1 / 11)
