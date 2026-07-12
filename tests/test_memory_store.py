"""Tests for memory store temporal attributes."""

from __future__ import annotations

from localagent.memory.store import get_memory_store


def test_retain_from_section_respects_created_at_override(isolated_data):
    store = get_memory_store()
    fact = store.retain_from_section(
        filename="test.md",
        heading="章节",
        text="2024 年先入职 A 公司，2025 年跳槽到 B 公司",
        chunk_id="c1",
        extra_metadata={"created_at": "2024-06-15T10:00:00"},
    )
    assert fact is not None
    assert fact.metadata["occurred_at"] == "2024-01-01"
    assert fact.metadata["recorded_at"] == "2024-06-15T10:00:00"
    assert fact.created_at == "2024-01-01"
    assert "created_at" not in fact.metadata
