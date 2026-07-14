"""Tests for Warm summary layer and memorize task helpers."""

from __future__ import annotations

from pathlib import Path

from localagent import config
from localagent.ingest.add_file import add_file
from localagent.ingest.pipeline import IngestStatus
from localagent.ingest.tasks import get_task_store
from localagent.memory.store import get_memory_store
from localagent.memory.summarize import (
    build_document_summary_facts,
    heuristic_summary,
)

from conftest import write_doc


def test_heuristic_summary_truncates():
    text = "第一句。第二句。" + ("很长内容。" * 80)
    summary = heuristic_summary(text, max_chars=80)
    assert len(summary) <= 80
    assert "第一句" in summary


def test_build_document_summary_facts_for_long_text(monkeypatch):
    monkeypatch.setattr(config, "INGEST_WARM_SUMMARY", True)
    monkeypatch.setattr(config, "INGEST_SUMMARY_MIN_CHARS", 50)
    monkeypatch.setattr(config, "MEMORY_SUMMARY_USE_LLM", False)
    text = "用户决定采用本地记忆系统。" * 20
    facts = build_document_summary_facts(text, filename="long.md", sections=None)
    assert facts
    assert facts[0]["metadata"]["memory_kind"] == "summary"
    assert "文档摘要" in facts[0]["text"]


def test_add_file_writes_warm_summary_for_long_doc(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "INGEST_WARM_SUMMARY", True)
    monkeypatch.setattr(config, "INGEST_SUMMARY_MIN_CHARS", 50)
    monkeypatch.setattr(config, "MEMORY_SUMMARY_USE_LLM", False)
    monkeypatch.setattr(config, "INGEST_SUMMARY_MAX_SECTIONS", 2)

    body = "# 长文\n\n" + ("这是关于深圳住址与长期记忆计划的说明。" * 30)
    body += "\n\n## 细节\n\n" + ("更多细节内容用于章节摘要。" * 30)
    source = write_doc(tmp_path / "long-notes.md", body)

    before = get_memory_store().count()
    target, result = add_file(source)
    assert target.name == "long-notes.md"
    assert result.status == IngestStatus.NEW
    assert result.knowledge_chunk_count >= 1
    assert result.memory_fact_count >= 1
    assert get_memory_store().count() > before
    texts = " ".join(f.text for f in get_memory_store().all_facts())
    assert "摘要" in texts


def test_create_memorize_session_task(isolated_data):
    task = get_task_store().create_memorize_session(session_id="s-demo")
    assert task.type == "memorize_session"
    assert task.source_path == "s-demo"
    assert task.status.value == "queued"
    listed = get_task_store().list_tasks(limit=5)
    assert any(t.id == task.id for t in listed)
