"""Tool approval / risk classification tests."""

from __future__ import annotations

from unittest.mock import patch

from localagent.tools.approval import (
    SessionApprovalGate,
    classify_shell_command,
    classify_tool,
    format_approval_prompt,
    needs_approval,
    normalize_approval_policy,
    prompt_tool_approval,
)
from localagent.agent.runtime import run_agent_turn
from localagent.tools.action_receipt import (
    append_action_receipt,
    format_action_receipt,
    record_side_effect,
)


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
    assert "命令输出为 hello。" in result.response
    assert "【Action receipt】" in result.response
    assert "run_shell" in result.response
    assert "echo hello" in result.response


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


def test_session_gate_remembers_safe_only():
    gate = SessionApprovalGate()
    safe = classify_shell_command("ls -la")
    dangerous = classify_shell_command("rm -rf ./tmp")
    gate.remember("run_shell", safe)
    gate.remember("run_shell", dangerous)
    assert gate.is_preapproved("run_shell", safe)
    assert not gate.is_preapproved("run_shell", dangerous)


def test_prompt_approve_once_remembers_safe(monkeypatch):
    gate = SessionApprovalGate()
    risk = classify_shell_command("ls")
    with patch("localagent.tools.approval.sys.stdin") as stdin:
        stdin.isatty.return_value = True
        monkeypatch.setattr("builtins.input", lambda *_: "a")
        assert prompt_tool_approval(
            "run_shell", {"command": "ls"}, risk, session_gate=gate
        )
    assert gate.is_preapproved("run_shell", risk)


def test_prompt_approve_once_not_offered_for_dangerous(monkeypatch):
    gate = SessionApprovalGate()
    risk = classify_shell_command("rm -rf ./tmp")
    with patch("localagent.tools.approval.sys.stdin") as stdin:
        stdin.isatty.return_value = True
        answers = iter(["a", "y"])

        def _input(_prompt=""):
            return next(answers)

        monkeypatch.setattr("builtins.input", _input)
        # First answer "a" is ignored for dangerous → falls through to default False
        # unless we answer y. Simulate: user types a then we need second prompt.
        # For dangerous, "a" is not accepted → returns default False.
        assert (
            prompt_tool_approval(
                "run_shell",
                {"command": "rm -rf ./tmp"},
                risk,
                session_gate=gate,
            )
            is False
        )
    assert not gate.is_preapproved("run_shell", risk)


def test_run_agent_turn_session_preapproved_skips_prompt(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.TOOL_APPROVAL", "always")
    gate = SessionApprovalGate()
    safe = classify_shell_command("echo hello")
    gate.remember("run_shell", safe)

    tool_reply = (
        '```tool\n{"name": "run_shell", "arguments": '
        '{"command": "echo hello"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [
        tool_reply,
        "命令输出为 hello。",
    ]
    approvals: list[str] = []

    def ask(name, args, risk):
        approvals.append(name)
        return True

    with patch("localagent.tools.run_shell", return_value="hello") as shell:
        result = run_agent_turn(
            "执行 echo",
            provider="ollama",
            on_tool_approve=ask,
            session_approval=gate,
        )

    shell.assert_called_once()
    assert approvals == []
    assert "【Action receipt】" in result.response


def test_action_receipt_helpers():
    item = record_side_effect(
        "write_file",
        {"path": "notes.md", "content": "hi", "mode": "overwrite"},
        outcome="executed",
    )
    assert item is not None
    receipt = format_action_receipt([item])
    assert receipt and "write_file" in receipt and "notes.md" in receipt
    text = append_action_receipt("已写好。", [item])
    assert text.endswith(receipt)
    assert record_side_effect("web_search", {"query": "x"}, outcome="executed") is None
