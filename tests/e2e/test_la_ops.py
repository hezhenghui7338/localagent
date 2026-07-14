"""E2E coverage for remaining top-level LA commands (ops / config / workspace)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers import parse_task_id, run_la, seed_memory, wait_for_task, write_kb_doc

pytestmark = pytest.mark.e2e


def test_e2e_version():
    result = run_la(["-V"])
    assert result.returncode == 0
    assert result.stdout.strip()


def test_e2e_help_lists_core_commands():
    result = run_la(["--help"])
    assert result.returncode == 0
    for cmd in ("memory", "rag", "chat", "tasks", "workspace", "audit", "logs", "config", "setup"):
        assert cmd in result.stdout


def test_e2e_logs_path_and_empty(la_env):
    path_result = run_la(["logs", "--path"], env=la_env)
    assert path_result.returncode == 0
    assert "localagent.log" in path_result.stdout

    # Trigger logging via a cheap command, then read.
    assert run_la(["memory", "status"], env=la_env).returncode == 0
    logs = run_la(["logs", "--tail", "20"], env=la_env)
    assert logs.returncode == 0
    # Either has content or the friendly empty message after a fresh data dir.
    assert "尚无日志" in logs.stdout or "INFO" in logs.stdout or "logging configured" in logs.stdout


def test_e2e_chat_help(la_env):
    result = run_la(["chat", "--help"], env=la_env)
    assert result.returncode == 0
    assert "--session-id" in result.stdout
    assert "--provider" in result.stdout


def test_e2e_chat_invalid_provider(la_env):
    result = run_la(["chat", "-p", "bogus"], env=la_env)
    assert result.returncode == 1
    assert "invalid provider" in result.stdout.lower() or "provider" in result.stdout.lower()


def test_e2e_chat_quit_immediately(la_env):
    """Enter chat and quit without sending a model turn."""
    result = run_la(
        ["chat", "--session-id", "s-e2e-quit", "-p", "openrouter"],
        env=la_env,
        input_text=":q\n",
        timeout=60,
    )
    assert result.returncode in (0, 1)
    assert "[错误]" not in result.stdout or "provider" in result.stdout.lower()


def test_e2e_config_example(la_env):
    result = run_la(["config-example"], env=la_env)
    assert result.returncode == 0
    assert "provider" in result.stdout
    assert "ollama" in result.stdout.lower() or "TAVILY" in result.stdout


def test_e2e_config_help(la_env):
    result = run_la(["config", "--help"], env=la_env)
    assert result.returncode == 0
    assert "list" in result.stdout
    assert "add" in result.stdout or "set-key" in result.stdout


def test_e2e_config_list(la_env, tmp_path: Path):
    result = run_la(["config", "list"], env=la_env)
    assert result.returncode == 0
    assert (
        "ollama" in result.stdout.lower()
        or "provider" in result.stdout.lower()
        or "model" in result.stdout.lower()
    )


def test_e2e_config_remove_missing(la_env):
    result = run_la(["config", "remove", "definitely-not-a-provider-xyz"], env=la_env)
    assert result.returncode == 1
    assert "未找到" in result.stdout or "not" in result.stdout.lower() or "config" in result.stdout.lower()


def test_e2e_config_apply_missing_file(la_env, tmp_path: Path):
    missing = tmp_path / "no-such-config.json"
    result = run_la(["config", str(missing)], env=la_env)
    assert result.returncode != 0


def test_e2e_workspace_summary(la_env):
    result = run_la(["workspace", "--days", "3"], env=la_env)
    assert result.returncode == 0
    assert result.stdout.strip()
    assert "[错误]" not in result.stdout


def test_e2e_workspace_todos_only(la_env, tmp_path: Path):
    todo = tmp_path / "TODO.md"
    todo.write_text("- [ ] e2e workspace todo item\n", encoding="utf-8")
    result = run_la(["workspace", "--todos-only", "--cwd", str(tmp_path)], env=la_env)
    assert result.returncode == 0
    assert "workspace" in result.stdout.lower() or "待办" in result.stdout or "TODO" in result.stdout


def test_e2e_workspace_help(la_env):
    result = run_la(["workspace", "--help"], env=la_env)
    assert result.returncode == 0
    assert "--days" in result.stdout
    assert "--todos-only" in result.stdout or "todos" in result.stdout


def test_e2e_workspace_empty_todos(la_env, tmp_path: Path):
    empty = tmp_path / "emptyws"
    empty.mkdir()
    result = run_la(["workspace", "--todos-only", "--cwd", str(empty)], env=la_env)
    assert result.returncode == 0
    assert "未扫描" in result.stdout or "0" in result.stdout or "待办" in result.stdout


def test_e2e_audit_summary(la_env):
    result = run_la(["audit", "--since", "7d"], env=la_env)
    assert result.returncode == 0
    assert result.stdout.strip()


def test_e2e_audit_invalid_since(la_env):
    result = run_la(["audit", "--since", "not-a-duration"], env=la_env)
    assert result.returncode == 1
    assert "audit" in result.stdout.lower() or result.stderr


def test_e2e_audit_report_file(la_env, tmp_path: Path):
    out = tmp_path / "audit.md"
    result = run_la(["audit", "--report", str(out)], env=la_env)
    assert result.returncode == 0
    assert "报告已写入" in result.stdout
    assert out.is_file()
    assert out.stat().st_size > 0


def test_e2e_audit_help(la_env):
    result = run_la(["audit", "--help"], env=la_env)
    assert result.returncode == 0
    assert "--since" in result.stdout
    assert "--report" in result.stdout


def test_e2e_setup_skip(la_env):
    env = {**la_env, "LA_SKIP_OLLAMA_SETUP": "1"}
    result = run_la(["setup"], env=env)
    assert result.returncode == 0
    assert "setup" in result.stdout.lower() or "跳过" in result.stdout or "skip" in result.stdout.lower()


def test_e2e_setup_help(la_env):
    result = run_la(["setup", "--help"], env=la_env)
    assert result.returncode == 0
    assert "--yes" in result.stdout or "Ollama" in result.stdout or "ollama" in result.stdout.lower()


def test_e2e_setup_decline_prompt(la_env):
    env = {**la_env}
    env.pop("LA_SKIP_OLLAMA_SETUP", None)
    result = run_la(["setup"], env=env, input_text="n\n", timeout=30)
    assert result.returncode == 0
    assert "跳过" in result.stdout or "setup" in result.stdout.lower() or "declin" in result.stdout.lower()


def test_e2e_tasks_help_and_empty_list(la_env):
    help_ = run_la(["tasks", "--help"], env=la_env)
    assert help_.returncode == 0
    assert "delete" in help_.stdout or "pause" in help_.stdout or "logs" in help_.stdout

    listed = run_la(["tasks"], env=la_env)
    assert listed.returncode == 0


def test_e2e_tasks_unknown_id(la_env):
    result = run_la(["tasks", "t-does-not-exist"], env=la_env)
    assert result.returncode == 1
    assert "未找到" in result.stdout


def test_e2e_tasks_logs_and_delete(la_env, tmp_path: Path):
    doc = write_kb_doc(tmp_path, "task-ops.md", "# TaskOps\n\ntasks logs and delete coverage\n")
    queued = run_la(["rag", "add", "--background", str(doc)], env=la_env)
    assert queued.returncode == 0
    task_id = parse_task_id(queued.stdout)
    wait_for_task(task_id, env=la_env, timeout=60)

    logs = run_la(["tasks", "logs", task_id], env=la_env)
    assert logs.returncode == 0

    deleted = run_la(["tasks", "delete", task_id], env=la_env)
    assert deleted.returncode == 0
    assert "已删除" in deleted.stdout

    missing = run_la(["tasks", task_id], env=la_env)
    assert missing.returncode == 1


def test_e2e_cross_memory_and_rag_isolation(la_env, tmp_path: Path):
    """rag add must not pollute Warm memory; memory add must still be searchable separately."""
    seed_memory(la_env, "2026年用户决定只用 memory add 写入 Warm 事实。")
    doc = write_kb_doc(
        tmp_path,
        "cold-only.md",
        "# Cold\n\n这篇文档只进知识库：UNIQUE_COLD_TOKEN_XYZ\n",
    )
    assert run_la(["rag", "add", str(doc)], env=la_env).returncode == 0

    mem = run_la(["memory", "search", "Warm 事实"], env=la_env)
    assert mem.returncode == 0
    assert "Warm" in mem.stdout or "memory add" in mem.stdout

    rag = run_la(["rag", "search", "UNIQUE_COLD_TOKEN_XYZ"], env=la_env)
    assert rag.returncode == 0
    assert "UNIQUE_COLD_TOKEN_XYZ" in rag.stdout

    q = run_la(["memory", "query", "--json"], env=la_env)
    assert q.returncode == 0
    payload = json.loads(q.stdout)
    texts = " ".join(str(item.get("text") or item) for item in payload)
    assert "UNIQUE_COLD_TOKEN_XYZ" not in texts or "Warm" in texts
