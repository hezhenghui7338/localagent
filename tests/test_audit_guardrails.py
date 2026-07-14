"""Guardrail interception tests: harmful actions must not execute and must be audited."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from localagent.agent.runtime import run_agent_turn
from localagent.audit.events import aggregate_behavior, load_events
from localagent.audit.report import generate_report, print_audit_summary
from localagent.audit.security import is_sensitive_path, run_security_scan
from localagent.ingest.add_file import SensitiveIngestError, prepare_symlink
from localagent.ingest.pipeline import IngestStatus, ingest_file
from localagent.tools.approval import classify_shell_command, classify_tool
from localagent.tools.shell import run_shell_command


@pytest.mark.parametrize(
    "command,reason_substr",
    [
        ("rm -rf /", "根目录"),
        ("rm -rf /*", "根目录"),
        ("mkfs.ext4 /dev/sda1", "格式化"),
        ("dd if=/dev/zero of=/dev/sda", "块设备"),
        (":(){ :|:& };:", "fork"),
    ],
)
def test_classify_blocks_destructive_commands(command: str, reason_substr: str):
    risk = classify_shell_command(command)
    assert risk.level == "blocked"
    assert reason_substr in (risk.reason or "")


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf ./build",
        "sudo apt install foo",
        "git push --force origin main",
        "chmod 777 /tmp/x",
    ],
)
def test_classify_marks_dangerous_but_not_blocked(command: str):
    risk = classify_shell_command(command)
    assert risk.level == "dangerous"


def test_run_shell_never_executes_blocked_command(isolated_data):
    with patch("localagent.tools.shell.subprocess.run") as run:
        out = run_shell_command("rm -rf /")
    run.assert_not_called()
    assert "禁止" in out or "错误" in out


def test_agent_blocks_rm_rf_root_without_executing(isolated_data, monkeypatch):
    tool_reply = (
        '```tool\n{"name": "run_shell", "arguments": '
        '{"command": "rm -rf /"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [
        tool_reply,
        "该命令已被安全策略禁止。",
    ]
    with patch("localagent.tools.run_shell") as shell:
        result = run_agent_turn("删除根目录", provider="ollama", session_id="s-block")

    shell.assert_not_called()
    assert result.tool_calls
    events = load_events()
    blocked = [e for e in events if e.get("type") == "tool.decision" and e.get("outcome") == "blocked"]
    assert blocked
    assert blocked[0]["tool"] == "run_shell"
    assert any(e.get("type") == "guardrail.triggered" for e in events)


def test_agent_denies_dangerous_rm_and_logs(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.TOOL_APPROVAL", "dangerous")
    tool_reply = (
        '```tool\n{"name": "run_shell", "arguments": '
        '{"command": "rm -rf ./build"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [
        tool_reply,
        "已跳过删除。",
    ]

    def deny(_name, _args, _risk):
        return False

    with patch("localagent.tools.run_shell") as shell:
        run_agent_turn(
            "删掉 build",
            provider="ollama",
            session_id="s-deny",
            on_tool_approve=deny,
        )

    shell.assert_not_called()
    events = load_events()
    denied = [e for e in events if e.get("outcome") == "denied"]
    asked = [e for e in events if e.get("outcome") == "asked"]
    assert asked
    assert denied


def test_agent_executes_safe_shell_when_approval_off(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.TOOL_APPROVAL", "off")
    tool_reply = (
        '```tool\n{"name": "run_shell", "arguments": '
        '{"command": "pwd"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [
        tool_reply,
        "当前目录如上。",
    ]
    with patch("localagent.tools.run_shell", return_value="/tmp") as shell:
        run_agent_turn("看一下目录", provider="ollama", session_id="s-safe")

    shell.assert_called_once()
    executed = [e for e in load_events() if e.get("outcome") == "executed"]
    assert executed
    assert executed[0]["tool"] == "run_shell"


def test_write_file_is_dangerous(isolated_data):
    risk = classify_tool("write_file", {"path": "/etc/passwd", "content": "x"})
    assert risk.level == "dangerous"


def test_prepare_symlink_blocks_env_file(tmp_path: Path, isolated_data):
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=1\n", encoding="utf-8")
    with pytest.raises(SensitiveIngestError):
        prepare_symlink(env_file)
    assert not (isolated_data["kb_dir"] / ".env").exists()
    events = load_events()
    assert any(e.get("type") == "kb.blocked" for e in events)
    assert any(e.get("type") == "guardrail.triggered" for e in events)


def test_prepare_symlink_blocks_pem(tmp_path: Path, isolated_data):
    pem = tmp_path / "server.pem"
    pem.write_text("-----BEGIN CERTIFICATE-----\nX\n", encoding="utf-8")
    with pytest.raises(SensitiveIngestError):
        prepare_symlink(pem)


def test_ingest_file_blocks_sensitive_even_if_already_in_kb(tmp_path: Path, isolated_data):
    secret = tmp_path / "id_rsa"
    secret.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nxxx\n", encoding="utf-8")
    link = isolated_data["kb_dir"] / "id_rsa"
    link.symlink_to(secret)
    assert is_sensitive_path(link)

    result = ingest_file(link)
    assert result.status == IngestStatus.FAILED
    assert "敏感" in result.error
    assert any(e.get("type") == "kb.blocked" for e in load_events())


def test_security_scan_still_flags_existing_env_symlink(tmp_path: Path, isolated_data):
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=abc\n", encoding="utf-8")
    link = isolated_data["kb_dir"] / ".env"
    link.symlink_to(env_file)
    report = run_security_scan()
    assert report.high_count >= 1


def test_audit_report_includes_blocked_behavior(isolated_data, monkeypatch):
    tool_reply = (
        '```tool\n{"name": "run_shell", "arguments": '
        '{"command": "mkfs.ext4 /dev/sda"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [
        tool_reply,
        "已拦截。",
    ]
    with patch("localagent.tools.run_shell"):
        run_agent_turn("格式化磁盘", provider="ollama")

    behavior = aggregate_behavior(load_events())
    assert behavior["outcomes"].get("blocked", 0) >= 1
    assert behavior["guardrail_triggers"] >= 1

    md = generate_report(include_workspace=False)
    assert "Agent 行为与护栏" in md
    assert "本周期拦截" in md

    summary = print_audit_summary()
    assert "护栏=" in summary
    assert "blocked=" in summary
