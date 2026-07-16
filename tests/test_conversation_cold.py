"""Tests for conversation → Cold RAG indexing."""

from __future__ import annotations

import json
from pathlib import Path

from localagent.ingest.conversation_cold import (
    build_conversation_chunks,
    cold_source_key,
    count_chunks_by_origin,
    index_conversation_cold,
    needs_cold_backfill,
    remove_conversations_by_origin,
)
from localagent.knowledge.hybrid import get_hybrid_retriever, reset_hybrid_retriever
from localagent.knowledge.indexer import get_knowledge_indexer
from localagent.memory.chatgpt_import import import_chatgpt_file
from localagent.memory.conversation_extract import ExtractedMemory
from localagent.memory.reset import reset_memory
from localagent.persist.chatgpt import parse_conversation
from localagent.tools import search_knowledge


def _make_conversation(
    *,
    conversation_id: str = "conv-cold-1",
    title: str = "Rust 学习计划",
    is_do_not_remember: bool = False,
    user_text: str = "我计划在2026年系统学习 Rust 语言，重点做系统编程",
    assistant_text: str = "很好的计划，可以从 Ownership 开始。",
) -> dict:
    user_id = "user-node"
    assistant_id = "assistant-node"
    root_id = "root-node"
    return {
        "conversation_id": conversation_id,
        "id": conversation_id,
        "title": title,
        "create_time": 1757058223.0,
        "update_time": 1757058263.0,
        "current_node": assistant_id,
        "is_do_not_remember": is_do_not_remember,
        "mapping": {
            root_id: {"id": root_id, "parent": None, "message": None},
            user_id: {
                "id": user_id,
                "parent": root_id,
                "message": {
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": [user_text]},
                    "create_time": 1757058223.1,
                },
            },
            assistant_id: {
                "id": assistant_id,
                "parent": user_id,
                "message": {
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": [assistant_text]},
                    "create_time": 1757058223.2,
                },
            },
        },
    }


def test_cold_source_key():
    assert cold_source_key("chatgpt", "abc") == "chatgpt:abc"
    assert cold_source_key("chat", "s-123") == "chat:s-123"


def test_needs_cold_backfill():
    assert needs_cold_backfill(None) is False
    assert needs_cold_backfill({}) is True
    assert needs_cold_backfill({"saved_count": 1}) is True
    assert needs_cold_backfill({"cold_chunk_count": 0}) is False
    assert needs_cold_backfill({"cold_chunk_count": 3}) is False


def test_build_conversation_chunks_has_summary_and_body(isolated_data):
    conv = parse_conversation(_make_conversation())
    chunks = build_conversation_chunks(
        conv,
        origin="chatgpt",
        archive_path="conversations-test.json",
    )
    assert chunks
    kinds = {c.metadata.get("chunk_kind") for c in chunks}
    assert "summary" in kinds
    assert "body" in kinds
    for chunk in chunks:
        assert chunk.metadata.get("origin") == "chatgpt"
        assert chunk.metadata.get("conversation_id") == "conv-cold-1"
        assert chunk.metadata.get("archive_path") == "conversations-test.json"


def test_index_skips_do_not_remember_and_empty(isolated_data):
    dnr = parse_conversation(_make_conversation(is_do_not_remember=True))
    assert index_conversation_cold(dnr, origin="chatgpt", archive_path="x.json") == 0

    empty_raw = _make_conversation()
    empty_raw["mapping"] = {"root": {"id": "root", "parent": None, "message": None}}
    empty_raw["current_node"] = "root"
    empty_conv = parse_conversation(empty_raw)
    assert index_conversation_cold(empty_conv, origin="chatgpt", archive_path="x.json") == 0


def test_index_conversation_cold_searchable(isolated_data):
    conv = parse_conversation(_make_conversation())
    count = index_conversation_cold(
        conv,
        origin="chatgpt",
        archive_path="conversations-test.json",
    )
    assert count >= 1
    reset_hybrid_retriever()
    hits = get_hybrid_retriever().retrieve("Rust 系统编程", top_k=5)
    assert hits
    assert any(
        (h.get("metadata") or {}).get("conversation_id") == "conv-cold-1" for h in hits
    )
    formatted = search_knowledge("Rust", top_k=5, fallback=False)
    assert "chatgpt" in formatted.lower() or "Rust" in formatted


def test_import_no_facts_still_indexes_cold(isolated_data, tmp_path: Path):
    export_path = tmp_path / "no-facts.json"
    export_path.write_text(
        json.dumps([_make_conversation()], ensure_ascii=False),
        encoding="utf-8",
    )
    isolated_data["router"].extract_memories.return_value = []

    summary = import_chatgpt_file(export_path)
    assert summary.imported == 0
    assert summary.skipped_empty == 1
    assert summary.cold_chunks >= 1

    hits = get_hybrid_retriever().retrieve("Rust", top_k=5)
    assert hits


def test_import_with_facts_also_cold(isolated_data, tmp_path: Path):
    export_path = tmp_path / "with-facts.json"
    export_path.write_text(
        json.dumps([_make_conversation()], ensure_ascii=False),
        encoding="utf-8",
    )
    isolated_data["router"].extract_memories.return_value = [
        ExtractedMemory(text="用户计划在2026年系统学习 Rust 语言")
    ]
    summary = import_chatgpt_file(export_path)
    assert summary.imported == 1
    assert summary.cold_chunks >= 1


def test_cold_backfill_when_index_missing_cold_field(isolated_data, tmp_path: Path):
    export_path = tmp_path / "backfill.json"
    export_path.write_text(
        json.dumps([_make_conversation(conversation_id="bf-1")], ensure_ascii=False),
        encoding="utf-8",
    )
    isolated_data["router"].extract_memories.return_value = [
        ExtractedMemory(text="用户计划学习 Rust")
    ]
    first = import_chatgpt_file(export_path)
    assert first.imported == 1

    # Simulate legacy index entry without cold_chunk_count
    from localagent import config

    index_path = config.CHATGPT_IMPORT_INDEX_FILE
    raw = json.loads(index_path.read_text(encoding="utf-8"))
    entry = raw["processed"]["bf-1"]
    entry.pop("cold_chunk_count", None)
    entry.pop("cold_indexed_at", None)
    index_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    get_knowledge_indexer().remove_by_source_file("chatgpt:bf-1")
    reset_hybrid_retriever()

    second = import_chatgpt_file(export_path)
    assert second.cold_backfill == 1
    assert second.cold_chunks >= 1
    assert second.imported == 0


def test_reset_chatgpt_removes_cold_chunks(isolated_data, tmp_path: Path):
    export_path = tmp_path / "reset-cold.json"
    export_path.write_text(
        json.dumps([_make_conversation(conversation_id="rst-1")], ensure_ascii=False),
        encoding="utf-8",
    )
    isolated_data["router"].extract_memories.return_value = []
    import_chatgpt_file(export_path)
    assert count_chunks_by_origin().get("chatgpt", 0) >= 1

    stats = reset_memory(source="chatgpt", clear_knowledge=False)
    assert stats["knowledge_chunks_removed"] >= 1
    assert count_chunks_by_origin().get("chatgpt", 0) == 0


def test_remove_by_origin_helper(isolated_data):
    conv = parse_conversation(_make_conversation(conversation_id="rm-1"))
    index_conversation_cold(conv, origin="chat", archive_path="s-rm-1.json")
    assert count_chunks_by_origin().get("chat", 0) >= 1
    removed = remove_conversations_by_origin("chat")
    assert removed >= 1
    assert count_chunks_by_origin().get("chat", 0) == 0
