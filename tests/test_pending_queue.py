"""Tests for Warm memory pending approval queue."""

from __future__ import annotations

from localagent.memory.conversation_extract import ExtractedMemory
from localagent.memory.save import confirm_save_extracted, confirm_save_facts
from localagent.memory.store import get_memory_store
from localagent.pending import (
    approve_all,
    approve_ids,
    list_pending,
    pending_count,
    reject_all,
)


def test_enqueue_then_approve_retains(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_APPROVAL_REQUIRED", True)
    monkeypatch.setattr("localagent.config.MEMORY_APPROVAL_AUTO", False)

    warm_before = get_memory_store().count()
    ids = confirm_save_facts(
        ["用户喜欢喝美式咖啡，不喜欢拿铁。"],
        metadata={"source": "test"},
        interactive=False,
    )
    assert ids == []
    assert pending_count() == 1
    assert get_memory_store().count() == warm_before

    pending = list_pending()
    warm_ids = approve_ids([pending[0].id])
    assert len(warm_ids) == 1
    assert pending_count() == 0
    assert get_memory_store().count() == warm_before + 1


def test_reject_does_not_retain(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_APPROVAL_REQUIRED", True)
    monkeypatch.setattr("localagent.config.MEMORY_APPROVAL_AUTO", False)

    warm_before = get_memory_store().count()
    confirm_save_extracted(
        [ExtractedMemory(text="用户在深圳工作，专注本地 AI 助手。", memory_type="fact")],
        metadata={"source": "test"},
        interactive=False,
    )
    assert pending_count() == 1
    assert reject_all() == 1
    assert pending_count() == 0
    assert get_memory_store().count() == warm_before


def test_auto_approve_bypasses_queue(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_APPROVAL_REQUIRED", True)
    monkeypatch.setattr("localagent.config.MEMORY_APPROVAL_AUTO", True)

    warm_before = get_memory_store().count()
    ids = confirm_save_facts(
        ["用户偏好使用 VS Code 做 Python 开发。"],
        metadata={"source": "test"},
        interactive=False,
    )
    assert len(ids) == 1
    assert pending_count() == 0
    assert get_memory_store().count() == warm_before + 1


def test_approve_all(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_APPROVAL_REQUIRED", True)
    monkeypatch.setattr("localagent.config.MEMORY_APPROVAL_AUTO", False)

    confirm_save_facts(["事实甲：用户养了一只猫。"], interactive=False)
    confirm_save_facts(["事实乙：用户周末喜欢徒步。"], interactive=False)
    assert pending_count() == 2
    warm_ids = approve_all()
    assert len(warm_ids) == 2
    assert pending_count() == 0
