"""Tests for version evaluation infrastructure."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.locomo.ci_smoke import compare_to_baseline
from benchmarks.prd.load_matrix import load_matrix
from benchmarks.prd.report_matrix import evaluate_matrix, summarize


def test_acceptance_matrix_loads():
    matrix = load_matrix()
    items = matrix.get("items") or []
    assert len(items) >= 30
    assert matrix.get("version") == 1


def test_evaluate_matrix_has_critical_items():
    reports = evaluate_matrix()
    summary = summarize(reports)
    assert summary["total"] == len(reports)
    assert "6.2.locomo_recall" in {r.item_id for r in reports}


def test_locomo_baseline_tolerance_pass():
    baseline = {"hit@1": 0.3333, "hit@5": 1.0, "hit@8": 1.0}
    overall = {"hit@1": 0.3333, "hit@5": 1.0, "hit@8": 1.0}
    assert compare_to_baseline(overall, baseline, tolerance=0.02) == []


def test_locomo_baseline_tolerance_fail():
    baseline = {"hit@1": 0.5, "hit@5": 1.0, "hit@8": 1.0}
    overall = {"hit@1": 0.4, "hit@5": 1.0, "hit@8": 1.0}
    errors = compare_to_baseline(overall, baseline, tolerance=0.02)
    assert errors


def test_tiny_baseline_file_exists():
    path = Path(__file__).resolve().parents[1] / "benchmarks" / "locomo" / "baseline_tiny.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "overall" in payload
    assert payload["overall"]["n"] >= 1
