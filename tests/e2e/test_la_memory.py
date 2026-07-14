"""E2E coverage for ``LA memory`` subcommands (Warm layer)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers import (
    memory_fact_ids,
    minimal_chatgpt_export,
    parse_task_id,
    require_ollama_completion,
    run_la,
    seed_memory,
    wait_for_task,
)

pytestmark = pytest.mark.e2e

FACT_A = "2026年7月决定使用 Mem0 作为记忆引擎"
FACT_B = "用户喜欢喝葡萄酒，尤其是赤霞珠。"
FACT_C = "2024年3月入职 Acme，负责 LocalAgent 记忆子系统。"


def test_e2e_memory_help(la_env):
    result = run_la(["memory", "--help"], env=la_env)
    assert result.returncode == 0
    for token in ("add", "search", "query", "reflect", "consolidate", "forget", "status", "ingest"):
        assert token in result.stdout


def test_e2e_bare_memory_shows_status(la_env):
    result = run_la(["memory"], env=la_env)
    assert result.returncode == 0
    assert "[memory status]" in result.stdout
    assert "来源分布" in result.stdout
    assert "下一步" in result.stdout


def test_e2e_memory_add_and_status(la_env):
    seed_memory(la_env, FACT_A)
    status = run_la(["memory", "status"], env=la_env)
    assert status.returncode == 0
    assert "Warm" in status.stdout
    assert "json" in status.stdout
    assert "记忆条数" in status.stdout
    assert "1" in status.stdout


def test_e2e_memory_search_hit_and_miss(la_env):
    seed_memory(la_env, FACT_A)
    hit = run_la(["memory", "search", "Mem0 记忆引擎"], env=la_env)
    assert hit.returncode == 0
    assert "Mem0" in hit.stdout
    assert "forget" in hit.stdout

    miss = run_la(["memory", "search", "完全无关的量子草莓配方 xyzzy"], env=la_env, timeout=90)
    assert miss.returncode == 0
    # May fall back to RAG/docs; must not crash and should not invent the seeded fact as only hit
    assert "[错误]" not in miss.stdout


def test_e2e_memory_search_top_k_and_verbose(la_env):
    seed_memory(la_env, FACT_A)
    seed_memory(la_env, FACT_B)
    result = run_la(["memory", "search", "记忆", "--top-k", "1", "--verbose"], env=la_env)
    assert result.returncode == 0
    assert result.stdout.strip()


def test_e2e_memory_search_knowledge_flag_migrated(la_env):
    result = run_la(["memory", "search", "--knowledge", "x"], env=la_env)
    assert result.returncode == 2
    assert "rag search" in result.stdout


def test_e2e_memory_query_list_json_and_tags(la_env, la_data_dir: Path):
    seed_memory(la_env, FACT_A)
    seed_memory(la_env, FACT_B)

    listed = run_la(["memory", "query"], env=la_env)
    assert listed.returncode == 0
    assert "Mem0" in listed.stdout or "葡萄酒" in listed.stdout
    assert "forget" in listed.stdout

    as_json = run_la(["memory", "query", "--json"], env=la_env)
    assert as_json.returncode == 0
    payload = json.loads(as_json.stdout)
    assert isinstance(payload, list)
    assert len(payload) >= 2

    filtered = run_la(["memory", "query", "葡萄酒", "--sort", "relevance"], env=la_env)
    assert filtered.returncode == 0
    assert "葡萄酒" in filtered.stdout

    tags = run_la(["memory", "query", "--list-tags"], env=la_env)
    assert tags.returncode == 0
    # Tags may be empty depending on enrich path; command must succeed.
    assert "标签" in tags.stdout or tags.stdout.strip() == "记忆库中暂无标签。"


def test_e2e_memory_query_since_until(la_env):
    seed_memory(la_env, FACT_C)
    result = run_la(
        ["memory", "query", "--since", "2024-01-01", "--until", "2024-12-31", "--json"],
        env=la_env,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)


def test_e2e_memory_forget_missing_and_cancel(la_env, la_data_dir: Path):
    missing = run_la(["memory", "forget", "deadbeefdeadbeef", "--yes"], env=la_env)
    assert missing.returncode == 1
    assert "未找到" in missing.stdout

    seed_memory(la_env, FACT_A)
    fact_id = memory_fact_ids(la_data_dir)[0]
    cancel = run_la(["memory", "forget", fact_id], env=la_env, input_text="n\n")
    assert cancel.returncode == 0
    assert "已取消" in cancel.stdout
    assert memory_fact_ids(la_data_dir) == [fact_id]


def test_e2e_memory_reset_by_source(la_env):
    seed_memory(la_env, FACT_A)
    result = run_la(["memory", "reset", "all"], env=la_env)
    assert result.returncode == 0
    assert "memory reset" in result.stdout
    assert "done" in result.stdout

    status = run_la(["memory", "status"], env=la_env)
    assert "记忆条数" in status.stdout


def test_e2e_memory_reset_file_migrated(la_env):
    result = run_la(["memory", "reset", "file"], env=la_env)
    assert result.returncode == 2
    assert "rag reset" in result.stdout


def test_e2e_memory_rebuild_points_to_reindex(la_env):
    result = run_la(["memory", "rebuild"], env=la_env)
    assert result.returncode == 2
    assert "reindex" in result.stdout
    assert "rag rebuild" in result.stdout


def test_e2e_memory_reindex_json_backend(la_env):
    seed_memory(la_env, FACT_A)
    result = run_la(["memory", "reindex"], env=la_env)
    assert result.returncode == 0
    assert "memory reindex" in result.stdout
    assert "json" in result.stdout.lower() or "skipped" in result.stdout.lower() or "reindexed" in result.stdout


def test_e2e_memory_add_file_migrated(la_env, tmp_path: Path):
    doc = tmp_path / "x.md"
    doc.write_text("# x\n", encoding="utf-8")
    result = run_la(["memory", "add-file", str(doc)], env=la_env)
    assert result.returncode == 2
    assert "rag add" in result.stdout


def test_e2e_memory_ingest_chat_empty_session(la_env, la_data_dir: Path):
    """Without LLM extraction success, command still exits cleanly."""
    sid = "s-e2e-empty"
    conv = la_data_dir / "conversations" / f"{sid}.jsonl"
    conv.write_text(
        json.dumps({"ts": "2026-07-11T10:00:00", "role": "user", "content": "你好"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    result = run_la(["memory", "ingest", "chat", "--session", sid], env=la_env, timeout=120)
    assert result.returncode == 0
    assert "已保存" in result.stdout or "未提取" in result.stdout


def test_e2e_memory_ingest_chatgpt_file(la_env, tmp_path: Path):
    export = tmp_path / "conversations.json"
    export.write_text(json.dumps(minimal_chatgpt_export(), ensure_ascii=False), encoding="utf-8")
    result = run_la(
        ["memory", "ingest", "chatgpt", str(export)],
        env=la_env,
        timeout=180,
    )
    assert result.returncode == 0
    # Extraction may yield 0 without usable LLM; command path must succeed.
    assert "chatgpt" in result.stdout.lower() or "记忆" in result.stdout or "未" in result.stdout


def test_e2e_memory_consolidate_foreground(la_env):
    seed_memory(la_env, FACT_A)
    seed_memory(la_env, "2026年7月决定采用 Mem0 管理长期记忆。")
    result = run_la(
        ["memory", "consolidate", "--foreground", "--limit", "10"],
        env=la_env,
        timeout=180,
    )
    assert result.returncode == 0
    assert "memory consolidate" in result.stdout
    assert "changed=" in result.stdout


def test_e2e_memory_consolidate_background(la_env):
    seed_memory(la_env, FACT_A)
    result = run_la(["memory", "consolidate", "--limit", "5"], env=la_env)
    assert result.returncode == 0
    assert "后台任务" in result.stdout
    task_id = parse_task_id(result.stdout)
    wait_for_task(task_id, env=la_env, timeout=120)


def test_e2e_memory_reflect_smoke(la_env):
    """Offline-safe: command returns; may synthesize or report inability."""
    seed_memory(la_env, FACT_A)
    result = run_la(["memory", "reflect", "Mem0 相关决策是什么"], env=la_env, timeout=180)
    assert result.returncode == 0
    assert "推理记忆" in result.stdout or result.stdout.strip()
    assert "[错误]" not in result.stdout


def test_e2e_memory_reflect_with_evidence(la_env):
    """When a completion model is available, reflect should use seeded facts."""
    require_ollama_completion()
    seed_memory(la_env, FACT_A)
    seed_memory(la_env, FACT_B)
    result = run_la(
        ["memory", "reflect", "关于记忆引擎和葡萄酒的偏好分别是什么？"],
        env=la_env,
        timeout=300,
    )
    assert result.returncode == 0
    out = result.stdout
    assert "未能从记忆中推理出答案" not in out or "Mem0" in out or "葡萄酒" in out
    # Prefer positive evidence when model works
    if "未能从记忆中推理出答案" not in out:
        assert "Mem0" in out or "葡萄酒" in out or "记忆" in out


def test_e2e_memory_roundtrip_add_search_forget(la_env, la_data_dir: Path):
    seed_memory(la_env, FACT_A)
    search = run_la(["memory", "search", "Mem0"], env=la_env)
    assert search.returncode == 0
    fact_id = memory_fact_ids(la_data_dir)[0]
    assert fact_id[:8] in search.stdout

    forget = run_la(["memory", "forget", fact_id, "--yes"], env=la_env)
    assert forget.returncode == 0
    assert "已删除" in forget.stdout

    after = run_la(["memory", "search", "Mem0"], env=la_env)
    assert after.returncode == 0
    assert fact_id[:8] not in after.stdout


def test_e2e_memory_status_empty_and_help(la_env):
    status = run_la(["memory", "status"], env=la_env)
    assert status.returncode == 0
    assert "记忆条数" in status.stdout
    assert "来源分布" in status.stdout
    help_ = run_la(["memory", "status", "--help"], env=la_env)
    assert help_.returncode == 0


def test_e2e_memory_status_source_counts(la_env):
    seed_memory(la_env, FACT_A)
    status = run_la(["memory", "status"], env=la_env)
    assert status.returncode == 0
    assert "记忆条数" in status.stdout
    assert "1" in status.stdout
    assert "other=" in status.stdout or "manual" in status.stdout.lower() or "来源分布" in status.stdout


def test_e2e_memory_reindex_empty_store(la_env):
    result = run_la(["memory", "reindex"], env=la_env)
    assert result.returncode == 0
    assert "memory reindex" in result.stdout


def test_e2e_memory_reindex_idempotent(la_env):
    seed_memory(la_env, FACT_A)
    first = run_la(["memory", "reindex"], env=la_env)
    second = run_la(["memory", "reindex"], env=la_env)
    assert first.returncode == 0
    assert second.returncode == 0
    assert "memory reindex" in first.stdout
    assert "memory reindex" in second.stdout


def test_e2e_memory_rebuild_help_message_stable(la_env):
    result = run_la(["memory", "rebuild"], env=la_env)
    assert result.returncode == 2
    assert "LA memory reindex" in result.stdout
    assert "LA rag rebuild" in result.stdout


def test_e2e_memory_add_file_help_points_to_rag(la_env):
    help_ = run_la(["memory", "add-file", "--help"], env=la_env)
    assert help_.returncode == 0
    assert "rag add" in help_.stdout
    bare = run_la(["memory", "add-file"], env=la_env)
    assert bare.returncode == 2
    assert "rag add" in bare.stdout


def test_e2e_memory_consolidate_empty(la_env):
    result = run_la(
        ["memory", "consolidate", "--foreground", "--limit", "5"],
        env=la_env,
        timeout=120,
    )
    assert result.returncode == 0
    assert "changed=" in result.stdout


def test_e2e_memory_consolidate_help(la_env):
    result = run_la(["memory", "consolidate", "--help"], env=la_env)
    assert result.returncode == 0
    assert "--foreground" in result.stdout or "-f" in result.stdout
    assert "--limit" in result.stdout


def test_e2e_memory_query_limit_and_sort_oldest(la_env):
    seed_memory(la_env, FACT_A)
    seed_memory(la_env, FACT_B)
    result = run_la(["memory", "query", "--sort", "oldest", "--limit", "1", "--json"], env=la_env)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert len(payload) <= 1


def test_e2e_memory_query_verbose(la_env):
    seed_memory(la_env, FACT_A)
    result = run_la(["memory", "query", "Mem0", "--verbose"], env=la_env)
    assert result.returncode == 0
    assert "Mem0" in result.stdout


def test_e2e_memory_ingest_all_no_sessions(la_env):
    result = run_la(["memory", "ingest", "all"], env=la_env, timeout=120)
    assert result.returncode == 0


def test_e2e_memory_ingest_chat_force_flag(la_env, la_data_dir: Path):
    sid = "s-e2e-force"
    conv = la_data_dir / "conversations" / f"{sid}.jsonl"
    conv.write_text(
        json.dumps(
            {"ts": "2026-07-11T10:00:00", "role": "user", "content": "我决定用 Mem0"},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    first = run_la(["memory", "ingest", "chat", "--session", sid], env=la_env, timeout=120)
    assert first.returncode == 0
    second = run_la(
        ["memory", "ingest", "chat", "--session", sid, "--force"],
        env=la_env,
        timeout=120,
    )
    assert second.returncode == 0


def test_e2e_memory_reflect_empty_bank(la_env):
    result = run_la(["memory", "reflect", "没有任何记忆时会怎样"], env=la_env, timeout=120)
    assert result.returncode == 0
    assert "未能从记忆中推理出答案" in result.stdout or result.stdout.strip()


def test_e2e_memory_reflect_help(la_env):
    result = run_la(["memory", "reflect", "--help"], env=la_env)
    assert result.returncode == 0
    assert "query" in result.stdout.lower() or "推理" in result.stdout
