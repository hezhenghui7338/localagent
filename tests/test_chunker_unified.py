"""Tests for unified document chunking (Chonkie-backed)."""

from __future__ import annotations

import pytest

from localagent import config
from localagent.ingest.chunker import (
    ChunkBudget,
    ChunkMode,
    _chonkie_split_text,
    _la_recursive_rules,
    chunk_document,
    chunk_for_rag,
    resolve_chunk_budget,
    split_into_sections,
)
from localagent.summarize.segment_reader import build_segments, resolve_reading_budget


def test_resolve_chunk_budget_ollama_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_TARGET_CHARS", 0)
    monkeypatch.setattr(config, "MODEL_PROVIDER_PRIORITY", ("ollama",))
    budget = resolve_chunk_budget(mode=ChunkMode.READING, provider="ollama")
    assert budget.target_chars == 1000
    assert budget.hard_max == 1200


def test_resolve_chunk_budget_cursor_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_TARGET_CHARS", 0)
    monkeypatch.setattr(
        "localagent.ingest.chunker._resolve_provider_name",
        lambda _provider: "cursor",
    )
    budget = resolve_chunk_budget(mode=ChunkMode.READING, provider="cursor")
    assert budget.target_chars == 3500
    assert budget.hard_max == 4200


def test_env_override_segment_target(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_TARGET_CHARS", 1200)
    budget = resolve_chunk_budget(mode=ChunkMode.READING, provider="ollama")
    assert budget.target_chars == 1200
    assert budget.hard_max == 1440


def test_rag_budget_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "RAG_CHUNK_SIZE", 400)
    monkeypatch.setattr(config, "RAG_CHUNK_OVERLAP", 50)
    budget = resolve_chunk_budget(mode=ChunkMode.RAG)
    assert budget.target_chars == 400
    assert budget.overlap == 50


def test_la_recursive_rules_defined():
    rules = _la_recursive_rules()
    assert rules is not None
    assert len(rules.levels) >= 3


def test_chonkie_split_not_mechanical():
    text = ("This is a sentence. " * 80 + "\n\n") * 5
    parts = _chonkie_split_text(text, target=1000, hard_max=1200)
    assert len(parts) >= 2
    assert not all(len(p) == 1200 for p in parts)


def test_chunk_sizes_within_60_120_percent():
    target = 1000
    hard_max = 1200
    min_chars = int(target * 0.6)
    text = "\n\n".join(
        " ".join(f"Word{i}." for i in range(20)) for _ in range(80)
    )
    budget = ChunkBudget(target_chars=target, hard_max=hard_max, min_merge=400)
    chunks = chunk_document(text, filename="long.md", mode=ChunkMode.READING, budget=budget)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk.text) <= hard_max
        assert len(chunk.text) >= min_chars or len(chunks) == 1


def test_no_tiny_tail_segment():
    target = 1000
    hard_max = 1200
    min_chars = int(target * 0.6)
    text = "# Chapter\n\n" + ("Sentence ends here. " * 120 + "\n\n") * 8
    budget = ChunkBudget(target_chars=target, hard_max=hard_max, min_merge=400)
    chunks = chunk_document(text, filename="book.md", mode=ChunkMode.READING, budget=budget)
    assert len(chunks) >= 2
    assert len(chunks[-1].text) >= min_chars


def test_split_at_sentence_boundary():
    text = "First sentence here. " * 200
    parts = _chonkie_split_text(text, target=1000, hard_max=1200)
    assert len(parts) >= 2
    for part in parts[:-1]:
        assert part.rstrip()[-1] in ".!?。！？" or part.endswith("here.")


def test_continuation_title_not_nested():
    text = "## [§Chapter I]\n\n" + ("Paragraph text. " * 300)
    budget = ChunkBudget(target_chars=800, hard_max=960, min_merge=200)
    chunks = chunk_document(text, filename="gatsby.mobi", mode=ChunkMode.READING, budget=budget)
    assert len(chunks) >= 2
    for chunk in chunks[1:]:
        assert chunk.heading.count("（续") <= 1


def test_chunk_document_reading_respects_headings():
    text = (
        "# 第一章\n\n"
        + "短。" * 50
        + "\n\n# 第二章\n\n"
        + "较长内容。" * 200
        + "\n\n# 第三章\n\n"
        + "结尾。" * 50
    )
    budget = ChunkBudget(target_chars=800, hard_max=960, min_merge=400)
    chunks = chunk_document(text, filename="t.md", mode=ChunkMode.READING, budget=budget)
    assert len(chunks) >= 2
    assert all(c.text.strip() for c in chunks)


def test_build_segments_matches_reading_mode():
    text = "# A\n\n" + "x" * 1200 + "\n\n# B\n\n" + "y" * 1200
    segments = build_segments(text, target_chars=800, segment_max=960, filename="t.md")
    assert len(segments) >= 2
    assert segments[0].index == 0


def test_chunk_for_rag_produces_overlap_parts():
    text = "# 章节\n\n" + ("段落内容。" * 80 + "\n\n") * 4
    chunks = chunk_for_rag(text, filename="doc.md", chunk_size=512, overlap=64)
    assert len(chunks) >= 2
    assert all(c.chunk_id.endswith("-rag-000") or "-rag-" in c.chunk_id for c in chunks)


def test_pdf_page_structural_split():
    text = "## [p.1]\n第一页内容。\n\n## [p.2]\n第二页内容。" * 50
    budget = ChunkBudget(target_chars=500, hard_max=600, min_merge=200)
    chunks = chunk_document(text, filename="doc.pdf", mode=ChunkMode.READING, budget=budget)
    assert len(chunks) >= 2


def test_resolve_reading_budget_uses_chunk_budget(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_TARGET_CHARS", 0)
    budget = resolve_reading_budget("ollama")
    assert budget.segment_target == 1000
    assert budget.segment_max == 1200


def test_split_into_sections_uses_chonkie_for_long_sections():
    text = "# 标题\n\n" + "内容。" * 2000
    chunks = split_into_sections(text, filename="long.md", target_chars=800, hard_max=960)
    assert len(chunks) >= 2
