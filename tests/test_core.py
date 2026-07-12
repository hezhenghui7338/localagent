"""Unit tests for core memory and retrieval modules."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from localagent.knowledge.hybrid import reciprocal_rank_fusion
from localagent.memory.scoped_recall import scoped_recall
from localagent.memory.temporal_intent import parse_temporal_intent
from localagent.memory.value_filter import is_valuable, should_retain_as_memory
from localagent.cli import main
from localagent.tools import search_memory


def test_value_filter():
    assert not is_valuable("好的")
    assert is_valuable("2026年7月决定使用 Hindsight 作为记忆引擎")


def test_should_retain_as_memory():
    assert should_retain_as_memory("2026年7月决定使用 Hindsight 作为记忆引擎", heading="# 日记")
    assert should_retain_as_memory("今天决定用 Hindsight 做记忆引擎。", heading="# 日记")
    assert not should_retain_as_memory("x" * 900, heading="## 附录")
    assert not should_retain_as_memory("- item\n- item\n- item\n- item\n- item", heading="## 参考")
    assert should_retain_as_memory("rebuild memory test content", heading="# Rebuild")
    # 含个人标记的长文本应保留（修复原先被长度规则提前拒绝的问题）
    personal_long = "我决定" + "x" * 1000
    assert should_retain_as_memory(personal_long, heading="## 附录")
    # 更短的事实也应通过
    assert is_valuable("我决定用 Rust")


def test_temporal_intent_month():
    intent = parse_temporal_intent("2026年5月 做了什么决定？")
    assert intent.anchor_date == "2026-05-15"
    assert intent.scope_start == "2026-05-01"
    assert intent.scope_end == "2026-05-31"


def test_temporal_intent_year():
    intent = parse_temporal_intent("2024年我在做什么项目？")
    assert intent.anchor_date is not None
    assert "2024" in intent.anchor_date


def test_rrf_fusion():
    dense = [{"chunk_id": "a", "text": "A", "score_dense": 0.9}]
    sparse = [{"chunk_id": "b", "text": "B", "score_sparse": 5.0}]
    fused = reciprocal_rank_fusion([dense, sparse], top_k=2)
    assert len(fused) == 2
    assert fused[0]["chunk_id"] in ("a", "b")


def test_scoped_recall_finds_added_memory():
    main(["add", "2026年7月决定使用 Hindsight 作为记忆引擎"])
    hits = scoped_recall("Hindsight 记忆引擎", max_results=3)
    assert hits
    assert any("Hindsight" in h["text"] for h in hits)


def test_scoped_recall_matches_chinese_preference_query():
    poem = "我喜欢这首诗:才行积雪上,又踏熏风花草路"
    main(["add", poem])
    hits = scoped_recall("我喜欢什么诗歌?", max_results=5)
    assert hits
    assert any(poem in h["text"] for h in hits)


def test_search_memory_falls_back_to_knowledge():
    with (
        patch("localagent.tools.get_memory_backend") as backend_getter,
        patch(
            "localagent.tools.search_knowledge",
            return_value="- [0.500] 技术方案 (spec.md)\n  LocalAgent 使用 Hindsight",
        ) as knowledge,
    ):
        backend = MagicMock()
        backend.recall.return_value = []
        backend_getter.return_value = backend
        result = search_memory("Hindsight")
    assert "记忆未命中" in result
    assert "Hindsight" in result
    knowledge.assert_called_once_with("Hindsight", top_k=5, fallback=False)


def test_search_memory_falls_back_to_documents():
    with (
        patch("localagent.tools.get_memory_backend") as backend_getter,
        patch("localagent.tools.search_knowledge", return_value="未找到相关知识片段。"),
        patch(
            "localagent.tools.search_documents",
            return_value="- [1] journal.md\n  我决定使用 Hindsight",
        ) as documents,
    ):
        backend = MagicMock()
        backend.recall.return_value = []
        backend_getter.return_value = backend
        result = search_memory("Hindsight")
    assert "记忆和 RAG 均未命中" in result
    assert "Hindsight" in result
    documents.assert_called_once_with("Hindsight", top_k=5)

