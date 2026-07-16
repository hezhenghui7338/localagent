"""E2E: Warm memory pending approval gate (PRD §6.2 / product-tour)."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import memory_fact_ids, run_la, seed_memory, seed_pending_queue, warm_count

pytestmark = pytest.mark.e2e

FACT = "用户喜欢喝美式咖啡，不喜欢拿铁，这是 e2e pending 测试事实。"


def test_e2e_memory_help_lists_pending_commands(la_env):
    result = run_la(["memory", "--help"], env=la_env)
    assert result.returncode == 0
    for token in ("pending", "approve", "reject"):
        assert token in result.stdout


def test_e2e_memory_add_bypasses_pending(la_env_pending):
    """Documented: LA memory add still writes Warm directly."""
    before = warm_count(la_env_pending)
    seed_memory(la_env_pending, FACT)
    assert warm_count(la_env_pending) == before + 1
    pending = run_la(["memory", "pending"], env=la_env_pending)
    assert pending.returncode == 0
    assert "队列为空" in pending.stdout or FACT[:20] not in pending.stdout


def test_e2e_pending_approve_writes_warm(la_env_pending, la_data_dir: Path):
    ids = seed_pending_queue(la_data_dir, [FACT])
    listed = run_la(["memory", "pending"], env=la_env_pending)
    assert listed.returncode == 0
    assert ids[0] in listed.stdout
    assert FACT[:20] in listed.stdout

    before = warm_count(la_env_pending)
    approve = run_la(["memory", "approve", ids[0]], env=la_env_pending)
    assert approve.returncode == 0
    assert "已写入 Warm" in approve.stdout
    assert warm_count(la_env_pending) == before + 1

    search = run_la(["memory", "search", "美式咖啡"], env=la_env_pending)
    assert search.returncode == 0
    assert "美式" in search.stdout or "咖啡" in search.stdout

    empty = run_la(["memory", "pending"], env=la_env_pending)
    assert "队列为空" in empty.stdout


def test_e2e_pending_reject_skips_warm(la_env_pending, la_data_dir: Path):
    ids = seed_pending_queue(la_data_dir, ["用户在深圳工作，专注本地 AI 助手 e2e reject。"])
    before = warm_count(la_env_pending)
    reject = run_la(["memory", "reject", ids[0]], env=la_env_pending)
    assert reject.returncode == 0
    assert "已丢弃" in reject.stdout
    assert warm_count(la_env_pending) == before
    assert memory_fact_ids(la_data_dir) == [] or before == warm_count(la_env_pending)


def test_e2e_pending_approve_all_and_reject_all(la_env_pending, la_data_dir: Path):
    seed_pending_queue(
        la_data_dir,
        [
            "事实甲：用户养了一只猫，e2e approve-all。",
            "事实乙：用户周末喜欢徒步，e2e approve-all。",
        ],
    )
    approve = run_la(["memory", "approve", "--all"], env=la_env_pending)
    assert approve.returncode == 0
    assert "已写入 Warm 2 条" in approve.stdout or "Warm 2" in approve.stdout

    seed_pending_queue(
        la_data_dir,
        ["事实丙：应被拒绝的候选，e2e reject-all。"],
    )
    before = warm_count(la_env_pending)
    reject = run_la(["memory", "reject", "--all"], env=la_env_pending)
    assert reject.returncode == 0
    assert "已丢弃" in reject.stdout
    assert warm_count(la_env_pending) == before
