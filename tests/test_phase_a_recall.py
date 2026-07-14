"""Unit tests for Phase A recall helpers: decompose, entities, rerank wiring."""

from __future__ import annotations

from localagent.memory.decompose import decompose_recall_query
from localagent.memory.entities import entity_overlap_score, extract_entities
from localagent.memory.enrich import enrich_heuristic
from localagent.memory.rerank import rerank_memory_hits
from localagent.memory.scoped_recall import finalize_hybrid_rank


def test_decompose_keeps_simple_query(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_RECALL_DECOMPOSE", True)
    q = "Where does Caroline live?"
    assert decompose_recall_query(q) == [q]


def test_decompose_splits_both_and(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_RECALL_DECOMPOSE", True)
    monkeypatch.setattr("localagent.config.MEMORY_RECALL_DECOMPOSE_MAX", 3)
    q = "What did both Caroline and Melanie say about painting?"
    parts = decompose_recall_query(q)
    assert parts[0] == q
    assert len(parts) >= 2
    joined = " ".join(parts).lower()
    assert "caroline" in joined
    assert "melanie" in joined or "painting" in joined


def test_decompose_disabled_returns_original(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_RECALL_DECOMPOSE", False)
    q = "What did both Caroline and Melanie say about painting?"
    assert decompose_recall_query(q) == [q]


def test_extract_entities_finds_quoted_and_names():
    ents = extract_entities('Caroline visited "Blue Harbor" gallery in Seattle')
    lower = {e.lower() for e in ents}
    assert "caroline" in lower or any("caroline" in e.lower() for e in ents)
    assert any("blue harbor" in e.lower() for e in ents) or "seattle" in lower


def test_entity_overlap_score():
    score = entity_overlap_score(
        ["Seattle", "painting"],
        ["Seattle"],
        "Caroline loves painting in Seattle",
    )
    assert score >= 0.5


def test_enrich_heuristic_includes_entities():
    enriched = enrich_heuristic("用户居住在深圳南山", heading="住址")
    assert enriched.entities
    assert "entities" in enriched.to_metadata()


def test_finalize_hybrid_rank_entity_boost(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_RECALL_ENTITY_BOOST", True)
    hits = [
        {
            "id": "noise",
            "text": "Caroline went to the market yesterday",
            "score": 0.55,
            "rrf_score": 0.55,
            "metadata": {"entities": ["Caroline", "market"]},
            "created_at": "2023-01-01T00:00:00",
        },
        {
            "id": "target",
            "text": "Caroline painted landscapes in Seattle",
            "score": 0.50,
            "rrf_score": 0.50,
            "metadata": {"entities": ["Caroline", "Seattle", "painting"]},
            "created_at": "2023-01-01T00:00:00",
        },
    ]
    ranked = finalize_hybrid_rank(
        "Where did Caroline paint in Seattle?",
        hits,
        max_results=2,
    )
    assert ranked
    assert ranked[0]["id"] == "target"
    assert float(ranked[0].get("entity_score") or 0.0) > float(
        ranked[1].get("entity_score") or 0.0
    )


def test_rerank_off_preserves_order(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_RERANK", False)
    hits = [
        {"id": "a", "text": "aaa", "score": 1.0},
        {"id": "b", "text": "bbb", "score": 0.5},
    ]
    out = rerank_memory_hits("query", hits, max_results=2)
    assert [h["id"] for h in out] == ["a", "b"]
