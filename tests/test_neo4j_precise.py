"""Tests for Neo4j precise graph query path (templates + in-memory store)."""

from __future__ import annotations

from localagent.memory.graph.cypher_guard import validate_readonly_cypher
from localagent.memory.graph.neo4j_store import (
    rebuild_neo4j_graph,
    reset_neo4j_store_singleton,
    sync_fact_to_neo4j,
)
from localagent.memory.graph.precise_query import (
    classify_precise_query,
    precise_graph_query,
    run_template,
)
from localagent.memory.graph.cypher_templates import get_template
from localagent.memory.store import MemoryFact, get_memory_store
from localagent.tools import query_memory_graph


def test_cypher_guard_rejects_writes():
    bad = validate_readonly_cypher("MATCH (n) DELETE n RETURN n")
    assert not bad.ok
    ok = validate_readonly_cypher(
        "MATCH (e:Entity)-[:MENTIONS]->(f:Fact) RETURN count(f) AS value"
    )
    assert ok.ok
    assert "LIMIT" in ok.limited_cypher.upper()


def test_classify_count_and_collect():
    intent = classify_precise_query("How many times was Caroline mentioned?")
    assert intent.kind == "count"
    assert intent.template_id in {"count_facts_mentioning", "count_relations"}
    assert any("Caroline" in e for e in intent.entities)

    intent2 = classify_precise_query("列出与 Melanie 相关的城市")
    assert intent2.kind == "collect"
    assert intent2.template_id == "collect_related"


def test_classify_co_mention():
    intent = classify_precise_query("Caroline and Melanie were mentioned together how many times?")
    assert intent.kind == "co_mention"
    assert intent.template_id == "co_mention_count"
    assert len(intent.entities) >= 2


def test_memory_neo4j_count_and_co_mention(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.NEO4J", True)
    monkeypatch.setattr("localagent.config.NEO4J_URI", "memory://")
    reset_neo4j_store_singleton()

    from localagent.memory.graph.neo4j_store import get_neo4j_store

    store = get_neo4j_store()
    f1 = MemoryFact(
        id="f-car-1",
        text="Caroline met Melanie at the gallery.",
        source_file="chat",
        section_heading="a",
        created_at="2026-01-01T00:00:00",
        metadata={
            "entities": ["Caroline", "Melanie", "gallery"],
            "slots": {
                "subject": "Caroline",
                "action": "met",
                "object": "Melanie",
                "location": "gallery",
            },
        },
    )
    f2 = MemoryFact(
        id="f-car-2",
        text="Caroline visited Paris.",
        source_file="chat",
        section_heading="b",
        created_at="2026-01-02T00:00:00",
        metadata={
            "entities": ["Caroline", "Paris"],
            "slots": {
                "subject": "Caroline",
                "action": "visited",
                "object": "Paris",
                "location": "Paris",
            },
        },
    )
    sync_fact_to_neo4j(f1)
    sync_fact_to_neo4j(f2)

    stats = store.stats()
    assert stats["entities"] >= 3
    assert stats["facts"] == 2

    count_tpl = get_template("count_facts_mentioning")
    assert count_tpl is not None
    result = run_template(
        count_tpl,
        "How many times was Caroline mentioned?",
        ["Caroline"],
        store=store,
    )
    assert result.ok
    assert result.value == 2
    assert set(result.fact_ids) == {"f-car-1", "f-car-2"}

    co_tpl = get_template("co_mention_count")
    assert co_tpl is not None
    co = run_template(
        co_tpl,
        "Caroline and Melanie mentioned together",
        ["Caroline", "Melanie"],
        store=store,
    )
    assert co.ok
    assert co.value == 1

    collect_tpl = get_template("collect_related")
    assert collect_tpl is not None
    collected = run_template(
        collect_tpl,
        "哪些与 Caroline 相关的地点",
        ["Caroline"],
        store=store,
    )
    assert collected.ok
    assert isinstance(collected.value, list)
    assert any("Paris" in str(v) or "gallery" in str(v) for v in collected.value)

    reset_neo4j_store_singleton()


def test_precise_graph_query_end_to_end(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.NEO4J", True)
    monkeypatch.setattr("localagent.config.NEO4J_URI", "memory://")
    reset_neo4j_store_singleton()

    mem = get_memory_store()
    f1 = mem.retain_from_section(
        filename="chat",
        heading="a",
        text="Caroline met Melanie at the gallery.",
        chunk_id="a1",
        extra_metadata={
            "entities": ["Caroline", "Melanie"],
            "slots": {
                "subject": "Caroline",
                "action": "met",
                "object": "Melanie",
            },
        },
    )
    f2 = mem.retain_from_section(
        filename="chat",
        heading="b",
        text="Caroline visited Paris.",
        chunk_id="b1",
        extra_metadata={
            "entities": ["Caroline", "Paris"],
            "slots": {
                "subject": "Caroline",
                "action": "visited",
                "object": "Paris",
                "location": "Paris",
            },
        },
    )
    mem.save()
    assert f1 is not None and f2 is not None

    stats = rebuild_neo4j_graph()
    assert stats["facts"] >= 2

    result = precise_graph_query(
        "How many times was Caroline mentioned?",
        fallback_hybrid=False,
    )
    assert result.ok
    assert result.value == 2
    assert not result.fallback

    tool_out = query_memory_graph("How many times was Caroline mentioned?")
    assert "2" in tool_out

    reset_neo4j_store_singleton()


def test_query_memory_graph_disabled(monkeypatch):
    monkeypatch.setattr("localagent.config.NEO4J", False)
    out = query_memory_graph("How many times was Caroline mentioned?")
    assert "未启用" in out


def test_cli_memory_graph_neo4j_and_query(isolated_data, monkeypatch):
    from localagent.cli import main

    monkeypatch.setattr("localagent.config.NEO4J", True)
    monkeypatch.setattr("localagent.config.NEO4J_URI", "memory://")
    reset_neo4j_store_singleton()

    mem = get_memory_store()
    mem.retain_from_section(
        filename="chat",
        heading="a",
        text="Caroline visited Paris.",
        chunk_id="c1",
        extra_metadata={
            "entities": ["Caroline", "Paris"],
            "slots": {
                "subject": "Caroline",
                "action": "visited",
                "object": "Paris",
                "location": "Paris",
            },
        },
    )
    mem.save()

    assert main(["memory", "graph", "neo4j", "rebuild"]) == 0
    assert main(["memory", "graph", "neo4j", "stats"]) == 0
    assert main(["memory", "graph", "query", "How many times was Caroline mentioned?"]) == 0

    reset_neo4j_store_singleton()
