"""Phase C tests: reflect hop planning + consolidation parsing/apply."""

from __future__ import annotations

from unittest.mock import MagicMock

from localagent.memory.consolidate import (
    ConsolidationAction,
    _apply_action,
    _parse_action,
    consolidate_candidates,
)
from localagent.memory.reflect_loop import _parse_hop_decision, reflect_with_hops
from localagent.memory.store import get_memory_store


def test_parse_hop_decision_ready():
    ready, queries = _parse_hop_decision('{"status":"ready","queries":[]}')
    assert ready is True
    assert queries == []


def test_parse_hop_decision_need():
    ready, queries = _parse_hop_decision(
        '{"status":"need","queries":["Caroline painting","Melanie trip"]}'
    )
    assert ready is False
    assert queries == ["Caroline painting", "Melanie trip"]


def test_reflect_with_hops_followup(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_REFLECT_MAX_HOPS", 1)
    monkeypatch.setattr("localagent.config.MEMORY_REFLECT_TOP_K", 3)

    backend = MagicMock()
    backend.recall.side_effect = [
        [{"id": "a", "text": "Caroline likes painting"}],
        [{"id": "b", "text": "Melanie visited Paris"}],
    ]

    decisions = iter(
        [
            (False, ["Melanie trip"]),  # after first hop → need more
            (True, []),
        ]
    )

    def fake_decide(query, hits):
        return next(decisions)

    monkeypatch.setattr(
        "localagent.memory.reflect_loop._decide_followups",
        fake_decide,
    )
    monkeypatch.setattr(
        "localagent.memory.reflect_loop._recall_knowledge",
        lambda query, top_k: [],
    )
    monkeypatch.setattr(
        "localagent.memory.reflect_loop._synthesize",
        lambda query, hits: f"answer:{len(hits)}",
    )

    out = reflect_with_hops(backend, "What about Caroline and Melanie?")
    assert out == "answer:2"
    assert backend.recall.call_count == 2


def test_reflect_with_hops_queries_knowledge(monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_REFLECT_MAX_HOPS", 0)
    monkeypatch.setattr("localagent.config.MEMORY_REFLECT_TOP_K", 3)

    backend = MagicMock()
    backend.recall.return_value = [{"id": "m1", "text": "memory fact"}]

    monkeypatch.setattr(
        "localagent.memory.reflect_loop._recall_knowledge",
        lambda query, top_k: [{"id": "k1", "text": "kb fact", "source": "knowledge"}],
    )

    captured: list[dict] = []

    def fake_synthesize(query, hits):
        captured.extend(hits)
        return "ok"

    monkeypatch.setattr(
        "localagent.memory.reflect_loop._synthesize",
        fake_synthesize,
    )

    out = reflect_with_hops(backend, "status?")
    assert out == "ok"
    assert any(h.get("id") == "m1" for h in captured)
    assert any(h.get("id") == "k1" for h in captured)
    assert backend.recall.call_count == 1


def test_parse_consolidation_action():
    action = _parse_action(
        '{"op":"UPDATE","target_id":"abc","text":"用户住在深圳","reason":"搬家"}',
        fallback_text="用户住在深圳",
    )
    assert action.op == "UPDATE"
    assert action.target_id == "abc"
    assert "深圳" in action.text


def test_apply_update_replaces_fact(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_CONSOLIDATE", True)
    from localagent.memory.backend import get_memory_backend
    from localagent.memory.consolidate import ConsolidationReport

    backend = get_memory_backend()
    old_id = backend.retain("用户居住在北京", metadata={"source": "chat"})
    assert old_id
    report = ConsolidationReport()
    _apply_action(
        backend,
        ConsolidationAction(
            op="UPDATE",
            text="用户居住在深圳",
            target_id=old_id,
            reason="搬家",
        ),
        metadata={"source": "consolidate"},
        report=report,
    )
    assert old_id in report.deleted_ids
    assert report.updated_ids
    texts = [f.text for f in get_memory_store().all_facts()]
    assert any("深圳" in t for t in texts)
    assert not any(t == "用户居住在北京" for t in texts)


def test_consolidate_disabled_just_adds(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_CONSOLIDATE", False)
    report = consolidate_candidates(
        ["用户喜欢喝咖啡"],
        metadata={"source": "test"},
        already_retained=False,
    )
    assert len(report.retained_ids) == 1
    assert report.actions[0].op == "ADD"
