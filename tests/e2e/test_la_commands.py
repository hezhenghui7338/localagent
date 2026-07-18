"""End-to-end tests: real subprocess invocations of LA CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import PROJECT_ROOT, ollama_completion_models, parse_task_id, run_la, wait_for_task

pytestmark = pytest.mark.e2e


def test_e2e_help():
    result = run_la(["--help"])
    assert result.returncode == 0
    assert "memory" in result.stdout
    assert "rag" in result.stdout
    assert "reflect" in result.stdout
    assert "websearch" in result.stdout
    assert "chat" in result.stdout
    assert "tasks" in result.stdout
    assert "delete|pause|resume|restart|logs" in result.stdout


def test_e2e_add(la_env):
    result = run_la(["memory", "add", "2026年7月决定使用 Mem0 作为记忆引擎"], env=la_env)
    assert result.returncode == 0
    assert "已写入记忆" in result.stdout


def test_e2e_add_rejects_short_text(la_env):
    result = run_la(["memory", "add", "好的"], env=la_env)
    assert result.returncode == 1
    assert "未写入" in result.stdout


def test_e2e_rag_add_and_ingest(la_env, tmp_path: Path):
    doc = tmp_path / "diary.md"
    doc.write_text(
        "# 日记\n\n2026年7月决定使用 Mem0 作为记忆引擎。\n\n## 计划\n\n先实现 rag add。",
        encoding="utf-8",
    )

    result = run_la(["rag", "add", str(doc)], env=la_env)
    assert result.returncode == 0
    assert "软链:" in result.stdout
    assert "done" in result.stdout

    kb_link = Path(la_env["LA_DATA_DIR"]) / "kb" / "diary.md"
    assert kb_link.is_symlink()

    result2 = run_la(["rag", "ingest"], env=la_env)
    assert result2.returncode == 0
    assert "skipped" in result2.stdout


def test_e2e_rag_ingest_force(la_env, tmp_path: Path):
    doc = tmp_path / "note.md"
    doc.write_text("# Note\n\nversion one for force sync", encoding="utf-8")
    run_la(["rag", "add", str(doc)], env=la_env)

    result = run_la(["rag", "ingest", "--force"], env=la_env)
    assert result.returncode == 0
    assert "updated" in result.stdout or "new" in result.stdout or "rag ingest" in result.stdout


def test_e2e_search_memory(la_env):
    run_la(["memory", "add", "2026年7月决定使用 Mem0 作为记忆引擎"], env=la_env)
    result = run_la(["memory", "search", "Mem0"], env=la_env)
    assert result.returncode == 0
    assert "Mem0" in result.stdout
    assert "forget" in result.stdout


def test_e2e_search_knowledge(la_env, tmp_path: Path):
    doc = tmp_path / "spec.md"
    doc.write_text("# 技术方案\n\nLocalAgent 使用 Mem0 管理长期记忆。", encoding="utf-8")
    run_la(["rag", "add", str(doc)], env=la_env)

    result = run_la(["rag", "search", "Mem0"], env=la_env)
    assert result.returncode == 0
    assert "Mem0" in result.stdout


def test_e2e_forget_memory(la_env, la_data_dir: Path):
    run_la(["memory", "add", "2026年7月决定使用 Mem0 作为记忆引擎"], env=la_env)
    store_path = la_data_dir / "memory_store.json"
    fact_id = json.loads(store_path.read_text(encoding="utf-8"))["facts"][0]["id"]

    search = run_la(["memory", "search", "Mem0"], env=la_env)
    assert search.returncode == 0
    assert fact_id[:8] in search.stdout

    forget = run_la(["memory", "forget", fact_id, "--yes"], env=la_env)
    assert forget.returncode == 0
    assert "已删除" in forget.stdout


def test_e2e_reset_memory(la_env, tmp_path: Path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Doc\n\ncontent for reset test", encoding="utf-8")
    run_la(["rag", "add", str(doc)], env=la_env)
    run_la(["memory", "add", "用户喜欢喝葡萄酒。"], env=la_env)

    result = run_la(["memory", "reset"], env=la_env)
    assert result.returncode == 0
    assert "memory reset" in result.stdout
    assert (Path(la_env["LA_DATA_DIR"]) / "kb" / "doc.md").exists()


def test_e2e_rag_rebuild(la_env, tmp_path: Path):
    doc = tmp_path / "rebuild.md"
    doc.write_text("# Rebuild\n\nrebuild test content here", encoding="utf-8")
    run_la(["rag", "add", str(doc)], env=la_env)
    run_la(["rag", "reset"], env=la_env)

    result = run_la(["rag", "rebuild"], env=la_env)
    assert result.returncode == 0
    assert "rag rebuild" in result.stdout


def test_e2e_ollama_model_autodetect():
    if not ollama_completion_models():
        pytest.skip("Ollama 未运行")

    code = """
from localagent.models.router import get_model_router
router = get_model_router()
resolved = router.resolve_ollama_model()
print(resolved)
"""
    import os

    env = os.environ.copy()
    env["OLLAMA_MODEL"] = "qwen3:4b"
    env.pop("OPENAI_API_KEY", None)
    env.pop("OPENROUTER_API_KEY", None)
    env.pop("CURSOR_API_KEY", None)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=PROJECT_ROOT,
        timeout=10,
    )
    assert proc.returncode == 0
    resolved = proc.stdout.strip()
    assert resolved in ollama_completion_models()


def test_e2e_add_file_background(la_env, tmp_path: Path):
    doc = tmp_path / "bg.md"
    doc.write_text("# BG\n\nbackground e2e test content for ingest", encoding="utf-8")

    result = run_la(["rag", "add", "--background", str(doc)], env=la_env)
    assert result.returncode == 0
    assert "后台任务" in result.stdout
    assert "软链:" in result.stdout
    assert "日志:" in result.stdout

    task_id = parse_task_id(result.stdout)
    status = run_la(["tasks", task_id], env=la_env)
    assert status.returncode == 0
    assert task_id in status.stdout

    wait_for_task(task_id, env=la_env, timeout=30)


def test_e2e_tasks_list(la_env, tmp_path: Path):
    doc = tmp_path / "list.md"
    doc.write_text("# List\n\ntasks list test", encoding="utf-8")
    run_la(["rag", "add", "--background", str(doc)], env=la_env)

    result = run_la(["tasks"], env=la_env)
    assert result.returncode == 0
    assert "t-" in result.stdout


def test_mem0_is_core_dependency():
    """mem0ai is a required dependency for the Warm memory engine."""
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "mem0ai" in text
    assert "hindsight-all" not in text
