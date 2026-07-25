"""Tests for unified turn intent routing."""

from __future__ import annotations

from localagent.agent.intent_route import (
    TurnIntent,
    classify_turn_intent,
    explicit_remember_content,
)
from localagent.agent.planner.state import ActionPlan, Milestone
from localagent.persist.session_work import plan_to_work_dict, save_session_work


def test_explicit_remember_content():
    assert explicit_remember_content("记住：我喜欢 Rust") == "我喜欢 Rust"
    assert explicit_remember_content("Please remember that I use vim") == "I use vim"
    assert explicit_remember_content("今天天气") is None


def test_classify_remember():
    intent = classify_turn_intent("记下：明天开会")
    assert intent.kind == "remember"
    assert intent.remember_content == "明天开会"


def test_classify_continue(isolated_data):
    sid = "s-intent-continue"
    plan = ActionPlan(
        goal="任务",
        milestones=[
            Milestone(id="m1", objective="一步", done_when="ok", status="done"),
            Milestone(id="m2", objective="二步", done_when="ok", status="pending"),
        ],
    )
    save_session_work(
        sid,
        {"active_plan": plan_to_work_dict(plan, partial=True), "last_tool_targets": []},
    )
    intent = classify_turn_intent("请继续", session_id=sid)
    assert intent.kind == "continue"
    assert intent.use_milestone_planner is True
    assert intent.resume_plan is not None


def test_classify_action_milestone():
    intent = classify_turn_intent("先找到 config.py 然后修改 timeout 再跑测试")
    assert intent.kind == "action_milestone"
    assert intent.use_milestone_planner is True


def test_classify_action_simple():
    intent = classify_turn_intent("帮我读一下 README.md")
    assert intent.kind == "action_simple"
    assert intent.use_milestone_planner is False


def test_classify_qa():
    intent = classify_turn_intent("你好")
    assert intent.kind == "qa"
