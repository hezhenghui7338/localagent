"""Tests for the lightweight action planner."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from localagent.agent.planner.checker import (
    check_milestone_done,
    milestone_done_heuristic,
    observation_suggests_replan,
)
from localagent.agent.planner.complexity import action_complexity_score, should_use_milestone_mode
from localagent.agent.planner.executor import execute_milestone_plan
from localagent.agent.planner.milestone import parse_revised_milestones, plan_milestones, verify_plan
from localagent.agent.planner.replan import replan_remaining
from localagent.agent.planner.state import ActionPlan, Milestone
from localagent.agent.planner.tools_route import route_action_tools
from localagent.agent.react_loop import ReactLoopResult, run_react_loop
from localagent.agent.validation import ValidationResult
from localagent.models.router import ChatMessage


def test_action_complexity_score_multi_step():
    msg = "先找到 config.py 里的 timeout，然后改成 30，再跑测试"
    assert action_complexity_score(msg) >= 2
    assert should_use_milestone_mode(msg)


def test_action_complexity_score_simple_chat():
    assert action_complexity_score("你好") == 0
    assert not should_use_milestone_mode("你好")


def test_action_complexity_score_memory_recall_skipped():
    assert not should_use_milestone_mode("我上次问过什么关于记忆的事吗")


def test_verify_plan_rejects_blocked_intent():
    plan = ActionPlan(
        goal="destructive",
        milestones=[Milestone(id="m1", objective="delete all", done_when="done")],
    )
    ok, reason = verify_plan(plan, "rm -rf /")
    assert not ok
    assert reason == "blocked_intent"


def test_verify_plan_accepts_valid():
    plan = ActionPlan(
        goal="edit config",
        milestones=[
            Milestone(id="m1", objective="locate config", done_when="path known"),
            Milestone(id="m2", objective="edit timeout", done_when="file changed"),
        ],
    )
    ok, _ = verify_plan(plan, "改 config 里的 timeout")
    assert ok


def test_parse_revised_milestones():
    raw = json.dumps(
        {
            "status": "revise",
            "milestones": [
                {"id": "m2", "objective": "retry with glob", "done_when": "found"},
            ],
        }
    )
    items = parse_revised_milestones(raw, start_id=2)
    assert len(items) == 1
    assert items[0].objective == "retry with glob"


def test_plan_milestones_parses_json(isolated_data):
    payload = json.dumps(
        {
            "mode": "milestone",
            "goal": "update timeout",
            "milestones": [
                {"id": "m1", "objective": "find config", "done_when": "path known"},
                {"id": "m2", "objective": "set timeout=30", "done_when": "saved"},
            ],
        }
    )
    isolated_data["router"].chat.return_value = payload
    plan = plan_milestones("找 config 然后改 timeout 为 30")
    assert plan is not None
    assert len(plan.milestones) == 2
    assert plan.goal == "update timeout"


def test_route_action_tools_prefers_file_tools():
    tools = route_action_tools("read config.py and edit timeout", top_k=5)
    names = {t["name"] for t in tools}
    assert "read_file" in names
    assert "edit_file" in names or "write_file" in names


def test_milestone_done_heuristic_write_file():
    m = Milestone(id="m1", objective="write", done_when="file saved")
    assert milestone_done_heuristic(
        m,
        tool_calls=[{"name": "write_file"}],
        last_observation="已写入文件: test.txt",
        last_tool_name="write_file",
        last_validation=ValidationResult.ok(readback_ok=True),
    )


def test_milestone_done_heuristic_shell_fail_validation():
    m = Milestone(id="m1", objective="test", done_when="测试通过")
    assert not milestone_done_heuristic(
        m,
        tool_calls=[{"name": "run_shell"}],
        last_observation="$ pytest\nexit: 1",
        last_tool_name="run_shell",
        last_validation=ValidationResult.fail("exit", exit_code=1),
    )


def test_check_milestone_done_llm_rejects_weak_heuristic(monkeypatch):
    monkeypatch.setattr("localagent.config.VALIDATION_LLM", True)
    monkeypatch.setattr("localagent.config.VALIDATION_LLM_MAX", 2)
    router = MagicMock()
    router.chat.return_value = '{"done": false, "reason": "仅找到路径，尚未修改文件"}'
    m = Milestone(id="m1", objective="修改 timeout", done_when="文件已修改")
    decision = check_milestone_done(
        m,
        tool_calls=[{"name": "grep"}],
        last_observation="config.py:10:timeout=10",
        last_tool_name="grep",
        last_validation=ValidationResult.ok(),
        router=router,
    )
    assert not decision.done
    assert decision.source == "llm"
    assert decision.llm_rejected
    router.chat.assert_called_once()


def test_check_milestone_done_llm_confirms_borderline(monkeypatch):
    monkeypatch.setattr("localagent.config.VALIDATION_LLM", True)
    monkeypatch.setattr("localagent.config.VALIDATION_LLM_MAX", 1)
    router = MagicMock()
    router.chat.return_value = '{"done": true, "reason": "已定位到 config.py 中的 timeout"}'
    m = Milestone(id="m1", objective="定位 timeout", done_when="已知路径与当前值")
    decision = check_milestone_done(
        m,
        tool_calls=[{"name": "grep"}],
        last_observation="config.py:10:timeout=10",
        last_tool_name="grep",
        last_validation=ValidationResult.ok(),
        router=router,
    )
    assert decision.done
    assert decision.source == "llm"
    router.chat.assert_called_once()


def test_check_milestone_done_skips_llm_when_heuristic_confident(monkeypatch):
    monkeypatch.setattr("localagent.config.VALIDATION_LLM", True)
    router = MagicMock()
    m = Milestone(id="m1", objective="write", done_when="file saved")
    decision = check_milestone_done(
        m,
        tool_calls=[{"name": "write_file"}],
        last_observation="已写入文件: test.txt",
        last_tool_name="write_file",
        last_validation=ValidationResult.ok(readback_ok=True),
        router=router,
    )
    assert decision.done
    assert decision.source == "heuristic"
    router.chat.assert_not_called()


def test_check_milestone_done_respects_semantic_budget(monkeypatch):
    monkeypatch.setattr("localagent.config.VALIDATION_LLM", True)
    monkeypatch.setattr("localagent.config.VALIDATION_LLM_MAX", 1)
    router = MagicMock()
    m = Milestone(id="m1", objective="修改", done_when="文件已修改")
    decision = check_milestone_done(
        m,
        tool_calls=[{"name": "grep"}],
        last_observation="config.py:10:timeout=10",
        last_tool_name="grep",
        router=router,
        semantic_calls=1,
    )
    assert not decision.done
    assert decision.source == "heuristic"
    router.chat.assert_not_called()


def test_observation_suggests_replan():
    assert observation_suggests_replan("错误: 文件不存在: foo.py")
    assert not observation_suggests_replan("已写入文件: ok.txt")


def test_run_react_loop_repeat_call_breaker(isolated_data):
    tool = '```tool\n{"name": "grep", "arguments": {"pattern": "timeout"}}\n```'
    isolated_data["router"].chat.side_effect = [tool, tool, tool, "找到 timeout=10"]
    messages = [ChatMessage(role="user", content="find timeout")]

    result = run_react_loop(
        messages=messages,
        user_message="find timeout",
        router=isolated_data["router"],
        prefer="ollama",
        session_id="s1",
        max_iterations=5,
        on_status=None,
        on_token=None,
        gated_execute=lambda name, args: "src/config.py:10:timeout=10",
    )

    assert result.repeat_breaker or result.response


def test_run_agent_turn_milestone_mode(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.PLANNER_ENABLED", True)
    plan_json = json.dumps(
        {
            "mode": "milestone",
            "goal": "update timeout",
            "milestones": [
                {"id": "m1", "objective": "grep timeout", "done_when": "path known"},
            ],
        }
    )
    tool = '```tool\n{"name": "grep", "arguments": {"pattern": "timeout"}}\n```'

    call_count = {"n": 0}

    def chat_side_effect(messages, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return plan_json
        return tool if call_count["n"] == 2 else "timeout 在 config.py 第 10 行"

    isolated_data["router"].chat.side_effect = chat_side_effect

    from localagent.agent.runtime import run_agent_turn
    from localagent.context.types import ContextBlocks

    with (
        patch(
            "localagent.context.engine.fetch_prefetch_blocks",
            return_value=(ContextBlocks(), {}),
        ),
        patch(
            "localagent.tools.execute_tool",
            return_value="config.py:10:timeout=10",
        ),
    ):
        result = run_agent_turn(
            "先 grep timeout 在哪，然后告诉我位置",
            provider="ollama",
        )

    assert "timeout" in result.response.lower() or "config" in result.response.lower()
    assert result.action_plan is not None


def test_run_agent_turn_resumes_session_work_plan(isolated_data):
    from localagent.agent.planner.state import PlannerOutcome
    from localagent.agent.runtime import run_agent_turn
    from localagent.context.types import ContextBlocks
    from localagent.persist.session_work import plan_to_work_dict, save_session_work

    sid = "s-resume-turn"
    plan = ActionPlan(
        goal="改两个文件",
        milestones=[
            Milestone(id="m1", objective="读 a.py", done_when="已知", status="done"),
            Milestone(id="m2", objective="改 b.py", done_when="已修改", status="pending"),
        ],
    )
    save_session_work(
        sid,
        {"active_plan": plan_to_work_dict(plan, partial=True), "last_tool_targets": ["b.py"]},
    )

    with (
        patch(
            "localagent.context.engine.fetch_prefetch_blocks",
            return_value=(ContextBlocks(), {}),
        ),
        patch("localagent.agent.planner.milestone.plan_milestones") as mock_plan,
        patch("localagent.agent.planner.executor.execute_milestone_plan") as mock_exec,
    ):
        mock_exec.return_value = PlannerOutcome(
            response="b.py 已修改。",
            tool_calls=[{"name": "edit_file", "arguments": {"path": "b.py"}}],
            plan=plan,
            partial=False,
        )
        result = run_agent_turn("请继续", provider="ollama", session_id=sid)

    mock_plan.assert_not_called()
    mock_exec.assert_called_once()
    assert result.response
    assert result.action_plan is not None


def _success_loop_result(**overrides) -> ReactLoopResult:
    base = ReactLoopResult(
        response="步骤完成",
        tool_calls=[{"name": "write_file", "arguments": {"path": "test.txt"}}],
        last_observation="已写入文件: test.txt",
        last_tool_name="write_file",
        last_validation=ValidationResult.ok(readback_ok=True),
    )
    for key, val in overrides.items():
        setattr(base, key, val)
    return base


def test_execute_milestone_plan_completes_two_steps(isolated_data):
    plan = ActionPlan(
        goal="two-step task",
        milestones=[
            Milestone(id="m1", objective="write a", done_when="file saved", status="pending"),
            Milestone(id="m2", objective="write b", done_when="file saved", status="pending"),
        ],
    )
    router = isolated_data["router"]

    with patch("localagent.agent.planner.executor.run_react_loop") as mock_loop:
        mock_loop.side_effect = [_success_loop_result(), _success_loop_result()]
        outcome = execute_milestone_plan(
            plan,
            user_message="write two files",
            base_messages=[ChatMessage(role="user", content="write two files")],
            router=router,
            prefer="ollama",
            session_id="s-exec",
            on_status=None,
            on_token=None,
            gated_execute=lambda name, args: "ok",
            rebuild_system=lambda **kwargs: "SYS",
        )

    assert mock_loop.call_count == 2
    assert all(m.status == "done" for m in plan.milestones)
    assert not outcome.partial


def test_execute_milestone_plan_partial_on_budget_exhausted(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.PLANNER_MAX_MILESTONES", 1)
    monkeypatch.setattr("localagent.config.PLANNER_STEPS_PER_MILESTONE", 1)

    plan = ActionPlan(
        goal="budget test",
        milestones=[
            Milestone(id="m1", objective="step one", done_when="ok", status="pending"),
            Milestone(id="m2", objective="step two", done_when="ok", status="pending"),
        ],
    )
    router = isolated_data["router"]

    with patch("localagent.agent.planner.executor.run_react_loop") as mock_loop:
        mock_loop.return_value = _success_loop_result()
        outcome = execute_milestone_plan(
            plan,
            user_message="multi step",
            base_messages=[ChatMessage(role="user", content="multi step")],
            router=router,
            prefer="ollama",
            session_id="s-budget",
            on_status=None,
            on_token=None,
            gated_execute=lambda name, args: "ok",
            rebuild_system=lambda **kwargs: "SYS",
        )

    assert plan.milestones[0].status == "done"
    assert plan.milestones[1].status == "pending"
    assert outcome.partial


def test_execute_milestone_plan_triggers_replan(isolated_data):
    plan = ActionPlan(
        goal="find file",
        milestones=[
            Milestone(id="m1", objective="read missing", done_when="content known", status="pending"),
        ],
    )
    revised = [Milestone(id="m2", objective="glob search", done_when="found", status="pending")]
    fail_loop = ReactLoopResult(
        response="",
        tool_calls=[{"name": "read_file"}],
        last_observation="错误: 文件不存在: foo.py",
        last_tool_name="read_file",
        last_validation=ValidationResult.fail("missing"),
    )
    router = isolated_data["router"]

    with (
        patch("localagent.agent.planner.executor.run_react_loop") as mock_loop,
        patch("localagent.agent.planner.executor.replan_remaining", return_value=revised) as mock_replan,
    ):
        mock_loop.side_effect = [fail_loop, _success_loop_result()]
        outcome = execute_milestone_plan(
            plan,
            user_message="read foo.py",
            base_messages=[ChatMessage(role="user", content="read foo.py")],
            router=router,
            prefer="ollama",
            session_id="s-replan",
            on_status=None,
            on_token=None,
            gated_execute=lambda name, args: "err",
            rebuild_system=lambda **kwargs: "SYS",
        )

    mock_replan.assert_called_once()
    assert len(plan.milestones) == 1
    assert plan.milestones[0].objective == "glob search"
    assert plan.milestones[0].status == "done"
    assert not outcome.partial


def test_execute_milestone_plan_replan_failure_marks_partial(isolated_data):
    plan = ActionPlan(
        goal="find file",
        milestones=[
            Milestone(id="m1", objective="read missing", done_when="content known", status="pending"),
        ],
    )
    fail_loop = ReactLoopResult(
        response="无法读取",
        tool_calls=[{"name": "read_file"}],
        last_observation="错误: 文件不存在: foo.py",
        last_tool_name="read_file",
        last_validation=ValidationResult.fail("missing"),
        exhausted=True,
    )
    router = isolated_data["router"]

    with (
        patch("localagent.agent.planner.executor.run_react_loop", return_value=fail_loop),
        patch("localagent.agent.planner.executor.replan_remaining", return_value=None),
    ):
        outcome = execute_milestone_plan(
            plan,
            user_message="read foo.py",
            base_messages=[ChatMessage(role="user", content="read foo.py")],
            router=router,
            prefer="ollama",
            session_id="s-replan-fail",
            on_status=None,
            on_token=None,
            gated_execute=lambda name, args: "err",
            rebuild_system=lambda **kwargs: "SYS",
        )

    assert plan.milestones[0].status == "failed"
    assert outcome.partial


def test_replan_remaining_parses_json(isolated_data):
    plan = ActionPlan(
        goal="fix config",
        milestones=[
            Milestone(id="m1", objective="read config", done_when="ok", status="failed"),
        ],
    )
    current = plan.milestones[0]
    payload = json.dumps(
        {
            "status": "revise",
            "milestones": [{"id": "m2", "objective": "glob config", "done_when": "found"}],
        }
    )
    isolated_data["router"].chat.return_value = payload

    with patch("localagent.models.router.get_model_router", return_value=isolated_data["router"]):
        revised = replan_remaining(
            plan,
            user_message="fix timeout",
            current=current,
            last_observation="错误: 文件不存在",
        )

    assert revised is not None
    assert len(revised) == 1
    assert revised[0].objective == "glob config"
    assert plan.replans_used == 1


def test_replan_remaining_respects_max_replan(monkeypatch, isolated_data):
    monkeypatch.setattr("localagent.config.PLANNER_MAX_REPLAN", 1)
    plan = ActionPlan(
        goal="task",
        milestones=[Milestone(id="m1", objective="step", done_when="ok", status="failed")],
        replans_used=1,
    )
    result = replan_remaining(
        plan,
        user_message="continue",
        current=plan.milestones[0],
        last_observation="failed",
    )
    assert result is None
    isolated_data["router"].chat.assert_not_called()
