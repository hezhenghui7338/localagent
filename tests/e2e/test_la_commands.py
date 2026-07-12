"""End-to-end tests: real subprocess invocations of LA CLI."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from helpers import PROJECT_ROOT, ollama_completion_models, run_la

pytestmark = pytest.mark.e2e


def test_e2e_help():
    result = run_la(["--help"])
    assert result.returncode == 0
    assert "add-file" in result.stdout
    assert "chat" in result.stdout
    assert "forget" in result.stdout
    assert "delete|pause|resume|restart|logs" in result.stdout
    assert "[-b]" in result.stdout


def test_e2e_add(la_env):
    result = run_la(["add", "2026年7月决定使用 Hindsight 作为记忆引擎"], env=la_env)
    assert result.returncode == 0
    assert "已写入记忆" in result.stdout


def test_e2e_add_rejects_short_text(la_env):
    result = run_la(["add", "好的"], env=la_env)
    assert result.returncode == 1
    assert "未写入" in result.stdout


def test_e2e_add_file_and_sync(la_env, tmp_path: Path):
    doc = tmp_path / "diary.md"
    doc.write_text(
        "# 日记\n\n2026年7月决定使用 Hindsight 作为记忆引擎。\n\n## 计划\n\n先实现 add-file。",
        encoding="utf-8",
    )

    result = run_la(["add-file", str(doc)], env=la_env)
    assert result.returncode == 0
    assert "软链:" in result.stdout
    assert "done" in result.stdout

    kb_link = Path(la_env["LA_DATA_DIR"]) / "kb" / "diary.md"
    assert kb_link.is_symlink()

    result2 = run_la(["sync-file"], env=la_env)
    assert result2.returncode == 0
    assert "skipped" in result2.stdout


def test_e2e_sync_file_force(la_env, tmp_path: Path):
    doc = tmp_path / "note.md"
    doc.write_text("# Note\n\nversion one for force sync", encoding="utf-8")
    run_la(["add-file", str(doc)], env=la_env)

    result = run_la(["sync-file", "--force"], env=la_env)
    assert result.returncode == 0
    assert "sync-file" in result.stderr + result.stdout or "updated" in result.stdout or "new" in result.stdout


def test_e2e_search_memory(la_env):
    run_la(["add", "2026年7月决定使用 Hindsight 作为记忆引擎"], env=la_env)
    result = run_la(["search", "Hindsight"], env=la_env)
    assert result.returncode == 0
    assert "Hindsight" in result.stdout
    assert "forget" in result.stdout


def test_e2e_search_knowledge(la_env, tmp_path: Path):
    doc = tmp_path / "spec.md"
    doc.write_text("# 技术方案\n\nLocalAgent 使用 Hindsight 管理长期记忆。", encoding="utf-8")
    run_la(["add-file", str(doc)], env=la_env)

    result = run_la(["search", "Hindsight", "--knowledge"], env=la_env)
    assert result.returncode == 0
    assert "Hindsight" in result.stdout


def test_e2e_forget_memory(la_env, la_data_dir: Path):
    run_la(["add", "2026年7月决定使用 Hindsight 作为记忆引擎"], env=la_env)
    store_path = la_data_dir / "memory_store.json"
    fact_id = json.loads(store_path.read_text(encoding="utf-8"))["facts"][0]["id"]

    search = run_la(["search", "Hindsight"], env=la_env)
    assert search.returncode == 0
    assert fact_id[:8] in search.stdout

    forget = run_la(["forget", fact_id, "--yes"], env=la_env)
    assert forget.returncode == 0
    assert "已删除" in forget.stdout


def test_e2e_reset_memory(la_env, tmp_path: Path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Doc\n\ncontent for reset test", encoding="utf-8")
    run_la(["add-file", str(doc)], env=la_env)

    result = run_la(["reset-memory"], env=la_env)
    assert result.returncode == 0
    assert "reset-memory" in result.stdout
    assert (Path(la_env["LA_DATA_DIR"]) / "kb" / "doc.md").exists()


def test_e2e_rebuild_memory(la_env, tmp_path: Path):
    doc = tmp_path / "rebuild.md"
    doc.write_text("# Rebuild\n\nrebuild test content here", encoding="utf-8")
    run_la(["add-file", str(doc)], env=la_env)
    run_la(["reset-memory"], env=la_env)

    result = run_la(["rebuild-memory"], env=la_env)
    assert result.returncode == 0
    assert "rebuild-memory" in result.stdout


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
    env.pop("MINIMAX_API_KEY", None)
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

    result = run_la(["add-file", "--background", str(doc)], env=la_env)
    assert result.returncode == 0
    assert "后台任务" in result.stdout
    assert "软链:" in result.stdout
    assert "日志:" in result.stdout

    task_id = next(line.split()[2] for line in result.stdout.splitlines() if "后台任务" in line)
    status = run_la(["tasks", task_id], env=la_env)
    assert status.returncode == 0
    assert task_id in status.stdout

    for _ in range(30):
        status = run_la(["tasks", task_id], env=la_env)
        if "status: completed" in status.stdout or "status: skipped" in status.stdout:
            break
        if "status: failed" in status.stdout:
            pytest.fail(status.stdout)
        time.sleep(0.2)
    else:
        pytest.fail(f"task did not complete in time:\n{status.stdout}")


def test_e2e_tasks_list(la_env, tmp_path: Path):
    doc = tmp_path / "list.md"
    doc.write_text("# List\n\ntasks list test", encoding="utf-8")
    run_la(["add-file", "--background", str(doc)], env=la_env)

    result = run_la(["tasks"], env=la_env)
    assert result.returncode == 0
    assert "t-" in result.stdout


def test_hindsight_extra_marked_py311_only():
    """README 中 hindsight 安装说明：Python 3.10 应能装包，但跳过 3.11-only 依赖."""
    text = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "hindsight-all" in text
    assert "python_version >= '3.11'" in text
