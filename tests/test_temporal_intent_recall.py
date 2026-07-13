"""Tests for temporal intent classification and scope-aware recall ranking."""

from __future__ import annotations

from localagent.memory.scoped_recall import (
    _hybrid_weights,
    _intent_temporal_score,
    _scope_alignment_score,
    finalize_hybrid_rank,
    scoped_recall,
)
from localagent.memory.store import get_memory_store
from localagent.memory.temporal_intent import TemporalIntent, parse_temporal_intent


def test_parse_when_event_locomo_style():
    intent = parse_temporal_intent("When did Caroline go to the LGBTQ support group?")
    assert intent.intent_kind == "when_event"
    assert intent.anchor_date is None
    assert intent.prefers_event_neighbors


def test_parse_duration():
    intent = parse_temporal_intent("How long ago was Caroline's 18th birthday?")
    assert intent.intent_kind == "duration"
    assert intent.prefers_event_neighbors


def test_parse_as_of_now():
    intent = parse_temporal_intent("你现在住在哪里？")
    assert intent.intent_kind == "as_of_now"
    assert intent.raises_temporal_weight
    assert intent.anchor_date is not None


def test_parse_english_last_week_with_reference_date():
    intent = parse_temporal_intent(
        "What did I do last week?",
        reference_date="2023-06-15",
    )
    assert intent.intent_kind == "range"
    assert intent.scope_start == "2023-06-05"
    assert intent.scope_end == "2023-06-11"
    assert intent.raises_temporal_weight


def test_parse_english_month_year():
    intent = parse_temporal_intent("What happened in May 2023?")
    assert intent.intent_kind == "range"
    assert intent.scope_start == "2023-05-01"
    assert intent.scope_end == "2023-05-31"


def test_explicit_year_beats_when_wording():
    intent = parse_temporal_intent("When did she move in 2023?")
    assert intent.intent_kind == "range"
    assert intent.scope_start == "2023-01-01"


def test_scope_alignment_in_near_out():
    intent = TemporalIntent(
        intent_kind="range",
        anchor_date="2023-05-15",
        scope_start="2023-05-01",
        scope_end="2023-05-31",
    )
    assert _scope_alignment_score("2023-05-08", intent) == 1.0
    assert _scope_alignment_score("2023-06-10", intent) == 0.5
    assert _scope_alignment_score("2024-01-01", intent) == 0.15


def test_intent_temporal_score_prefers_in_window():
    intent = TemporalIntent(
        intent_kind="range",
        anchor_date="2023-05-15",
        scope_start="2023-05-01",
        scope_end="2023-05-31",
    )
    in_window = _intent_temporal_score(
        effective_at="2023-05-08",
        storage_at="2023-05-08",
        intent=intent,
    )
    out_window = _intent_temporal_score(
        effective_at="2024-12-01",
        storage_at="2024-12-01",
        intent=intent,
    )
    assert in_window > out_window


def test_hybrid_weights_raise_for_range():
    range_w = _hybrid_weights(TemporalIntent(intent_kind="range"))
    when_w = _hybrid_weights(TemporalIntent(intent_kind="when_event"))
    none_w = _hybrid_weights(TemporalIntent(intent_kind="none"))
    assert range_w[3] > when_w[3]
    assert range_w[3] > none_w[3]


def test_scoped_recall_prefers_in_scope_memory(isolated_data):
    store = get_memory_store()
    store.retain_from_section(
        filename="a.md",
        heading="in",
        text="用户在深圳开会讨论产品路线",
        chunk_id="in-scope",
        extra_metadata={"occurred_at": "2023-05-10", "recorded_at": "2023-05-10T12:00:00"},
    )
    store.retain_from_section(
        filename="b.md",
        heading="out",
        text="用户在深圳开会讨论招聘计划",
        chunk_id="out-scope",
        extra_metadata={"occurred_at": "2024-11-01", "recorded_at": "2024-11-01T12:00:00"},
    )
    store.save()

    hits = scoped_recall("2023年5月 深圳开会做了什么", max_results=3)
    assert hits
    assert hits[0]["anchor"]["intent_kind"] == "range"
    assert "产品路线" in hits[0]["text"]
    assert hits[0]["temporal_score"] >= hits[-1]["temporal_score"]


def test_finalize_hybrid_rank_attaches_when_event_intent():
    hits = [
        {
            "id": "1",
            "text": "Caroline said she went to the LGBTQ support group",
            "score": 0.9,
            "rrf_score": 0.03,
            "metadata": {"occurred_at": "2023-05-07", "dia_id": "D1:3"},
            "created_at": "2023-05-07",
        },
        {
            "id": "2",
            "text": "Melanie painted flowers yesterday",
            "score": 0.8,
            "rrf_score": 0.02,
            "metadata": {"occurred_at": "2023-06-01", "dia_id": "D14:1"},
            "created_at": "2023-06-01",
        },
    ]
    ranked = finalize_hybrid_rank(
        "When did Caroline go to the LGBTQ support group?",
        hits,
        max_results=2,
    )
    assert ranked
    assert ranked[0]["anchor"]["intent_kind"] == "when_event"
    assert "Caroline" in ranked[0]["text"]
