"""Tests for memory enrichment and display."""

from __future__ import annotations

from localagent.memory.display import format_memory_hit, format_memory_hits
from localagent.memory.enrich import enrich_heuristic, enrich_memory


def test_enrich_heuristic_preserves_leading_year():
    text = "2026年3月，开发者决定用 Python 重写个人助手，项目代号 LocalAgent"
    result = enrich_heuristic(text)
    assert result.title.startswith("2026年3月")


def test_enrich_heuristic_generates_title_tags_summary():
    text = "2026年7月决定使用 Hindsight 作为记忆引擎，用于管理长期记忆。"
    result = enrich_heuristic(text, heading="技术决策")
    assert result.title
    assert "Hindsight" in result.summary or "Hindsight" in result.searchable_text
    assert "技术" in result.tags or "决策" in result.tags
    assert result.memory_type in ("fact", "preference", "plan")


def test_enrich_heuristic_summarizes_long_text():
    text = "。" + "这是一段很长的个人反思内容。" * 30
    result = enrich_heuristic(text, heading="自我批评")
    assert len(result.summary) <= 210
    assert result.searchable_text


def test_format_memory_hit_readable_card():
    hit = {
        "id": "abc12345-0000-0000-0000-000000000000",
        "text": "2026年7月决定使用 Hindsight 作为记忆引擎",
        "score": 0.82,
        "created_at": "2026-07-11T16:00:00",
        "source_file": "LA add",
        "section_heading": "技术决策",
        "metadata": {
            "title": "采用 Hindsight",
            "summary": "2026年7月决定使用 Hindsight 作为记忆引擎",
            "tags": ["技术", "决策"],
            "type": "fact",
            "source": "manual_add",
        },
    }
    rendered = format_memory_hit(hit, index=1, show_ids=True)
    assert "### 1. 采用 Hindsight" in rendered
    assert "相关度 0.82" in rendered
    assert "#技术" in rendered
    assert "Hindsight" in rendered
    assert "id: abc12345" in rendered


def test_format_memory_hits_header():
    hits = [
        {
            "id": "x",
            "text": "测试记忆",
            "score": 0.5,
            "created_at": "2026-07-11",
            "source_file": "manual",
            "metadata": {"title": "测试"},
        }
    ]
    rendered = format_memory_hits(hits, query="测试")
    assert "找到 1 条相关记忆" in rendered
    assert "查询: 测试" in rendered


def test_enrich_memory_fallback_for_empty():
    result = enrich_memory("   ")
    assert result.title == "空记忆"
