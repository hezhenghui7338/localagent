"""Tests for cognitive memory_class tagging and recall soft-boost."""

from __future__ import annotations

from localagent.memory.enrich import enrich_heuristic
from localagent.memory.memory_class import (
    infer_memory_class,
    memory_class_alignment,
    parse_memory_class_intent,
    resolve_memory_class_for_recall,
    stamp_memory_class,
)
from localagent.memory.scoped_recall import finalize_hybrid_rank
from localagent.memory.temporal_intent import TemporalIntent


def test_infer_type_maps_to_class():
    assert infer_memory_class(memory_type="preference") == "semantic"
    assert infer_memory_class(memory_type="fact") == "semantic"
    assert infer_memory_class(memory_type="experience") == "episodic"
    assert infer_memory_class(memory_type="decision") == "episodic"
    assert infer_memory_class(memory_type="skill") == "procedural"


def test_dia_id_forces_episodic():
    assert (
        infer_memory_class(memory_type="fact", metadata={"dia_id": "D1:3"})
        == "episodic"
    )


def test_stamp_upgrades_semantic_when_dia_id_present():
    meta = stamp_memory_class(
        {"type": "fact", "memory_class": "semantic", "dia_id": "D2:1"},
        text="Caroline said hello",
    )
    assert meta["memory_class"] == "episodic"


def test_resolve_recall_dia_id_overrides_stale_stamp():
    assert (
        resolve_memory_class_for_recall(
            {"type": "fact", "memory_class": "semantic", "dia_id": "D3:9"}
        )
        == "episodic"
    )


def test_enrich_includes_memory_class():
    result = enrich_heuristic("用户喜欢喝葡萄酒。", heading="偏好")
    assert result.memory_class == "semantic"
    assert result.to_metadata()["memory_class"] == "semantic"

    exp = enrich_heuristic("用户感到这次旅行很累。", heading="经历")
    assert exp.memory_class == "episodic"


def test_parse_intent_temporal_is_episodic():
    intent = TemporalIntent(intent_kind="when_event")
    assert parse_memory_class_intent("When did Caroline paint?", intent) == "episodic"


def test_parse_intent_preference_is_semantic():
    assert parse_memory_class_intent("我喜欢什么？") == "semantic"
    assert parse_memory_class_intent("Where do I live?") == "semantic"


def test_parse_intent_how_to_is_procedural():
    assert parse_memory_class_intent("怎么做才能部署这个服务？") == "procedural"
    assert parse_memory_class_intent("How to reset the index?") == "procedural"


def test_alignment_scores():
    assert memory_class_alignment("semantic", "semantic") == 1.0
    assert memory_class_alignment("episodic", "semantic") < 0.5
    assert memory_class_alignment("semantic", None) == 0.5


def test_finalize_prefers_semantic_over_diary_noise(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_RECALL_CLASS_BOOST", True)
    monkeypatch.setattr("localagent.config.MEMORY_CLASS_WEIGHT", 0.25)
    monkeypatch.setattr("localagent.config.MEMORY_RECALL_ENTITY_BOOST", False)
    hits = [
        {
            "id": "diary",
            "text": "今天去菜市场买菜，顺便散了散步，天气不错",
            "score": 0.55,
            "rrf_score": 0.55,
            "metadata": {
                "type": "experience",
                "memory_class": "episodic",
                "dia_id": "D1:1",
            },
            "created_at": "2024-06-01T00:00:00",
        },
        {
            "id": "home",
            "text": "用户居住在深圳南山",
            "score": 0.50,
            "rrf_score": 0.50,
            "metadata": {"type": "fact", "memory_class": "semantic"},
            "created_at": "2024-06-01T00:00:00",
        },
    ]
    ranked = finalize_hybrid_rank("我住在哪里？", hits, max_results=2)
    assert ranked
    assert ranked[0]["id"] == "home"
    assert ranked[0].get("memory_class") == "semantic"


def test_finalize_class_boost_disabled_no_crash(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_RECALL_CLASS_BOOST", False)
    hits = [
        {
            "id": "a",
            "text": "用户喜欢茶",
            "score": 0.5,
            "rrf_score": 0.5,
            "metadata": {"type": "preference"},
            "created_at": "2024-01-01T00:00:00",
        }
    ]
    ranked = finalize_hybrid_rank("随便问问", hits, max_results=1)
    assert len(ranked) == 1
