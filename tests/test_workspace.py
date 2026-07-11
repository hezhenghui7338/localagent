"""Tests for workspace context (git, recent files, todos)."""

from __future__ import annotations

from pathlib import Path

from localagent.cli import main
from localagent.workspace.context import (
    format_workspace_summary,
    git_summary,
    recent_files,
    scan_todos,
)


def test_scan_todos_finds_markers(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "# app\n# TODO: fix login bug\n",
        encoding="utf-8",
    )
    (tmp_path / "notes.md").write_text("- [ ] 完成 Phase 1\n", encoding="utf-8")

    todos = scan_todos(tmp_path)
    texts = {t["text"] for t in todos}
    assert "fix login bug" in texts
    assert "完成 Phase 1" in texts


def test_recent_files_lists_modified(tmp_path: Path):
    path = tmp_path / "changed.txt"
    path.write_text("hello", encoding="utf-8")
    files = recent_files(tmp_path, days=7, limit=10)
    assert any(f["path"] == "changed.txt" for f in files)


def test_git_summary_non_repo(tmp_path: Path):
    summary = git_summary(tmp_path)
    assert summary.is_repo is False
    assert "不是 git 仓库" in summary.to_text()


def test_format_workspace_summary_includes_sections(tmp_path: Path, monkeypatch):
    (tmp_path / "task.md").write_text("- [ ] ship audit\n", encoding="utf-8")
    monkeypatch.setenv("LA_WORKSPACE", str(tmp_path))

    text = format_workspace_summary(days=7, workspace=tmp_path)
    assert "工作区:" in text
    assert "待办" in text or "task.md" in text


def test_cli_workspace_command(tmp_path: Path, capsys):
    (tmp_path / "todo.md").write_text("# TODO: cli test\n", encoding="utf-8")
    rc = main(["workspace", "--cwd", str(tmp_path), "--todos-only"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cli test" in out
