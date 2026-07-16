"""E2E safety contracts: hard-block, approval gate, write hallucination, no intent pre-check.

Runs in an isolated LA_DATA_DIR subprocess via a thin Python entry (not full REPL).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

from helpers import PROJECT_ROOT

pytestmark = pytest.mark.e2e


def _run_safety_script(script: str, *, env: dict[str, str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    base = os.environ.copy()
    for key in ("MINIMAX_API_KEY", "OPENROUTER_API_KEY", "CURSOR_API_KEY", "TAVILY_API_KEY"):
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


def test_e2e_safety_blocks_rm_rf_root(la_env):
    script = textwrap.dedent(
        """
        from unittest.mock import patch
        from localagent.tools.shell import run_shell_command
        from localagent.tools.approval import classify_shell_command

        risk = classify_shell_command("rm -rf /")
        assert risk.level == "blocked", risk
        with patch("localagent.tools.shell.subprocess.run") as run:
            out = run_shell_command("rm -rf /")
        run.assert_not_called()
        assert "禁止" in out or "错误" in out
        print("OK_BLOCKED")
        """
    )
    result = _run_safety_script(script, env=la_env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK_BLOCKED" in result.stdout


def test_e2e_safety_agent_blocks_rm_rf_root(la_env):
    script = textwrap.dedent(
        """
        from unittest.mock import MagicMock, patch
        from localagent.agent.runtime import run_agent_turn
        from localagent.audit.events import load_events

        mock = MagicMock()
        mock.chat.side_effect = [
            '```tool\\n{"name": "run_shell", "arguments": {"command": "rm -rf /"}}\\n```',
            "该命令已被安全策略禁止。",
        ]
        mock.provider = "ollama"
        mock.model = "test"
        with patch("localagent.agent.runtime.get_model_router", return_value=mock):
            with patch("localagent.tools.run_shell") as shell:
                run_agent_turn("删除根目录", provider="ollama", session_id="s-e2e-block")
        shell.assert_not_called()
        events = load_events()
        assert any(
            e.get("type") == "tool.decision" and e.get("outcome") == "blocked"
            for e in events
        ), events[-5:]
        print("OK_AGENT_BLOCKED")
        """
    )
    result = _run_safety_script(script, env=la_env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK_AGENT_BLOCKED" in result.stdout


def test_e2e_safety_denies_without_approval_callback(la_env):
    env = {**la_env, "LA_TOOL_APPROVAL": "always"}
    script = textwrap.dedent(
        """
        from unittest.mock import MagicMock, patch
        from localagent.agent.runtime import run_agent_turn

        mock = MagicMock()
        mock.chat.side_effect = [
            '```tool\\n{"name": "run_shell", "arguments": {"command": "echo hello"}}\\n```',
            "当前环境无法确认，已跳过命令。",
        ]
        mock.provider = "ollama"
        mock.model = "test"
        with patch("localagent.agent.runtime.get_model_router", return_value=mock):
            with patch("localagent.tools.run_shell") as shell:
                result = run_agent_turn("执行 echo", provider="ollama", session_id="s-e2e-deny")
        shell.assert_not_called()
        assert result.tool_calls, result
        print("OK_DENIED")
        """
    )
    result = _run_safety_script(script, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK_DENIED" in result.stdout


def test_e2e_safety_write_hallucination_retries(la_env):
    env = {**la_env, "LA_TOOL_APPROVAL": "off"}
    script = textwrap.dedent(
        """
        from unittest.mock import MagicMock, patch
        from localagent.agent.runtime import run_agent_turn

        mock = MagicMock()
        hallucinated = "已为你更新 `tour-note.txt` 文件，当前内容为：跨会话持续性测试"
        tool_reply = (
            '```tool\\n{"name": "write_file", "arguments": '
            '{"path": "tour-note.txt", "content": "跨会话持续性测试"}}\\n```'
        )
        mock.chat.side_effect = [hallucinated, tool_reply, "文件已更新。"]
        mock.provider = "ollama"
        mock.model = "test"
        with patch("localagent.agent.runtime.get_model_router", return_value=mock):
            with patch("localagent.tools.write_file", return_value="ok") as write:
                result = run_agent_turn(
                    "修改 tour-note.txt，写入：跨会话持续性测试",
                    provider="ollama",
                    session_id="s-e2e-halluc",
                )
        assert write.called or "文件" in (result.response or "")
        assert mock.chat.call_count >= 2, mock.chat.call_count
        print("OK_HALLUCINATION_RETRY")
        """
    )
    result = _run_safety_script(script, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK_HALLUCINATION_RETRY" in result.stdout


def test_e2e_safety_no_intent_precheck_before_tools(la_env):
    """PRD §4.4: user input goes straight into the agent tool loop (no clarify gate)."""
    env = {**la_env, "LA_TOOL_APPROVAL": "off"}
    script = textwrap.dedent(
        """
        import json
        from unittest.mock import MagicMock, patch
        from localagent.agent.runtime import run_agent_turn

        mock = MagicMock()
        mock.chat.side_effect = [
            '```tool\\n{"name": "run_shell", "arguments": {"command": "pwd"}}\\n```',
            "当前目录如上。",
        ]
        mock.provider = "ollama"
        mock.model = "test"
        user_msg = "用 shell 执行 pwd"
        with patch("localagent.agent.runtime.get_model_router", return_value=mock):
            with patch("localagent.tools.run_shell", return_value="/tmp"):
                run_agent_turn(user_msg, provider="ollama", session_id="s-e2e-direct")
        assert mock.chat.call_count >= 1
        first_call = mock.chat.call_args_list[0]
        blob = ""
        if first_call.args:
            blob = json.dumps(first_call.args[0], ensure_ascii=False, default=str)
        if first_call.kwargs.get("messages") is not None:
            blob = json.dumps(first_call.kwargs["messages"], ensure_ascii=False, default=str)
        # Some routers pass ChatMessage objects via kwargs
        if not blob and first_call.kwargs:
            blob = json.dumps(first_call.kwargs, ensure_ascii=False, default=str)
        assert "pwd" in blob or user_msg in blob, blob[:500]
        print("OK_DIRECT")
        """
    )
    result = _run_safety_script(script, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK_DIRECT" in result.stdout


def test_e2e_safety_dangerous_prompt_mentions_risk():
    """Tour §7: dangerous ops surface a risk hint in the approval prompt text."""
    from localagent.tools.approval import classify_shell_command, format_approval_prompt

    risk = classify_shell_command("rm -rf ./build")
    assert risk.level == "dangerous"
    text = format_approval_prompt("run_shell", {"command": "rm -rf ./build"}, risk)
    assert "rm -rf ./build" in text
    assert "危险" in text or "风险" in text or "warning" in text.lower() or "潜在" in text
