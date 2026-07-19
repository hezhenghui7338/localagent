"""E2E duration budgets for critical offline CLI paths.

Hang protection remains ``timeout=``; these tests pass explicit ``budget=`` so a
command that succeeds but is too slow fails. Disable with ``LA_E2E_BUDGETS=0``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import (
    BACKGROUND_TASK_BUDGET,
    DURATION_BUDGETS,
    lookup_duration_budget,
    parse_task_id,
    run_la,
    seed_memory,
    wait_for_task,
    write_chat_session,
    write_kb_doc,
)

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.serial,
    pytest.mark.xdist_group("serial"),
]


def _budget(args: list[str]) -> float:
    found = lookup_duration_budget(args)
    assert found is not None, f"no DURATION_BUDGETS entry for {args!r}"
    return found


# --- P0: interactive hot paths ---


def test_perf_help():
    args = ["--help"]
    result = run_la(args, budget=_budget(args), timeout=15)
    assert result.returncode == 0
    assert "memory" in result.stdout


def test_perf_version():
    args = ["-V"]
    result = run_la(args, budget=_budget(args), timeout=15)
    assert result.returncode == 0
    assert result.stdout.strip() or result.stderr.strip()


def test_perf_complete():
    args = ["complete", "--", "LA", "mem"]
    result = run_la(args, budget=_budget(args), timeout=15)
    assert result.returncode == 0
    assert "memory" in result.stdout.lower() or "mem" in result.stdout.lower()


def test_perf_memory_status(la_env):
    args = ["memory", "status"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=20)
    assert result.returncode == 0
    assert "记忆条数" in result.stdout or "Warm" in result.stdout


def test_perf_rag_status(la_env):
    args = ["rag", "status"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=20)
    assert result.returncode == 0
    assert "[rag" in result.stdout.lower() or "知识" in result.stdout or "索引" in result.stdout


def test_perf_daily_status(la_env):
    args = ["status"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=20)
    assert result.returncode == 0
    assert result.stdout.strip()


def test_perf_memory_add(la_env):
    args = ["ingest", "text", "2026年7月决定使用 Mem0 作为记忆引擎"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=30)
    assert result.returncode == 0
    assert "已写入记忆" in result.stdout or "Warm +" in result.stdout or "warm=1" in result.stdout


def test_perf_memory_search_hit(la_env):
    seed_memory(la_env, "2026年7月决定使用 Mem0 作为记忆引擎")
    args = ["memory", "search", "Mem0"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=30)
    assert result.returncode == 0
    assert "Mem0" in result.stdout


def test_perf_memory_query(la_env):
    seed_memory(la_env, "2026年7月决定使用 Mem0 作为记忆引擎")
    args = ["memory", "query", "--json"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=30)
    assert result.returncode == 0
    assert result.stdout.strip()


def test_perf_rag_add_small(la_env, tmp_path: Path):
    doc = write_kb_doc(
        tmp_path,
        "perf.md",
        "# Perf\n\nLocalAgent Cold RAG 小文件索引性能测试标记 PERF_RAG_TOKEN\n",
    )
    args = ["ingest", "doc", str(doc)]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=45)
    assert result.returncode == 0


def test_perf_rag_search(la_env, tmp_path: Path):
    doc = write_kb_doc(
        tmp_path,
        "perf-search.md",
        "# Perf Search\n\nCold 检索标记 PERF_SEARCH_TOKEN_XYZ\n",
    )
    assert run_la(["ingest", "doc", str(doc)], env=la_env, timeout=45).returncode == 0
    args = ["rag", "search", "PERF_SEARCH_TOKEN_XYZ"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=30)
    assert result.returncode == 0
    assert "PERF_SEARCH_TOKEN_XYZ" in result.stdout


def test_perf_chat_quit(la_env):
    args = ["chat", "--session-id", "s-e2e-perf-quit", "-p", "openrouter"]
    result = run_la(
        args,
        env=la_env,
        input_text=":q\n",
        budget=_budget(args),
        timeout=30,
    )
    assert result.returncode in (0, 1)
    assert "[错误]" not in result.stdout or "provider" in result.stdout.lower()


# --- P1: daily sidecars & ops ---


def test_perf_workspace(la_env, tmp_path: Path):
    args = ["workspace", "--todos-only", "--cwd", str(tmp_path)]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=20)
    assert result.returncode == 0


def test_perf_audit_summary(la_env):
    args = ["audit", "--since", "7d"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=30)
    assert result.returncode == 0


def test_perf_audit_report(la_env, tmp_path: Path):
    out = tmp_path / "audit-perf.html"
    args = ["audit", "--report", str(out)]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=30)
    assert result.returncode == 0
    assert out.is_file()


def test_perf_logs_path(la_env):
    args = ["logs", "--path"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=15)
    assert result.returncode == 0
    assert result.stdout.strip()


def test_perf_config_list(la_env):
    args = ["config", "list"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=20)
    assert result.returncode == 0


def test_perf_tasks_list(la_env):
    args = ["tasks"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=20)
    assert result.returncode == 0


def test_perf_memory_pending(la_env_pending):
    args = ["memory", "pending"]
    result = run_la(args, env=la_env_pending, budget=_budget(args), timeout=20)
    assert result.returncode == 0


def test_perf_summarize_heuristic(la_env, tmp_path: Path):
    doc = write_kb_doc(
        tmp_path,
        "brief.md",
        "# 周报\n\n本周完成 LocalAgent 性能预算用例规划与落地。\n\n下一步：CI 跑通。\n",
    )
    args = ["summarize", str(doc), "--no-chat", "--heuristic"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=30)
    assert result.returncode == 0
    assert result.stdout.strip()


def test_perf_polish_offline(la_env):
    """Offline contract: empty polish prints usage and exits quickly (no model call)."""
    args = ["polish"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=20)
    assert result.returncode == 1
    out = (result.stdout + result.stderr).lower()
    assert "用法" in result.stdout or "usage" in out
    assert "polish" in out


# --- P2: batch / background ---


def test_perf_rag_bg_task(la_env, tmp_path: Path):
    doc = write_kb_doc(
        tmp_path,
        "bg.md",
        "# Background\n\n后台 ingest 性能标记 PERF_BG_TOKEN\n",
    )
    enqueue_args = ["ingest", "doc", "--background", str(doc)]
    queued = run_la(
        enqueue_args,
        env=la_env,
        budget=_budget(enqueue_args),
        timeout=30,
    )
    assert queued.returncode == 0, queued.stdout + queued.stderr
    task_id = parse_task_id(queued.stdout)
    wait_for_task(
        task_id,
        env=la_env,
        timeout=60,
        budget=BACKGROUND_TASK_BUDGET,
    )


def test_perf_memory_ingest_chat(la_env, la_data_dir: Path):
    sid = "s-e2e-perf-ingest"
    write_chat_session(
        la_data_dir,
        sid,
        [
            {
                "ts": "2026-07-11T10:00:00",
                "role": "user",
                "content": "2026年7月我用 LocalAgent 管理个人记忆",
            },
            {
                "ts": "2026-07-11T10:00:01",
                "role": "assistant",
                "content": "好的，已记下。",
            },
        ],
    )
    args = ["ingest", "chat", "--session", sid]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=60)
    assert result.returncode == 0
    assert "已保存" in result.stdout or "未提取" in result.stdout or "cold" in result.stdout.lower()


def test_perf_memory_reindex(la_env):
    seed_memory(la_env, "2026年7月决定使用 Mem0 作为记忆引擎")
    args = ["memory", "reindex"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=45)
    assert result.returncode == 0


def test_perf_rag_rebuild(la_env, tmp_path: Path):
    doc = write_kb_doc(tmp_path, "rebuild.md", "# Rebuild\n\n小库重建标记 PERF_REBUILD\n")
    assert run_la(["ingest", "doc", str(doc)], env=la_env, timeout=45).returncode == 0
    args = ["ingest", "rebuild"]
    result = run_la(args, env=la_env, budget=_budget(args), timeout=45)
    assert result.returncode == 0


def test_duration_budgets_table_covers_perf_prefixes():
    """Smoke: table keys used by this module resolve via longest-prefix match."""
    samples = [
        ["--help"],
        ["memory", "status"],
        ["ingest", "doc", "/tmp/x.md"],
        ["ingest", "doc", "--background", "/tmp/x.md"],
        ["audit", "--report", "/tmp/a.html"],
        ["ingest", "chat", "--session", "s"],
    ]
    for args in samples:
        assert lookup_duration_budget(args) is not None, args
    assert DURATION_BUDGETS[("memory", "search")] == 10.0
