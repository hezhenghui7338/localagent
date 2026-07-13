"""Unit tests for LoCoMo benchmark helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from benchmarks.locomo.answer import answer_question
from benchmarks.locomo.dataset import filter_samples, format_turn, iter_memory_items, load_samples
from benchmarks.locomo.ingest import ingest_sample
from benchmarks.locomo.metrics import (
    CATEGORY_NAMES,
    f1_score,
    multi_answer_f1,
    score_qa_item,
    summarize_scores,
)
from benchmarks.locomo.runtime import configure_data_dir
from localagent.memory.backends.json_backend import JsonMemoryBackend
from localagent.memory.backend import reset_memory_backend

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks" / "locomo" / "fixtures" / "tiny.json"


def test_category_names_cover_official_ids():
    assert set(CATEGORY_NAMES) == {1, 2, 3, 4, 5}


def test_f1_and_multi_answer_scoring():
    assert f1_score("Sunny", "Sunny") == 1.0
    assert f1_score("a golden dog", "golden retriever") > 0
    assert multi_answer_f1("pottery, Clara", "pottery, Clara") == 1.0


def test_adversarial_scoring_accepts_abstain():
    assert score_qa_item(category=5, prediction="No information available", answer=None) == 1.0
    assert score_qa_item(category=5, prediction="red", answer=None) == 0.0


def test_open_domain_uses_first_semicolon_segment():
    score = score_qa_item(
        category=3,
        prediction="pottery",
        answer="pottery; ignored extra",
    )
    assert score == 1.0


def test_summarize_scores_by_category():
    summary = summarize_scores(
        [
            {"category": 4, "f1": 1.0},
            {"category": 4, "f1": 0.0},
            {"category": 5, "f1": 1.0},
        ]
    )
    assert summary["n"] == 3
    assert summary["overall_f1"] == 0.6667
    assert summary["categories"]["4"]["n"] == 2
    assert summary["categories"]["4"]["f1"] == 0.5


def test_load_fixture_and_format_turns():
    samples = load_samples(FIXTURE)
    assert len(samples) == 1
    sample = samples[0]
    items = list(iter_memory_items(sample))
    assert any(i["metadata"]["kind"] == "conversation_meta" for i in items)
    dialogs = [i for i in items if i["metadata"]["kind"] == "dialog"]
    assert len(dialogs) == 4
    assert "Sunny" in dialogs[0]["text"]
    assert "dia_id=D1:1" in dialogs[0]["text"]

    turn = format_turn(
        {"speaker": "Alice", "dia_id": "D1:1", "text": "Hi", "blip_caption": "a dog"},
        date_time="now",
        session_num=1,
    )
    assert "shared an image" in turn


def test_filter_samples():
    samples = load_samples(FIXTURE)
    assert filter_samples(samples, sample_ids=["missing"]) == []
    assert filter_samples(samples, sample_ids=["conv-tiny"])[0]["sample_id"] == "conv-tiny"


def test_ingest_tiny_into_isolated_json_backend(tmp_path):
    configure_data_dir(tmp_path / "locomo-tiny")
    reset_memory_backend()
    with patch(
        "localagent.memory.backend.get_memory_backend",
        lambda: JsonMemoryBackend(),
    ):
        sample = load_samples(FIXTURE)[0]
        info = ingest_sample(sample)
        assert info["written"] >= 4
        assert info["memory_count"] >= 4

        hits = JsonMemoryBackend().recall("Alice dog name Sunny", max_results=5)
        assert any("Sunny" in (h.get("text") or "") for h in hits)


def test_end_to_end_recall_mode_scores(tmp_path):
    configure_data_dir(tmp_path / "locomo-e2e")
    reset_memory_backend()
    with patch(
        "localagent.memory.backend.get_memory_backend",
        lambda: JsonMemoryBackend(),
    ):
        sample = load_samples(FIXTURE)[0]
        ingest_sample(sample)

        qa = sample["qa"][0]
        result = answer_question(
            qa["question"],
            category=int(qa["category"]),
            mode="recall",
            top_k=5,
            provider="cursor",
        )
        f1 = score_qa_item(
            category=int(qa["category"]),
            prediction=result["prediction"],
            answer=qa["answer"],
        )
        assert "Sunny" in result["prediction"]
        assert f1 > 0.0
