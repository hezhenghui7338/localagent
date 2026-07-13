"""Tests for structured memory query."""

from __future__ import annotations

import json

from localagent.cli import main
from localagent.memory.query import list_memory_tags, query_memories
from localagent.memory.store import get_memory_store


def _add_with_tags(text: str, tags: list[str], created_at: str) -> None:
    store = get_memory_store()
    fact = store.retain_from_section(
        filename="test",
        heading="测试",
        text=text,
        chunk_id="test-chunk",
        extra_metadata={"recorded_at": created_at, "tags": tags},
    )
    assert fact is not None
    store.save()


def test_query_memories_semantic_match():
    main(["memory", "add", "2026年7月决定使用 Hindsight 作为记忆引擎"])
    hits = query_memories(query="Hindsight", sort="relevance", limit=5)
    assert hits
    assert any("Hindsight" in hit["text"] for hit in hits)


def test_query_memories_filter_by_tag():
    _add_with_tags("用户偏好深色主题", ["偏好", "界面"], "2026-01-10T10:00:00")
    _add_with_tags("下周开始 Phase 0 实现", ["计划", "工作"], "2026-02-10T10:00:00")

    hits = query_memories(tags=["偏好"], sort="newest", limit=10)
    assert len(hits) == 1
    assert "深色主题" in hits[0]["text"]


def test_query_memories_filter_by_time_range():
    _add_with_tags("2024年的旧记忆", ["事实"], "2024-06-01T10:00:00")
    _add_with_tags("2026年的新记忆", ["事实"], "2026-06-01T10:00:00")

    hits = query_memories(since="2026-01-01", sort="newest", limit=10)
    assert len(hits) == 1
    assert "2026年" in hits[0]["text"]


def test_query_memories_sort_oldest():
    _add_with_tags("较早的记忆", ["事实"], "2024-01-01T10:00:00")
    _add_with_tags("较晚的记忆", ["事实"], "2026-01-01T10:00:00")

    hits = query_memories(sort="oldest", limit=10)
    assert len(hits) >= 2
    assert hits[0]["created_at"] <= hits[-1]["created_at"]


def test_list_memory_tags():
    _add_with_tags("标签统计测试 A", ["工作", "技术"], "2026-03-01T10:00:00")
    _add_with_tags("标签统计测试 B", ["工作"], "2026-03-02T10:00:00")

    ranked = list_memory_tags()
    tag_map = dict(ranked)
    assert tag_map.get("工作", 0) >= 2
    assert tag_map.get("技术", 0) >= 1


def test_cli_memories_browse(capsys):
    main(["memory", "add", "2026年7月决定使用 Hindsight 作为记忆引擎"])
    rc = main(["memory", "query", "--limit", "5"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "记忆库共" in out
    assert "Hindsight" in out


def test_cli_memories_semantic_query(capsys):
    main(["memory", "add", "我喜欢这首诗:才行积雪上,又踏熏风花草路"])
    rc = main(["memory", "query", "诗歌", "--sort", "relevance"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "积雪" in out or "诗歌" in out


def test_cli_memories_list_tags(capsys):
    _add_with_tags("列出标签测试", ["偏好"], "2026-04-01T10:00:00")
    rc = main(["memory", "query", "--list-tags"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "偏好" in out


def test_cli_memories_json_output(capsys):
    main(["memory", "add", "JSON 输出测试记忆内容"])
    capsys.readouterr()
    rc = main(["memory", "query", "--json", "--limit", "3"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    data = json.loads(out)
    assert isinstance(data, list)
    assert data
