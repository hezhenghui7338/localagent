"""Tests for add-file / sync-file Cold RAG ingest pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from localagent import config
from localagent.ingest.add_file import add_file
from localagent.ingest.pipeline import IngestStatus
from localagent.ingest.sync_file import sync_files
from localagent.ingest.sync_index import get_sync_index
from localagent.knowledge.indexer import get_knowledge_indexer
from localagent.memory.core_profile import CoreProfile, load_core_profile, save_core_profile
from localagent.memory.reset import rebuild_knowledge, reset_knowledge, reset_memory
from localagent.memory.save import save_facts
from localagent.memory.store import get_memory_store

from conftest import write_doc


def test_add_file_symlinks_and_indexes_cold_only(tmp_path: Path):
    """rag add: symlink + Cold RAG; short docs skip Warm summary by default."""
    source = write_doc(
        tmp_path / "diary.md",
        "# 日记\n\n今天决定用 Hindsight 做记忆引擎。\n\n## 计划\n\n先实现 add-file。",
    )

    before = get_memory_store().count()
    target, result = add_file(source)

    assert target == config.KB_DIR / "diary.md"
    assert target.is_symlink()
    assert os.readlink(target) == str(source.resolve())
    assert result.status == IngestStatus.NEW
    assert result.memory_fact_count == 0
    assert result.knowledge_chunk_count >= 1
    assert get_sync_index().get("diary.md") is not None
    assert get_memory_store().count() == before


def test_sync_file_skips_unchanged(tmp_path: Path):
    source = write_doc(tmp_path / "note.md", "# Note\n\nunchanged content")
    add_file(source)

    summary1 = sync_files(force=False)
    assert summary1.skipped_count == 1

    summary2 = sync_files(force=False)
    assert summary2.skipped_count == 1


def test_sync_file_updates_changed_file(tmp_path: Path):
    source = write_doc(tmp_path / "note.md", "# Note\n\nversion one")
    add_file(source)
    source.write_text("# Note\n\nversion two with more detail", encoding="utf-8")
    summary = sync_files(force=False)
    assert summary.updated_count == 1


def test_reset_knowledge_and_rebuild(tmp_path: Path):
    source = write_doc(tmp_path / "doc.md", "# Doc\n\ncontent for knowledge")
    add_file(source)
    assert get_knowledge_indexer().count() > 0

    save_facts(["用户喜欢喝葡萄酒。"], metadata={"source": "chat", "session_id": "s-test"})
    chat_before = get_memory_store().count()
    assert chat_before >= 1

    stats = reset_knowledge(clear_knowledge=True)
    assert stats["knowledge_chunks_removed"] >= 0
    assert get_knowledge_indexer().count() == 0
    # Chat memories preserved
    assert get_memory_store().count() == chat_before

    _, summary = rebuild_knowledge()
    assert summary.new_count + summary.updated_count >= 1


def test_save_facts_flow():
    before = get_memory_store().count()
    ids = save_facts(
        ["用户计划下周开始 Phase 0 实现"],
        metadata={"source": "chat", "session_id": "s-test"},
    )
    assert len(ids) == 1
    assert get_memory_store().count() == before + 1


def test_core_profile_roundtrip():
    profile = CoreProfile(name="测试用户", current_status="开发 LocalAgent")
    save_core_profile(profile)
    loaded = load_core_profile()
    assert loaded.name == "测试用户"


def test_memory_reset_preserves_knowledge(tmp_path: Path):
    source = write_doc(tmp_path / "keep.md", "# Keep\n\nknowledge stays")
    add_file(source)
    chunks = get_knowledge_indexer().count()
    assert chunks > 0
    save_facts(["用户住在上海。"], metadata={"source": "chat"})

    reset_memory(clear_knowledge=False, source="all")
    assert get_memory_store().count() == 0
    assert get_knowledge_indexer().count() == chunks
