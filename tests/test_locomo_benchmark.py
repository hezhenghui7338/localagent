"""Unit tests for LoCoMo benchmark helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from benchmarks.locomo.answer import answer_question, dedupe_hits, joint_recall
from benchmarks.locomo.dataset import filter_samples, format_turn, iter_memory_items, load_samples
from benchmarks.locomo.ingest import ingest_sample
from benchmarks.locomo.measure_profile import measure_profile_cases
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
    assert any(i["metadata"]["kind"] == "session_summary" for i in items)
    dialogs = [i for i in items if i["metadata"]["kind"] == "dialog"]
    assert len(dialogs) == 4
    assert "Sunny" in dialogs[0]["text"]
    assert "dia_id=D1:1" in dialogs[0]["text"]
    assert "Alice" in (dialogs[0]["metadata"].get("entities") or [])
    assert (dialogs[0]["metadata"].get("slots") or {}).get("subject") == "Alice"

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
        info = ingest_sample(sample)
        assert info.get("cold_chunks", 0) >= 1

        qa = sample["qa"][0]
        result = answer_question(
            qa["question"],
            category=int(qa["category"]),
            mode="recall",
            top_k=8,
            provider="cursor",
        )
        f1 = score_qa_item(
            category=int(qa["category"]),
            prediction=result["prediction"],
            answer=qa["answer"],
        )
        assert "Sunny" in result["prediction"]
        assert f1 > 0.0
        assert "D1:1" in (result.get("retrieved_dia_ids") or [])


def test_dedupe_hits_by_dia_id():
    hits = [
        {"id": "a", "text": "x", "metadata": {"dia_id": "D1:1"}, "score": 0.9},
        {"id": "b", "text": "y", "metadata": {"dia_id": "D1:1"}, "score": 0.8},
        {"id": "c", "text": "z dia_id=D2:1", "metadata": {}, "score": 0.7},
    ]
    out = dedupe_hits(hits, top_k=5)
    assert len(out) == 2
    assert out[0]["id"] == "a"
    assert out[1]["metadata"]["dia_id"] == "D2:1"


def test_joint_recall_rrf_fuses_warm_and_cold():
    from benchmarks.locomo import answer as answer_mod

    warm = [
        {"id": "w1", "text": "warm A", "score": 0.9, "metadata": {"dia_id": "D1:1"}},
        {"id": "w2", "text": "warm B", "score": 0.5, "metadata": {"dia_id": "D1:2"}},
    ]
    cold = [
        {"id": "c1", "text": "cold A", "score": 0.8, "source": "cold", "metadata": {"dia_id": "D1:3"}},
        {"id": "c2", "text": "cold dup", "score": 0.7, "source": "cold", "metadata": {"dia_id": "D1:1"}},
    ]
    with (
        patch.object(answer_mod, "_tag_warm_hits", side_effect=lambda hits: [
            {**h, "source": "warm"} for h in hits
        ]),
        patch(
            "localagent.memory.backend.get_memory_backend",
        ) as backend_factory,
        patch.object(answer_mod, "_recall_cold", return_value=cold),
    ):
        backend_factory.return_value.recall.return_value = warm
        hits = joint_recall("q", top_k=3, mode="joint")
    dias = [(h.get("metadata") or {}).get("dia_id") for h in hits]
    assert "D1:1" in dias
    assert "D1:3" in dias
    assert len(hits) <= 3


def test_ingest_incremental_sessions(tmp_path):
    configure_data_dir(tmp_path / "locomo-incr")
    reset_memory_backend()
    with patch(
        "localagent.memory.backend.get_memory_backend",
        lambda: JsonMemoryBackend(),
    ):
        sample = load_samples(FIXTURE)[0]
        info = ingest_sample(sample, incremental_sessions=True)
        assert info["incremental_sessions"] is True
        assert info["sessions_ingested"] >= 1
        assert info["written"] >= 4


def test_measure_profile_aux_track(tmp_path):
    result = measure_profile_cases(
        [
            {
                "id": "hot-test",
                "pins": {"name": "Bob", "preferences": {"饮品": "咖啡"}},
            }
        ],
        work_dir=tmp_path / "profile",
    )
    assert result["overall"]["profile_field_hit"] == 1.0
    assert result["cases"][0]["profile_hit"] is True


def test_extract_graph_speaker_and_comention():
    from localagent.memory.graph.extract import extract_graph_payload
    from localagent.memory.store import MemoryFact

    fact = MemoryFact(
        id="f1",
        text='[session=1 date=1 May 2023 dia_id=D1:1] Alice said, "Sunny loves the park."',
        source_file="locomo",
        section_heading="s1",
        created_at="2026-01-01T00:00:00",
        metadata={
            "speaker": "Alice",
            "entities": ["Alice", "Sunny"],
            "slots": {"subject": "Alice", "action": "", "object": "Sunny", "location": ""},
            "dia_id": "D1:1",
        },
    )
    payload = extract_graph_payload(fact)
    names = {name for name, _ in payload.entities}
    assert "Alice" in names
    assert "Sunny" in names
    assert any(pred == "SAID_ABOUT" for _s, pred, _d, _c in payload.relations)
    assert any(pred == "CO_MENTIONS" for _s, pred, _d, _c in payload.relations)
