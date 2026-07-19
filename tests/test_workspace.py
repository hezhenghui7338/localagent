"""Tests for workspace context, diagnostic scan, and managed tasks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from localagent.cli import main
from localagent.workspace.context import (
    format_workspace_summary,
    git_summary,
    recent_files,
    scan_todos,
)
from localagent.workspace.tasks import (
    TaskRejected,
    add_task,
    dismiss,
    done,
    list_open,
    load_tasks,
    propose_task,
    purge,
    snooze,
    task_count_open,
)
import pytest


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


def test_scan_todos_ignores_substring_false_positives(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "noise.py").write_text(
        "todos = scan_todos(tmp_path)\n"
        "todo_count=3,\n"
        "print('TODOs | shell context')\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "real.py").write_text(
        "# TODO: real issue here\n",
        encoding="utf-8",
    )
    todos = scan_todos(tmp_path)
    texts = {t["text"] for t in todos}
    assert "real issue here" in texts
    assert not any(t.startswith("s ") or t.startswith("s=") or "_count" in t for t in texts)


def test_scan_todos_skips_tests_and_docs(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "tests" / "t.py").write_text("# TODO: should skip\n", encoding="utf-8")
    (tmp_path / "docs" / "x.md").write_text("- [ ] should skip docs\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("# TODO: keep this one\n", encoding="utf-8")
    todos = scan_todos(tmp_path)
    texts = {t["text"] for t in todos}
    assert "keep this one" in texts
    assert "should skip" not in texts
    assert "should skip docs" not in texts


def test_recent_files_lists_modified(tmp_path: Path):
    path = tmp_path / "changed.txt"
    path.write_text("hello", encoding="utf-8")
    files = recent_files(tmp_path, days=7, limit=10)
    assert any(f["path"] == "changed.txt" for f in files)


def test_git_summary_non_repo(tmp_path: Path):
    summary = git_summary(tmp_path)
    assert summary.is_repo is False
    assert "不是 git 仓库" in summary.to_text()


def test_format_workspace_summary_includes_managed_tasks(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LA_WORKSPACE", str(tmp_path))
    add_task("修登录", "阻塞发版的高优先级缺陷", workspace=tmp_path)

    text = format_workspace_summary(days=7, workspace=tmp_path)
    assert "工作区:" in text
    assert "托管待办" in text
    assert "修登录" in text


def test_cli_workspace_diagnostic_scan(tmp_path: Path, capsys):
    (tmp_path / "todo.md").write_text("# TODO: cli test item\n", encoding="utf-8")
    rc = main(["workspace", "--cwd", str(tmp_path), "--todos-only"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cli test item" in out
    assert "未入队" in out


def test_cli_workspace_task_lifecycle(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("LA_WORKSPACE", str(tmp_path))
    rc = main(
        [
            "workspace",
            "add",
            "发布检查",
            "--why",
            "用户指定的发版前核对清单",
            "--cwd",
            str(tmp_path),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "已添加" in out
    assert task_count_open(tmp_path) == 1
    tid = list_open(tmp_path)[0].id

    rc = main(["workspace", "tasks", "--cwd", str(tmp_path)])
    assert rc == 0
    assert "发布检查" in capsys.readouterr().out

    rc = main(["workspace", "done", tid, "--cwd", str(tmp_path)])
    assert rc == 0
    assert task_count_open(tmp_path) == 0


def test_add_task_requires_rationale(tmp_path: Path):
    with pytest.raises(TaskRejected):
        add_task("x", "足够长的理由文本", workspace=tmp_path)
    with pytest.raises(TaskRejected):
        add_task("足够长的标题", "短", workspace=tmp_path)


def test_task_ttl_expires(tmp_path: Path, monkeypatch):
    task = add_task(
        "会过期的任务",
        "用于验证 TTL 懒过期逻辑",
        workspace=tmp_path,
        ttl_days=1,
    )
    # Force expires_at into the past
    items = load_tasks(tmp_path, refresh=False)
    for item in items:
        if item.id == task.id:
            item.expires_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    from localagent.workspace.tasks import _save_bucket

    _save_bucket(tmp_path, items)
    opened = list_open(tmp_path)
    assert all(i.id != task.id for i in opened)
    assert any(i.id == task.id and i.status == "expired" for i in load_tasks(tmp_path))


def test_snooze_and_purge(tmp_path: Path):
    task = add_task("可搁置", "用户暂时不想处理但这事重要", workspace=tmp_path)
    snooze(task.id, days=2, workspace=tmp_path)
    assert task_count_open(tmp_path) == 0
    dismiss(task.id, workspace=tmp_path)
    # dismiss after snooze
    assert any(i.status == "dismissed" for i in load_tasks(tmp_path))
    removed = purge(tmp_path)
    assert removed >= 1


def test_propose_task_daily_limit(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("localagent.config.WORKSPACE_TASK_AGENT_DAILY_LIMIT", 1)
    propose_task(
        "测试持续失败",
        "CI 连续失败阻塞合并，需优先排查",
        workspace=tmp_path,
    )
    with pytest.raises(TaskRejected):
        propose_task(
            "另一重大问题",
            "配置失效导致无法启动本地服务",
            workspace=tmp_path,
        )


def test_done_dismiss_paths(tmp_path: Path):
    a = add_task("任务甲", "用户明确要求记录的事项甲", workspace=tmp_path)
    b = add_task("任务乙", "用户明确要求记录的事项乙", workspace=tmp_path)
    done(a.id, workspace=tmp_path)
    dismiss(b.id, workspace=tmp_path)
    assert task_count_open(tmp_path) == 0
