"""Tests for memory temporal resolution."""

from __future__ import annotations

from datetime import datetime

from localagent.memory.store import get_memory_store
from localagent.memory.temporal import (
    effective_memory_time,
    extract_occurred_at,
    memory_effective_time,
    resolve_memory_times,
)


def test_extract_occurred_at_cjk():
    assert extract_occurred_at("2024年6月15日决定跳槽") == "2024-06-15"
    assert extract_occurred_at("2024 年先入职 A 公司") == "2024-01-01"
    assert extract_occurred_at("2025年3月开始新项目") == "2025-03-01"
    assert extract_occurred_at("2026年7月决定使用 Hindsight") == "2026-07-01"


def test_extract_occurred_at_isoish():
    assert extract_occurred_at("事件发生于 2024-06-15") == "2024-06-15"
    assert extract_occurred_at("更新于 2024/06/15") == "2024-06-15"


def test_effective_memory_time_priority():
    assert effective_memory_time(
        occurred_at="2024-01-01",
        recorded_at="2025-01-01",
        indexed_at="2026-01-01",
    ) == "2024-01-01"
    assert effective_memory_time(
        recorded_at="2025-01-01",
        indexed_at="2026-01-01",
    ) == "2025-01-01"
    assert effective_memory_time(indexed_at="2026-01-01") == "2026-01-01"


def test_retain_from_section_sets_occurred_and_recorded(isolated_data):
    store = get_memory_store()
    fact = store.retain_from_section(
        filename="diary.md",
        heading="日记",
        text="2024 年先入职 A 公司，2025 年跳槽到 B 公司",
        chunk_id="c1",
        extra_metadata={
            "recorded_at": "2024-06-15T10:00:00",
        },
    )
    assert fact is not None
    assert fact.metadata["occurred_at"] == "2024-01-01"
    assert fact.metadata["recorded_at"] == "2024-06-15T10:00:00"
    assert fact.metadata["indexed_at"]
    assert fact.created_at == "2024-01-01"


def test_retain_from_section_legacy_created_at_maps_to_recorded(isolated_data):
    store = get_memory_store()
    fact = store.retain_from_section(
        filename="legacy.md",
        heading="旧数据",
        text="没有明确日期的记忆",
        chunk_id="c2",
        extra_metadata={"created_at": "2023-05-01T12:00:00"},
    )
    assert fact is not None
    assert fact.metadata["recorded_at"] == "2023-05-01T12:00:00"
    assert fact.created_at == "2023-05-01T12:00:00"


def test_memory_effective_time_from_metadata():
    effective = memory_effective_time(
        metadata={
            "occurred_at": "2022-01-01",
            "recorded_at": "2023-01-01",
            "indexed_at": "2024-01-01",
        },
        created_at="2024-01-01",
    )
    assert effective == "2022-01-01"


def test_resolve_memory_times_extracts_from_text():
    times = resolve_memory_times(
        text="2026年7月决定使用 Hindsight",
        recorded_at="2026-07-10T08:00:00",
    )
    assert times["occurred_at"] == "2026-07-01"
    assert times["recorded_at"] == "2026-07-10T08:00:00"
    assert times["effective_at"] == "2026-07-01"
    assert datetime.fromisoformat(times["indexed_at"])
