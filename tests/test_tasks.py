"""Tests for ingest background tasks and progress."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from localagent import config
from localagent.ingest.add_file import add_file_background, restart_background_task
from localagent.ingest.pipeline import IngestStatus
from localagent.ingest.task_logs import read_task_log
from localagent.ingest.tasks import TaskStatus, get_task_store
from localagent.ingest.worker import run_task

from conftest import write_doc


def test_add_file_background_creates_task(tmp_path: Path):
    source = write_doc(tmp_path / "bg.md", "# BG\n\nbackground ingest test content here")
    target, task, pid = add_file_background(source)

    assert target.is_symlink()
    assert task.id.startswith("t-")
    assert pid > 0
    assert task.log_path
    assert Path(task.log_path).exists()

    store = get_task_store()
    loaded = store.get(task.id)
    assert loaded is not None
    assert loaded.status in (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.COMPLETED)
    log = read_task_log(task.id)
    assert "任务已创建" in log
    assert "spawn worker" in log


def test_worker_completes_task(tmp_path: Path, isolated_data):
    source = write_doc(tmp_path / "worker.md", "# Worker\n\nworker task test content")
    _, task, _ = add_file_background(source)

    with patch("localagent.ingest.worker.ingest_file") as mock_ingest:
        from localagent.ingest.pipeline import IngestResult

        mock_ingest.return_value = IngestResult(
            filename="worker.md",
            path=str(config.KB_DIR / "worker.md"),
            status=IngestStatus.NEW,
            memory_fact_count=2,
            knowledge_chunk_count=3,
        )
        rc = run_task(task.id)

    assert rc == 0
    loaded = get_task_store().get(task.id)
    assert loaded is not None
    assert loaded.status == TaskStatus.COMPLETED
    assert loaded.memory_fact_count == 2
    assert "完成" in read_task_log(task.id)


def test_task_delete(tmp_path: Path):
    source = write_doc(tmp_path / "del.md", "# Del\n\ndelete task test content")
    _, task, _ = add_file_background(source)

    with patch("localagent.ingest.tasks._kill_pid", return_value=True):
        deleted = get_task_store().delete(task.id)

    assert deleted is not None
    assert get_task_store().get(task.id) is None
    assert not Path(task.log_path).exists()


def test_task_pause_and_resume(tmp_path: Path):
    source = write_doc(tmp_path / "pause.md", "# Pause\n\npause task test content")
    _, task, pid = add_file_background(source)

    with patch("localagent.ingest.tasks._pid_alive", return_value=True), patch(
        "localagent.ingest.tasks.os.kill"
    ) as mock_kill:
        paused = get_task_store().pause(task.id)
        assert paused is not None
        assert paused.status == TaskStatus.PAUSED
        mock_kill.assert_called()

        resumed = get_task_store().resume(task.id)
        assert resumed is not None
        assert resumed.status == TaskStatus.RUNNING


def test_task_restart(tmp_path: Path):
    source = write_doc(tmp_path / "restart.md", "# Restart\n\nrestart task test content")
    _, task, _ = add_file_background(source)

    with patch("localagent.ingest.worker.ingest_file") as mock_ingest:
        from localagent.ingest.pipeline import IngestResult

        mock_ingest.return_value = IngestResult(
            filename="restart.md",
            path=str(config.KB_DIR / "restart.md"),
            status=IngestStatus.FAILED,
            error="boom",
        )
        run_task(task.id)

    with patch("localagent.ingest.add_file.spawn_background_task", return_value=99999) as mock_spawn:
        restarted, pid = restart_background_task(task.id)

    assert pid == 99999
    assert restarted.status == TaskStatus.QUEUED
    mock_spawn.assert_called_once()
    assert "任务重启中" in read_task_log(task.id)


def test_task_reconcile_stale(tmp_path: Path):
    import json

    source = write_doc(tmp_path / "stale.md", "# Stale\n\nstale task test content")
    _, task, _ = add_file_background(source)

    store = get_task_store()
    data = json.loads(config.INGEST_TASKS_FILE.read_text(encoding="utf-8"))
    for item in data["tasks"]:
        if item["id"] == task.id:
            item["status"] = "running"
            item["pid"] = 999999
    config.INGEST_TASKS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    with patch("localagent.ingest.tasks._pid_alive", return_value=False):
        changed = store.reconcile_stale()

    assert changed >= 1
    loaded = store.get(task.id, reconcile=False)
    assert loaded is not None
    assert loaded.status == TaskStatus.FAILED


def test_foreground_add_file_shows_progress(tmp_path: Path, capsys):
    source = write_doc(
        tmp_path / "progress.md",
        "# Progress\n\n## A\n\nsection one\n\n## B\n\nsection two",
    )
    from localagent.ingest.add_file import add_file
    from localagent.ingest.progress import ConsoleProgressReporter

    add_file(source, reporter=ConsoleProgressReporter(prefix="add-file"))
    out = capsys.readouterr().out
    assert "源文件" in out
    assert "加载文件" in out
    assert "切分" in out
