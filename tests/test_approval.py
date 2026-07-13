"""Tool approval / risk classification tests."""

from __future__ import annotations

from unittest.mock import patch

from localagent.tools.approval import (
    classify_shell_command,
    classify_tool,
    format_approval_prompt,
    needs_approval,
    normalize_approval_policy,
    prompt_tool_approval,
)
from localagent.agent.runtime import run_agent_turn


def test_normalize_approval_policy():
    assert normalize_approval_policy("always") == "always"
    assert normalize_approval_policy("dangerous") == "dangerous"
    assert normalize_approval_policy("off") == "off"
    assert normalize_approval_policy("never") == "off"
    assert normalize_approval_policy("weird") == "always"


def test_classify_shell_blocks_rm_rf_root():
    risk = classify_shell_command("rm -rf /")
    assert risk.level == "blocked"
    assert risk.reason


def test_classify_shell_marks_rm_dangerous():
    risk = classify_shell_command("rm -rf ./build")
    assert risk.level == "dangerous"
    assert "删除" in (risk.reason or "")


def test_classify_shell_marks_sudo_dangerous():
    assert classify_shell_command("sudo apt install foo").level == "dangerous"


def test_classify_shell_safe_read():
    assert classify_shell_command("ls -la").level == "safe"
    assert classify_shell_command("find . -name '*.py' | wc -l").level == "safe"


def test_classify_write_file_is_dangerous():
    risk = classify_tool("write_file", {"path": "a.txt", "content": "hello"})
    assert risk.level == "dangerous"
    assert "a.txt" in risk.summary


def test_needs_approval_policy_always():
    risk = classify_shell_command("ls")
    assert needs_approval("run_shell", risk, policy="always")
    assert not needs_approval("run_shell", risk, policy="dangerous")
    assert not needs_approval("run_shell", risk, policy="off")


def test_needs_approval_policy_dangerous():
    risk = classify_shell_command("rm -rf ./tmp")
    assert needs_approval("run_shell", risk, policy="dangerous")
    write_risk = classify_tool("write_file", {"path": "x", "content": "y"})
    assert needs_approval("write_file", write_risk, policy="dangerous")


def test_needs_approval_skips_blocked():
    risk = classify_shell_command("rm -rf /")
    assert risk.level == "blocked"
    assert not needs_approval("run_shell", risk, policy="always")


def test_format_approval_prompt_includes_command():
    risk = classify_shell_command("rm -rf ./tmp")
    text = format_approval_prompt("run_shell", {"command": "rm -rf ./tmp"}, risk)
    assert "rm -rf ./tmp" in text
    assert "风险" in text


def test_prompt_tool_approval_non_tty_denies():
    risk = classify_shell_command("ls")
    with patch("localagent.tools.approval.sys.stdin") as stdin:
        stdin.isatty.return_value = False
        assert prompt_tool_approval("run_shell", {"command": "ls"}, risk) is False


def test_run_agent_turn_requests_approval_and_denies(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.TOOL_APPROVAL", "always")
    tool_reply = (
        '```tool\n{"name": "run_shell", "arguments": '
        '{"command": "echo hello"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [
        tool_reply,
        "已按你的选择跳过该命令。",
    ]
    approvals: list[str] = []

    def deny(name, args, risk):
        approvals.append(name)
        return False

    with patch("localagent.tools.run_shell") as shell:
        result = run_agent_turn(
            "执行 echo",
            provider="ollama",
            on_tool_approve=deny,
        )

    shell.assert_not_called()
    assert approvals == ["run_shell"]
    assert "跳过" in result.response or result.tool_calls


def test_run_agent_turn_approves_and_executes(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.TOOL_APPROVAL", "always")
    tool_reply = (
        '```tool\n{"name": "run_shell", "arguments": '
        '{"command": "echo hello"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [
        tool_reply,
        "命令输出为 hello。",
    ]

    with patch("localagent.tools.run_shell", return_value="hello") as shell:
        result = run_agent_turn(
            "执行 echo",
            provider="ollama",
            on_tool_approve=lambda *_: True,
        )

    shell.assert_called_once()
    assert result.response == "命令输出为 hello。"


def test_run_agent_turn_blocks_without_callback(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.TOOL_APPROVAL", "always")
    tool_reply = (
        '```tool\n{"name": "run_shell", "arguments": '
        '{"command": "echo hello"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [
        tool_reply,
        "当前环境无法确认，已跳过命令。",
    ]

    with patch("localagent.tools.run_shell") as shell:
        result = run_agent_turn("执行 echo", provider="ollama")

    shell.assert_not_called()
    assert result.tool_calls
