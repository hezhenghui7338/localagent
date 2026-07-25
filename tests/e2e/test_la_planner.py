"""E2E action planner: milestone mode, session resume, validation linkage."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

from helpers import PROJECT_ROOT

pytestmark = [pytest.mark.e2e, pytest.mark.xdist_group("serial")]


def _run_planner_script(script: str, *, env: dict[str, str], timeout: int = 90) -> subprocess.CompletedProcess[str]:
    base = os.environ.copy()
    for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "CURSOR_API_KEY", "TAVILY_API_KEY"):
        base.pop(key, None)
    base.update(env)
    base["PYTHONPATH"] = str(PROJECT_ROOT / "src") + os.pathsep + base.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-c", script],
        text=True,
        capture_output=True,
        env=base,
        cwd=PROJECT_ROOT,
        timeout=timeout,
    )


@pytest.fixture
def la_env_planner(la_env):
    return {**la_env, "LA_PLANNER_ENABLED": "1", "LA_TOOL_APPROVAL": "off", "LA_VALIDATION_LLM": "0"}


def test_e2e_planner_milestone_multi_step(la_env_planner):
    script = textwrap.dedent(
        """
        import json
        from unittest.mock import MagicMock, patch
        from localagent.agent.planner.state import ActionPlan, Milestone
        from localagent.agent.runtime import run_agent_turn
        from localagent.context.types import ContextBlocks

        plan = ActionPlan(
            goal="find timeout",
            milestones=[
                Milestone(id="m1", objective="grep timeout", done_when="path known"),
            ],
        )
        tool = '```tool\\n{"name": "grep", "arguments": {"pattern": "timeout"}}\\n```'
        calls = {"n": 0}

        def chat_side_effect(messages, **_kwargs):
            calls["n"] += 1
            return tool if calls["n"] == 1 else "timeout 在 config.py 第 10 行"

        mock = MagicMock()
        mock.chat.side_effect = chat_side_effect
        mock.provider = "ollama"
        mock.model = "test"

        with patch("localagent.models.router.get_model_router", return_value=mock):
            with patch("localagent.agent.planner.milestone.plan_milestones", return_value=plan):
                with patch(
                    "localagent.context.engine.fetch_prefetch_blocks",
                    return_value=(ContextBlocks(), {}),
                ):
                    with patch(
                        "localagent.agent.runtime.execute_tool",
                        return_value="config.py:10:timeout=10",
                    ) as exec_tool:
                        result = run_agent_turn(
                            "先 grep timeout 在哪，然后告诉我",
                            provider="ollama",
                            session_id="s-e2e-plan",
                        )
        assert exec_tool.called, "grep tool should run"
        assert result.action_plan is not None, result
        assert "timeout" in (result.response or "").lower() or "config" in (result.response or "").lower()
        print("OK_MILESTONE")
        """
    )
    result = _run_planner_script(script, env=la_env_planner)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK_MILESTONE" in result.stdout


def test_e2e_planner_session_resume(la_env_planner):
    script = textwrap.dedent(
        """
        from unittest.mock import MagicMock, patch
        from localagent.agent.planner.state import ActionPlan, Milestone, PlannerOutcome
        from localagent.agent.runtime import run_agent_turn
        from localagent.context.types import ContextBlocks
        from localagent.persist.session_work import plan_to_work_dict, save_session_work

        sid = "s-e2e-resume"
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

        mock = MagicMock()
        mock.provider = "ollama"
        mock.model = "test"

        with patch("localagent.models.router.get_model_router", return_value=mock):
            with patch(
                "localagent.context.engine.fetch_prefetch_blocks",
                return_value=(ContextBlocks(), {}),
            ):
                with patch("localagent.agent.planner.milestone.plan_milestones") as mock_plan:
                    with patch(
                        "localagent.agent.planner.executor.execute_milestone_plan",
                    ) as mock_exec:
                        mock_exec.return_value = PlannerOutcome(
                            response="b.py 已修改。",
                            tool_calls=[{"name": "edit_file", "arguments": {"path": "b.py"}}],
                            plan=plan,
                            partial=False,
                        )
                        result = run_agent_turn("请继续", provider="ollama", session_id=sid)
        mock_plan.assert_not_called()
        mock_exec.assert_called_once()
        assert result.action_plan is not None
        print("OK_RESUME")
        """
    )
    result = _run_planner_script(script, env=la_env_planner)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK_RESUME" in result.stdout


def test_e2e_planner_validation_blocks_false_done(la_env_planner):
    script = textwrap.dedent(
        """
        from localagent.agent.planner.checker import check_milestone_done
        from localagent.agent.planner.state import Milestone
        from localagent.agent.validation import ValidationResult

        m = Milestone(id="m1", objective="run tests", done_when="测试通过")
        decision = check_milestone_done(
            m,
            tool_calls=[{"name": "run_shell"}],
            last_observation="$ pytest\\nexit: 1\\nstdout:\\nFAILED",
            last_tool_name="run_shell",
            last_validation=ValidationResult.fail("exit", exit_code=1),
            router=None,
        )
        assert not decision.done, decision
        print("OK_VALIDATION_BLOCK")
        """
    )
    result = _run_planner_script(script, env=la_env_planner)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK_VALIDATION_BLOCK" in result.stdout
