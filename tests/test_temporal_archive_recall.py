"""Tests for recorded_at write path and Cold hard date filtering."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from localagent.ingest.conversation_cold import _base_provenance, build_conversation_chunks
from localagent.knowledge.bm25_store import BM25Store
from localagent.knowledge.hybrid import HybridRetriever
from localagent.memory.query import query_memories
from localagent.memory.store import MemoryFact, get_memory_store, reset_memory_store_singleton
from localagent.memory.temporal import memory_recorded_time, to_ymd
from localagent.memory.temporal_intent import parse_temporal_intent
from localagent.persist.chatgpt import ChatGPTConversation, ChatGPTMessage


def test_parse_temporal_intent_june_browse():
    intent = parse_temporal_intent("我在2025年6月问过哪些问题")
    assert intent.intent_kind == "range"
    assert intent.scope_start == "2025-06-01"
    assert intent.scope_end == "2025-06-30"


def test_base_provenance_has_recorded_at_ymd():
    meta = _base_provenance(
        origin="chatgpt",
        conversation_id="c1",
        title="t",
        archive_path="a.json",
        create_time=datetime(2025, 6, 15, tzinfo=timezone.utc).timestamp(),
        update_time=None,
    )
    assert meta["recorded_at"].startswith("2025-06-15")
    assert meta["recorded_at_ymd"] == "2025-06-15"


def test_bm25_list_in_range_hard_filter(tmp_path: Path):
    store = BM25Store(tmp_path / "bm25.pkl")
    store.build(
        ["a", "b", "c"],
        ["june chat about rust", "december chat about rust", "kb doc rust"],
        [
            {
                "origin": "chatgpt",
                "recorded_at": "2025-06-10T00:00:00+00:00",
                "recorded_at_ymd": "2025-06-10",
                "chunk_kind": "summary",
                "conversation_id": "j1",
                "title": "June",
            },
            {
                "origin": "chatgpt",
                "recorded_at": "2025-12-06T00:00:00+00:00",
                "recorded_at_ymd": "2025-12-06",
                "chunk_kind": "summary",
                "conversation_id": "d1",
                "title": "Dec",
            },
            {"source_file": "kb.md", "heading": "rust"},
        ],
    )
    since = datetime(2025, 6, 1)
    until = datetime(2025, 6, 30, 23, 59, 59)
    hits = store.list_in_range(
        since=since,
        until=until,
        origins=frozenset({"chat", "chatgpt"}),
    )
    assert len(hits) == 1
    assert hits[0]["metadata"]["conversation_id"] == "j1"

    scored = store.query("rust", 5, since=since, until=until, origins=frozenset({"chatgpt"}))
    assert len(scored) == 1
    assert scored[0]["chunk_id"] == "a"


def test_hybrid_retrieve_filters_dense(tmp_path: Path):
    bm25 = BM25Store(tmp_path / "bm25.pkl")
    bm25.build(
        ["june"],
        ["talk about charcoal"],
        [
            {
                "origin": "chatgpt",
                "recorded_at": "2025-06-01T00:00:00+00:00",
                "recorded_at_ymd": "2025-06-01",
                "chunk_kind": "summary",
                "conversation_id": "j",
            }
        ],
    )
    chroma = MagicMock()
    chroma.query.return_value = [
        {
            "chunk_id": "dec",
            "text": "talk about charcoal in december",
            "metadata": {
                "origin": "chatgpt",
                "recorded_at": "2025-12-06T00:00:00+00:00",
                "recorded_at_ymd": "2025-12-06",
            },
            "score_dense": 0.99,
        },
        {
            "chunk_id": "june",
            "text": "talk about charcoal",
            "metadata": {
                "origin": "chatgpt",
                "recorded_at": "2025-06-01T00:00:00+00:00",
                "recorded_at_ymd": "2025-06-01",
            },
            "score_dense": 0.5,
        },
    ]
    retriever = HybridRetriever(chroma, bm25)
    hits = retriever.retrieve(
        "charcoal",
        top_k=5,
        since="2025-06-01",
        until="2025-06-30",
        conversation_only=True,
    )
    assert hits
    assert all(
        str((h.get("metadata") or {}).get("recorded_at_ymd") or "").startswith("2025-06")
        for h in hits
    )


def test_query_memories_recorded_time_field():
    reset_memory_store_singleton()
    store = get_memory_store()
    store._facts = [
        MemoryFact(
            id="1",
            text="asked about rust",
            source_file="chat",
            section_heading="",
            created_at="2026-01-01",
            metadata={
                "source": "chat",
                "recorded_at": "2025-06-15T12:00:00+00:00",
                "occurred_at": "2026-01-01",
            },
        ),
        MemoryFact(
            id="2",
            text="asked about housing",
            source_file="chat",
            section_heading="",
            created_at="2025-12-01",
            metadata={"source": "chat", "recorded_at": "2025-12-01T00:00:00+00:00"},
        ),
    ]
    store.save()

    hits = query_memories(
        since="2025-06-01",
        until="2025-06-30",
        time_field="recorded",
        limit=10,
    )
    assert len(hits) == 1
    assert hits[0]["id"] == "1"
    assert memory_recorded_time(metadata=hits[0]["metadata"]).startswith("2025-06")


def test_build_conversation_chunks_include_ymd():
    conv = ChatGPTConversation(
        conversation_id="cid",
        title="June talk",
        create_time=datetime(2025, 6, 20, tzinfo=timezone.utc).timestamp(),
        update_time=None,
        is_do_not_remember=False,
        messages=[ChatGPTMessage(role="user", content="hello rust")],
    )
    chunks = build_conversation_chunks(conv, origin="chatgpt", archive_path="x.json")
    assert chunks
    assert all(c.metadata.get("recorded_at_ymd") == "2025-06-20" for c in chunks)
    assert to_ymd(chunks[0].metadata["recorded_at"]) == "2025-06-20"
