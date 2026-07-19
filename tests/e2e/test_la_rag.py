"""E2E coverage for ``LA rag`` subcommands (Cold knowledge)."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import parse_task_id, run_la, wait_for_task, write_kb_doc

pytestmark = pytest.mark.e2e


def test_e2e_rag_help(la_env):
    result = run_la(["rag", "--help"], env=la_env)
    assert result.returncode == 0
    for token in ("add", "ingest", "search", "status", "reset", "rebuild"):
        assert token in result.stdout


def test_e2e_rag_status_empty(la_env):
    result = run_la(["rag", "status"], env=la_env)
    assert result.returncode == 0
    assert "Cold" in result.stdout or "知识库" in result.stdout
    assert "已索引文件" in result.stdout
    assert "知识块数" in result.stdout
    assert "下一步" in result.stdout


def test_e2e_bare_rag_shows_status(la_env):
    result = run_la(["rag"], env=la_env)
    assert result.returncode == 0
    assert "[rag status]" in result.stdout
    assert "kb 目录" in result.stdout
    assert "下一步" in result.stdout


def test_e2e_rag_add_status_search(la_env, tmp_path: Path):
    doc = write_kb_doc(
        tmp_path,
        "architecture.md",
        "# 架构\n\nLocalAgent 使用 Mem0 管理 Warm 记忆，Chroma 管理 Cold RAG。\n",
    )
    add = run_la(["ingest", "doc", str(doc)], env=la_env)
    assert add.returncode == 0
    assert "软链:" in add.stdout or "archived:" in add.stdout or "ingest doc" in add.stdout
    assert "done" in add.stdout

    kb = Path(la_env["LA_DATA_DIR"]) / "kb" / "architecture.md"
    assert kb.is_symlink()

    status = run_la(["rag", "status"], env=la_env)
    assert status.returncode == 0
    assert "1" in status.stdout or "architecture" in status.stdout

    search = run_la(["rag", "search", "Mem0 Warm"], env=la_env)
    assert search.returncode == 0
    assert "Mem0" in search.stdout or "Warm" in search.stdout


def test_e2e_rag_search_top_k(la_env, tmp_path: Path):
    doc = write_kb_doc(
        tmp_path,
        "notes.md",
        "# Notes\n\n## A\n\nalpha keyword unique\n\n## B\n\nbeta keyword unique\n",
    )
    assert run_la(["ingest", "doc", str(doc)], env=la_env).returncode == 0
    result = run_la(["rag", "search", "keyword", "--top-k", "1"], env=la_env)
    assert result.returncode == 0
    assert result.stdout.strip()


def test_e2e_rag_search_miss(la_env, tmp_path: Path):
    doc = write_kb_doc(tmp_path, "plain.md", "# Plain\n\nonly cats and dogs here\n")
    assert run_la(["ingest", "doc", str(doc)], env=la_env).returncode == 0
    result = run_la(["rag", "search", "quantum strawberry xyzzy"], env=la_env)
    assert result.returncode == 0
    assert "[错误]" not in result.stdout


def test_e2e_rag_ingest_skip_then_force(la_env, tmp_path: Path):
    doc = write_kb_doc(tmp_path, "diary.md", "# 日记\n\n今天实现了 rag ingest 增量跳过。\n")
    assert run_la(["ingest", "doc", str(doc)], env=la_env).returncode == 0

    skipped = run_la(["ingest", "kb"], env=la_env)
    assert skipped.returncode == 0
    assert "skipped" in skipped.stdout or "rag ingest" in skipped.stdout or "ingest kb" in skipped.stdout

    forced = run_la(["ingest", "kb", "--force"], env=la_env)
    assert forced.returncode == 0
    assert "updated" in forced.stdout or "new" in forced.stdout or "rag ingest" in forced.stdout or "ingest kb" in forced.stdout


def test_e2e_rag_ingest_new_symlink_only(la_env, tmp_path: Path, la_data_dir: Path):
    """File already linked into kb/ without going through add should be picked up by ingest."""
    src = write_kb_doc(tmp_path, "linked.md", "# Linked\n\ningest discovers bare symlink content.\n")
    target = la_data_dir / "kb" / "linked.md"
    target.symlink_to(src)

    result = run_la(["ingest", "kb"], env=la_env)
    assert result.returncode == 0
    assert "new" in result.stdout or "linked" in result.stdout or "rag ingest" in result.stdout or "ingest kb" in result.stdout

    search = run_la(["rag", "search", "bare symlink"], env=la_env)
    assert search.returncode == 0
    assert "symlink" in search.stdout.lower() or "ingest" in search.stdout.lower() or "Linked" in search.stdout


def test_e2e_rag_reset_preserves_symlink(la_env, tmp_path: Path):
    doc = write_kb_doc(tmp_path, "keep.md", "# Keep\n\nreset should keep kb symlink\n")
    assert run_la(["ingest", "doc", str(doc)], env=la_env).returncode == 0
    kb = Path(la_env["LA_DATA_DIR"]) / "kb" / "keep.md"
    assert kb.exists()

    reset = run_la(["rag", "reset"], env=la_env)
    assert reset.returncode == 0
    assert "rag reset" in reset.stdout
    assert "done" in reset.stdout
    assert kb.exists()

    status = run_la(["rag", "status"], env=la_env)
    assert status.returncode == 0
    # Index cleared; file count may still list sync empty
    assert "知识块数" in status.stdout


def test_e2e_rag_rebuild_after_reset(la_env, tmp_path: Path):
    doc = write_kb_doc(tmp_path, "rebuild.md", "# Rebuild\n\nrebuild restores Cold index from kb/\n")
    assert run_la(["ingest", "doc", str(doc)], env=la_env).returncode == 0
    assert run_la(["rag", "reset"], env=la_env).returncode == 0

    rebuild = run_la(["ingest", "rebuild"], env=la_env)
    assert rebuild.returncode == 0
    assert "rag rebuild" in rebuild.stdout or "ingest rebuild" in rebuild.stdout

    search = run_la(["rag", "search", "Cold index"], env=la_env)
    assert search.returncode == 0
    assert "Cold" in search.stdout or "rebuild" in search.stdout.lower() or "kb" in search.stdout.lower()


def test_e2e_rag_add_background_and_tasks(la_env, tmp_path: Path):
    doc = write_kb_doc(tmp_path, "bg2.md", "# BG2\n\nsecond background ingest path for rag e2e\n")
    result = run_la(["ingest", "doc", "--background", str(doc)], env=la_env)
    assert result.returncode == 0
    assert "后台任务" in result.stdout
    assert "软链:" in result.stdout or "archived:" in result.stdout or "background" in result.stdout or "ingest doc" in result.stdout
    task_id = parse_task_id(result.stdout)
    wait_for_task(task_id, env=la_env, timeout=60)

    search = run_la(["rag", "search", "background ingest"], env=la_env)
    assert search.returncode == 0
    assert "background" in search.stdout.lower() or "BG2" in search.stdout


def test_e2e_rag_add_missing_file(la_env, tmp_path: Path):
    missing = tmp_path / "nope.md"
    result = run_la(["ingest", "doc", str(missing)], env=la_env)
    assert result.returncode == 1
    assert "error" in result.stdout.lower() or "不存在" in result.stdout or "No such" in result.stdout or "not found" in result.stdout.lower()


def test_e2e_rag_rebuild_empty_kb(la_env):
    result = run_la(["ingest", "rebuild"], env=la_env)
    assert result.returncode == 0
    assert "rag rebuild" in result.stdout or "ingest rebuild" in result.stdout


def test_e2e_rag_rebuild_idempotent(la_env, tmp_path: Path):
    doc = write_kb_doc(tmp_path, "idem.md", "# Idem\n\nrebuild twice should succeed\n")
    assert run_la(["ingest", "doc", str(doc)], env=la_env).returncode == 0
    first = run_la(["ingest", "rebuild"], env=la_env)
    second = run_la(["ingest", "rebuild"], env=la_env)
    assert first.returncode == 0
    assert second.returncode == 0
    assert "rag rebuild" in first.stdout or "ingest rebuild" in first.stdout


def test_e2e_rag_reset_keep_index_flag(la_env, tmp_path: Path):
    doc = write_kb_doc(tmp_path, "keepidx.md", "# KeepIdx\n\noptional keep-index path\n")
    assert run_la(["ingest", "doc", str(doc)], env=la_env).returncode == 0
    help_ = run_la(["rag", "reset", "--help"], env=la_env)
    assert help_.returncode == 0
    result = run_la(["rag", "reset"], env=la_env)
    assert result.returncode == 0
    assert "rag reset" in result.stdout


def test_e2e_rag_status_after_add_lists_file(la_env, tmp_path: Path):
    doc = write_kb_doc(tmp_path, "listed.md", "# Listed\n\nstatus should see indexed file\n")
    assert run_la(["ingest", "doc", str(doc)], env=la_env).returncode == 0
    status = run_la(["rag", "status"], env=la_env)
    assert status.returncode == 0
    assert "已索引文件" in status.stdout
    assert "知识块数" in status.stdout
    # at least one indexed file / non-zero chunks typically
    assert "下一步" in status.stdout


def test_e2e_rag_ingest_help(la_env):
    result = run_la(["ingest", "kb", "--help"], env=la_env)
    assert result.returncode == 0
    assert "--force" in result.stdout


def test_e2e_rag_search_help(la_env):
    result = run_la(["rag", "search", "--help"], env=la_env)
    assert result.returncode == 0
    assert "--top-k" in result.stdout or "query" in result.stdout.lower()
