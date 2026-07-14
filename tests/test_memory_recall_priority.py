"""Regression tests for memory recall ranking and explicit retain."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from localagent.agent.runtime import (
    _prefetch_personal_context,
    _rewrite_personal_memory_query,
    run_agent_turn,
)
from localagent.memory.core_profile import load_core_profile
from localagent.memory.scoped_recall import _lexical_overlap_score, scoped_recall
from localagent.memory.store import get_memory_store
from localagent.tools import retain_memory


def test_lexical_overlap_prefers_residence_fact_over_diary_noise():
    query = "你知道我住在哪里吗?"
    fact = "用户居住在深圳"
    noise = (
        "### 张杨对代码的一些意见和建议；1. 测试：未规范；"
        "- 要采用unittest，但是我不知道采用unittest的必要性在哪里。"
    )
    assert _lexical_overlap_score(query, fact) > _lexical_overlap_score(query, noise)


def test_scoped_recall_ranks_recent_residence_first(isolated_data):
    store = get_memory_store()
    old = datetime.now() - timedelta(days=180)
    recent = datetime.now()
    store.retain_from_section(
        filename="old.md",
        heading="旧住址",
        text="用户居住在北京",
        chunk_id="old-home",
        extra_metadata={
            "source": "import-chatgpt",
            "recorded_at": old.isoformat(timespec="seconds"),
            "created_at": old.isoformat(timespec="seconds"),
        },
    )
    store.retain_from_section(
        filename="chat.md",
        heading="新住址",
        text="用户居住在深圳",
        chunk_id="new-home",
        extra_metadata={
            "source": "chat",
            "recorded_at": recent.isoformat(timespec="seconds"),
            "created_at": recent.isoformat(timespec="seconds"),
        },
    )
    store.retain_from_section(
        filename="diary.md",
        heading="日记",
        text="人要选择一个适合自己成长的环境，以前在核电站，干了四年，"
        "虽然因为运气的关系，获得的成长机会比其他同事都要多些，但我还是觉得成长不太够，"
        "不是合适的地方。我不知道采用unittest的必要性在哪里。",
        chunk_id="diary",
        extra_metadata={
            "source": "ingest",
            "recorded_at": recent.isoformat(timespec="seconds"),
            "created_at": recent.isoformat(timespec="seconds"),
        },
    )

    hits = scoped_recall("你知道我住在哪里吗?", max_results=5)
    assert hits
    assert "深圳" in hits[0]["text"]
    assert "北京" not in hits[0]["text"]


def test_rewrite_location_query():
    assert "居住" in _rewrite_personal_memory_query("你知道我住在哪里吗?")


def test_prefetch_personal_context_for_location_question():
    with patch(
        "localagent.tools.search_memory",
        return_value="- 用户居住在深圳",
    ) as search:
        ctx = _prefetch_personal_context("你知道我住在哪里吗?")
    assert ctx
    assert "已预加载" in ctx
    assert search.call_count >= 1
    assert any("居住" in str(call) for call in search.call_args_list)


def test_explicit_remember_writes_memory_and_pins_profile(isolated_data):
    result = run_agent_turn("记录一下:我居住在深圳")
    assert "已记住" in result.response
    assert result.tool_calls
    assert result.tool_calls[0]["name"] == "retain_memory"

    hits = scoped_recall("你知道我住在哪里吗?", max_results=3)
    assert hits
    assert any("深圳" in h["text"] for h in hits)

    profile = load_core_profile()
    assert profile.preferences.get("居住地") == "深圳"


def test_scoped_recall_bm25_finds_english_entity_fact(isolated_data):
    store = get_memory_store()
    store.retain_from_section(
        filename="locomo",
        heading="session_2",
        text='[session=2] Caroline said, "I spent the week researching adoption agencies."',
        chunk_id="D2:8",
        extra_metadata={"dia_id": "D2:8", "speaker": "Caroline", "source": "locomo"},
    )
    store.retain_from_section(
        filename="locomo",
        heading="session_14",
        text='[session=14] Melanie said, "I painted flowers yesterday."',
        chunk_id="D14:1",
        extra_metadata={"dia_id": "D14:1", "speaker": "Melanie", "source": "locomo"},
    )
    store.save()

    hits = scoped_recall("What did Caroline research?", max_results=3)
    assert hits
    assert any("adoption agencies" in h["text"] for h in hits)
    assert any((h.get("metadata") or {}).get("dia_id") == "D2:8" for h in hits)


def test_retain_memory_tool(isolated_data):
    msg = retain_memory("我喜欢喝美式咖啡")
    assert "已记住" in msg
    hits = scoped_recall("我喜欢喝什么", max_results=3)
    assert any("美式咖啡" in h["text"] for h in hits)


def test_expand_recall_queries_strips_wh_words():
    from localagent.memory.scoped_recall import expand_recall_queries

    variants = expand_recall_queries("What did Caroline research?")
    assert variants[0] == "What did Caroline research?"
    assert any("research" in v.lower() and "what" not in v.lower().split() for v in variants)


def test_extract_occurred_at_english_locomo_date():
    from localagent.memory.temporal import extract_occurred_at, memory_effective_time

    assert extract_occurred_at("1:56 pm on 8 May, 2023") == "2023-05-08"
    assert extract_occurred_at("May 8, 2023") == "2023-05-08"
    effective = memory_effective_time(
        metadata={"date_time": "7:55 pm on 9 June, 2023"},
        created_at="2099-01-01T00:00:00",
    )
    assert effective.startswith("2023-06-09")


def test_rrf_fuse_hits_prefers_overlap():
    from localagent.memory.scoped_recall import rrf_fuse_hits

    fused = rrf_fuse_hits(
        [
            [{"id": "a", "text": "A", "score": 0.9}, {"id": "b", "text": "B", "score": 0.8}],
            [{"id": "b", "text": "B", "score": 0.7}, {"id": "c", "text": "C", "score": 0.6}],
        ]
    )
    assert fused[0]["id"] == "b"
    assert fused[0]["rrf_score"] > fused[1]["rrf_score"]
