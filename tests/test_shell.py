"""Shell tool tests."""

from __future__ import annotations

from pathlib import Path

from localagent.tools import execute_tool
from localagent.tools.shell import run_shell_command


def test_run_shell_command_echo(tmp_path: Path):
    result = run_shell_command("echo hello", cwd=tmp_path)
    assert "hello" in result
    assert "stdout:" in result
    assert str(tmp_path) in result


def test_run_shell_command_empty(monkeypatch):
    from localagent.i18n import reset_lang_cache

    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    assert "不能为空" in run_shell_command("   ")


def test_run_shell_command_blocks_rm_rf_root(monkeypatch):
    from localagent.i18n import reset_lang_cache

    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    result = run_shell_command("rm -rf /")
    assert "禁止" in result


def test_run_shell_command_timeout(tmp_path: Path, monkeypatch):
    from localagent.i18n import reset_lang_cache

    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    result = run_shell_command("sleep 5", cwd=tmp_path, timeout=0.2)
    assert "超时" in result


def test_execute_tool_run_shell(tmp_path: Path):
    result = execute_tool("run_shell", {"command": "pwd", "cwd": str(tmp_path)})
    assert str(tmp_path) in result


def test_parse_run_shell_tool_call():
    from localagent.agent.runtime import _parse_tool_call

    text = '```tool\n{"name": "run_shell", "arguments": {"command": "wc -l *.py"}}\n```'
    assert _parse_tool_call(text) == {
        "name": "run_shell",
        "arguments": {"command": "wc -l *.py"},
    }
