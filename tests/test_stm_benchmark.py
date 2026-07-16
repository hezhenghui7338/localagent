"""Tests for the short-term memory (STM) benchmark suite."""

from __future__ import annotations

from pathlib import Path

from benchmarks.stm.metrics import THRESHOLDS, summarize_stm
from benchmarks.stm.scenarios import load_cases, run_all
from localagent.agent.runtime import is_session_recall_query

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks" / "stm" / "fixtures" / "cases.json"


def test_load_stm_fixture():
    cases = load_cases(FIXTURE)
    assert cases["routing"]
    assert cases["in_session"]
    assert cases["same_day"]
    assert cases["priority"]


def test_english_today_session_routing():
    assert is_session_recall_query("What did we talk about today?") is True
    assert is_session_recall_query("What did I talk about today?") is True


def test_stm_benchmark_passes_thresholds(tmp_path):
    cases = load_cases(FIXTURE)
    detail = run_all(cases, work_dir=tmp_path / "stm-run")
    summary = summarize_stm(detail)
    assert summary["n"]["routing"] >= 5
    assert summary["routing_accuracy"] >= THRESHOLDS["routing_accuracy"]
    assert summary["in_session_coverage"] >= THRESHOLDS["in_session_coverage"]
    assert summary["session_hit"] >= THRESHOLDS["session_hit"]
    assert summary["priority_win_rate"] >= THRESHOLDS["priority_win_rate"]
    assert summary["passed"] is True
