"""Tests for local SQLite memory relation graph overlay."""

from __future__ import annotations

from localagent.memory.backends.json_backend import JsonMemoryBackend
from localagent.memory.graph import (
    expand_hits_by_graph,
    get_memory_graph,
    protect_seed_prefix,
    rebuild_memory_graph,
    sync_fact_to_graph,
)
from localagent.memory.graph.extract import extract_graph_payload
from localagent.memory.scoped_recall import finalize_hybrid_rank
from localagent.memory.store import MemoryFact, get_memory_store


def test_extract_slots_to_relations():
    fact = MemoryFact(
        id="f1",
        text="用户喜欢喝葡萄酒。",
        source_file="chat",
        section_heading="direct",
        created_at="2026-01-01T00:00:00",
        metadata={
            "slots": {
                "subject": "用户",
                "action": "喜欢",
                "object": "葡萄酒",
                "location": "",
            },
            "entities": ["用户", "葡萄酒"],
        },
    )
    payload = extract_graph_payload(fact)
    names = {name for name, _ in payload.entities}
    assert "用户" in names
    assert "葡萄酒" in names
    assert any(pred == "喜欢" and src == "用户" and dst == "葡萄酒" for src, pred, dst, _ in payload.relations)


def test_sync_and_hop_expands_related_fact(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_GRAPH", True)
    monkeypatch.setattr("localagent.config.NEO4J", False)
    monkeypatch.setattr("localagent.config.MEMORY_GRAPH_HOPS", 2)
    monkeypatch.setattr("localagent.config.MEMORY_GRAPH_MAX_EXTRAS", 8)

    store = get_memory_store()
    f1 = store.retain_from_section(
        filename="chat",
        heading="a",
        text="Caroline met Melanie at the gallery.",
        chunk_id="a1",
        extra_metadata={
            "entities": ["Caroline", "Melanie", "gallery"],
            "slots": {
                "subject": "Caroline",
                "action": "met",
                "object": "Melanie",
                "location": "gallery",
            },
            "dia_id": "D1:1",
        },
    )
    f2 = store.retain_from_section(
        filename="chat",
        heading="b",
        text="Melanie adopted a dog named Bailey.",
        chunk_id="b1",
        extra_metadata={
            "entities": ["Melanie", "Bailey", "dog"],
            "slots": {
                "subject": "Melanie",
                "action": "adopted",
                "object": "Bailey",
            },
            "dia_id": "D1:2",
        },
    )
    store.save()
    assert f1 is not None and f2 is not None

    sync_fact_to_graph(f1)
    sync_fact_to_graph(f2)
    rebuild_memory_graph()  # also links NEXT_TURN

    stats = get_memory_graph().stats()
    assert stats["entities"] >= 3
    assert stats["relations"] >= 1
    assert stats["facts"] >= 2

    seed = [
        {
            "id": f1.id,
            "text": f1.text,
            "score": 0.9,
            "rrf_score": 0.05,
            "source_file": f1.source_file,
            "section_heading": f1.section_heading,
            "created_at": f1.created_at,
            "metadata": f1.metadata,
            "source": "lexical",
        }
    ]
    expanded = expand_hits_by_graph(
        "What did Melanie adopt?",
        seed,
        facts=store.all_facts(),
    )
    ids = {str(hit.get("id")) for hit in expanded}
    assert f2.id in ids
    assert any(hit.get("source") == "graph" for hit in expanded)

    ranked = finalize_hybrid_rank("What did Melanie adopt?", expanded, max_results=5)
    assert ranked
    assert any("Bailey" in str(hit.get("text") or "") for hit in ranked)


def test_json_backend_retain_syncs_when_graph_enabled(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_GRAPH", True)
    monkeypatch.setattr("localagent.config.NEO4J", False)
    backend = JsonMemoryBackend()
    fact_id = backend.retain(
        "用户居住在深圳。",
        metadata={
            "slots": {"subject": "用户", "action": "居住在", "object": "深圳", "location": "深圳"},
            "entities": ["用户", "深圳"],
        },
    )
    assert fact_id
    stats = get_memory_graph().stats()
    assert stats["facts"] >= 1
    assert stats["entities"] >= 1

    assert backend.delete(fact_id)
    stats_after = get_memory_graph().stats()
    assert stats_after["facts"] == 0


def test_graph_disabled_skips_expand(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_GRAPH", False)
    monkeypatch.setattr("localagent.config.NEO4J", False)
    hits = [{"id": "x", "text": "hello", "score": 1.0, "metadata": {}}]
    assert expand_hits_by_graph("hello", hits) is hits


def test_protect_seed_prefix_keeps_top1(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_GRAPH_PROTECT_TOP", 1)
    # seed_ranked = post seed-only rerank (baseline top-1)
    seed_ranked = [
        {"id": "seed-a", "text": "seed winner", "score": 0.95, "source": "lexical"},
        {"id": "seed-b", "text": "seed second", "score": 0.5, "source": "lexical"},
    ]
    ranked = [
        {"id": "graph-x", "text": "graph noise", "score": 0.99, "source": "graph"},
        {"id": "seed-a", "text": "seed winner", "score": 0.8, "source": "lexical"},
        {"id": "seed-b", "text": "seed second", "score": 0.7, "source": "lexical"},
        {"id": "graph-y", "text": "graph related", "score": 0.6, "source": "graph"},
    ]
    out = protect_seed_prefix(seed_ranked, ranked, max_results=5, force_graph_n=2)
    assert out[0]["id"] == "seed-a"
    assert out[0].get("graph_protected") is True
    # Graph extras are force-inserted right after the protected prefix.
    assert out[1]["id"] == "graph-x"
    assert out[1].get("graph_forced") is True
    assert any(hit["id"] == "graph-y" for hit in out)


def test_protect_keeps_graph_extra_in_top5(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_GRAPH", True)
    monkeypatch.setattr("localagent.config.MEMORY_GRAPH_HOPS", 2)
    monkeypatch.setattr("localagent.config.MEMORY_GRAPH_PROTECT_TOP", 1)
    monkeypatch.setattr("localagent.config.MEMORY_GRAPH_BOOST", 0.0)

    store = get_memory_store()
    f1 = store.retain_from_section(
        filename="chat",
        heading="a",
        text="Caroline met Melanie at the gallery.",
        chunk_id="a1",
        extra_metadata={
            "entities": ["Caroline", "Melanie"],
            "slots": {"subject": "Caroline", "action": "met", "object": "Melanie"},
            "dia_id": "D1:1",
        },
    )
    f2 = store.retain_from_section(
        filename="chat",
        heading="b",
        text="Melanie adopted a dog named Bailey.",
        chunk_id="b1",
        extra_metadata={
            "entities": ["Melanie", "Bailey"],
            "slots": {"subject": "Melanie", "action": "adopted", "object": "Bailey"},
            "dia_id": "D1:2",
        },
    )
    store.save()
    assert f1 and f2
    rebuild_memory_graph()

    seed = [
        {
            "id": f1.id,
            "text": f1.text,
            "score": 0.9,
            "rrf_score": 0.05,
            "metadata": f1.metadata,
            "source": "lexical",
        }
    ]
    expanded = expand_hits_by_graph("What did Melanie adopt?", seed, facts=store.all_facts())
    # Simulate rerank putting graph hit first.
    ranked = sorted(
        expanded,
        key=lambda h: (0 if h.get("source") == "graph" else 1, -float(h.get("score") or 0)),
    )
    out = protect_seed_prefix(seed, ranked, max_results=5)
    assert out[0]["id"] == f1.id
    assert any(hit.get("id") == f2.id for hit in out)
