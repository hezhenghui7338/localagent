"""Background ingest task tracking."""

from __future__ import annotations

import json
import os
import signal
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from localagent import config
from localagent.ingest.pipeline import IngestResult, IngestStatus
from localagent.ingest.task_logs import append_task_log, delete_task_log, ensure_task_log, read_task_log


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.PAUSED)


@dataclass
class IngestTask:
    id: str
    type: str
    status: TaskStatus
    source_path: str
    target_path: str
    filename: str
    created_at: str
    updated_at: str
    pid: int | None = None
    phase: str = ""
    message: str = ""
    progress_current: int = 0
    progress_total: int = 0
    memory_fact_count: int = 0
    knowledge_chunk_count: int = 0
    result_status: str = ""
    error: str = ""
    log_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status.value,
            "source_path": self.source_path,
            "target_path": self.target_path,
            "filename": self.filename,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pid": self.pid,
            "phase": self.phase,
            "message": self.message,
            "progress_current": self.progress_current,
            "progress_total": self.progress_total,
            "memory_fact_count": self.memory_fact_count,
            "knowledge_chunk_count": self.knowledge_chunk_count,
            "result_status": self.result_status,
            "error": self.error,
            "log_path": self.log_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IngestTask:
        return cls(
            id=data["id"],
            type=data.get("type", "add_file"),
            status=TaskStatus(data["status"]),
            source_path=data.get("source_path", ""),
            target_path=data.get("target_path", ""),
            filename=data.get("filename", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            pid=data.get("pid"),
            phase=data.get("phase", ""),
            message=data.get("message", ""),
            progress_current=int(data.get("progress_current", 0)),
            progress_total=int(data.get("progress_total", 0)),
            memory_fact_count=int(data.get("memory_fact_count", 0)),
            knowledge_chunk_count=int(data.get("knowledge_chunk_count", 0)),
            result_status=data.get("result_status", ""),
            error=data.get("error", ""),
            log_path=data.get("log_path", ""),
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_tasks() -> list[IngestTask]:
    if not config.INGEST_TASKS_FILE.exists():
        return []
    try:
        raw = json.loads(config.INGEST_TASKS_FILE.read_text(encoding="utf-8"))
        return [IngestTask.from_dict(item) for item in raw.get("tasks", [])]
    except Exception:
        return []


def _save_tasks(tasks: list[IngestTask]) -> None:
    config.ensure_data_dirs()
    config.INGEST_TASKS_FILE.write_text(
        json.dumps({"tasks": [t.to_dict() for t in tasks]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


def _kill_pid(pid: int | None, *, sig: signal.Signals = signal.SIGTERM) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    else:
        return True


class TaskStore:
    def list_tasks(self, *, limit: int = 20, reconcile: bool = True) -> list[IngestTask]:
        if reconcile:
            self.reconcile_stale()
        tasks = sorted(_load_tasks(), key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    def get(self, task_id: str, *, reconcile: bool = True) -> IngestTask | None:
        if reconcile:
            self.reconcile_stale()
        for task in _load_tasks():
            if task.id == task_id:
                return task
        return None

    def create_add_file(self, *, source_path: str, target_path: str, filename: str) -> IngestTask:
        tasks = _load_tasks()
        now = _now()
        task_id = f"t-{uuid.uuid4().hex[:8]}"
        log_path = str(ensure_task_log(task_id))
        task = IngestTask(
            id=task_id,
            type="add_file",
            status=TaskStatus.QUEUED,
            source_path=source_path,
            target_path=target_path,
            filename=filename,
            created_at=now,
            updated_at=now,
            message="等待开始",
            log_path=log_path,
        )
        append_task_log(task_id, f"任务已创建: {filename}")
        append_task_log(task_id, f"source: {source_path}")
        append_task_log(task_id, f"symlink: {target_path}")
        tasks.append(task)
        _save_tasks(tasks)
        return task

    def mark_running(self, task_id: str, *, pid: int) -> None:
        tasks = _load_tasks()
        for task in tasks:
            if task.id != task_id:
                continue
            task.status = TaskStatus.RUNNING
            task.pid = pid
            task.phase = "start"
            task.message = "开始索引"
            task.updated_at = _now()
            break
        _save_tasks(tasks)
        append_task_log(task_id, f"worker 启动 pid={pid}")

    def update_progress(
        self,
        task_id: str,
        *,
        phase: str,
        message: str,
        current: int = 0,
        total: int = 0,
    ) -> None:
        tasks = _load_tasks()
        for task in tasks:
            if task.id != task_id:
                continue
            if task.status == TaskStatus.QUEUED:
                task.status = TaskStatus.RUNNING
            task.phase = phase
            task.message = message
            task.progress_current = current
            task.progress_total = total
            task.updated_at = _now()
            break
        _save_tasks(tasks)

    def complete(self, task_id: str, result: IngestResult) -> None:
        tasks = _load_tasks()
        for task in tasks:
            if task.id != task_id:
                continue
            if result.status == IngestStatus.FAILED:
                task.status = TaskStatus.FAILED
                task.error = result.error
            elif result.status == IngestStatus.SKIPPED:
                task.status = TaskStatus.SKIPPED
            else:
                task.status = TaskStatus.COMPLETED
            task.phase = "done"
            task.message = "索引完成"
            task.memory_fact_count = result.memory_fact_count
            task.knowledge_chunk_count = result.knowledge_chunk_count
            task.result_status = result.status.value
            task.pid = None
            task.updated_at = _now()
            break
        _save_tasks(tasks)
        append_task_log(
            task_id,
            f"完成: status={result.status.value} "
            f"facts={result.memory_fact_count} chunks={result.knowledge_chunk_count}",
        )

    def fail(self, task_id: str, error: str) -> None:
        tasks = _load_tasks()
        for task in tasks:
            if task.id != task_id:
                continue
            task.status = TaskStatus.FAILED
            task.phase = "done"
            task.message = "索引失败"
            task.error = error
            task.pid = None
            task.updated_at = _now()
            break
        _save_tasks(tasks)
        append_task_log(task_id, f"失败: {error}")

    def reconcile_stale(self) -> int:
        """Mark running tasks whose worker process has exited."""
        tasks = _load_tasks()
        changed = 0
        for task in tasks:
            if not task.log_path:
                task.log_path = str(ensure_task_log(task.id))
                changed += 1
            if task.status not in (TaskStatus.RUNNING, TaskStatus.PAUSED):
                continue
            if _pid_alive(task.pid):
                continue
            task.status = TaskStatus.FAILED
            task.phase = "done"
            task.message = "worker 进程已退出"
            if not task.error:
                task.error = "worker process exited unexpectedly"
            task.pid = None
            task.updated_at = _now()
            changed += 1
            append_task_log(task.id, "检测到 worker 已退出，标记为 failed")
        if changed:
            _save_tasks(tasks)
        return changed

    def delete(self, task_id: str) -> IngestTask | None:
        tasks = _load_tasks()
        target: IngestTask | None = None
        remaining: list[IngestTask] = []
        for task in tasks:
            if task.id == task_id:
                target = task
            else:
                remaining.append(task)
        if target is None:
            return None

        if target.status in (TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.QUEUED):
            if target.status == TaskStatus.PAUSED and target.pid:
                _kill_pid(target.pid, sig=signal.SIGCONT)
            _kill_pid(target.pid, sig=signal.SIGTERM)
            append_task_log(task_id, "任务被删除，已终止 worker")

        _save_tasks(remaining)
        delete_task_log(task_id)
        return target

    def pause(self, task_id: str) -> IngestTask | None:
        task = self.get(task_id, reconcile=True)
        if task is None:
            return None
        if task.status != TaskStatus.RUNNING:
            raise ValueError(f"任务 {task_id} 状态为 {task.status.value}，无法暂停")
        if not _pid_alive(task.pid):
            self.reconcile_stale()
            raise ValueError(f"任务 {task_id} 的 worker 进程不存在")

        os.kill(task.pid, signal.SIGSTOP)
        tasks = _load_tasks()
        for item in tasks:
            if item.id != task_id:
                continue
            item.status = TaskStatus.PAUSED
            item.message = "已暂停"
            item.updated_at = _now()
            task = item
            break
        _save_tasks(tasks)
        append_task_log(task_id, f"任务已暂停 pid={task.pid}")
        return task

    def resume(self, task_id: str) -> IngestTask | None:
        task = self.get(task_id, reconcile=False)
        if task is None:
            return None
        if task.status != TaskStatus.PAUSED:
            raise ValueError(f"任务 {task_id} 状态为 {task.status.value}，无法恢复")
        if not _pid_alive(task.pid):
            self.reconcile_stale()
            raise ValueError(f"任务 {task_id} 的 worker 进程不存在")

        os.kill(task.pid, signal.SIGCONT)
        tasks = _load_tasks()
        for item in tasks:
            if item.id != task_id:
                continue
            item.status = TaskStatus.RUNNING
            item.message = "已恢复运行"
            item.updated_at = _now()
            task = item
            break
        _save_tasks(tasks)
        append_task_log(task_id, f"任务已恢复 pid={task.pid}")
        return task

    def prepare_restart(self, task_id: str) -> IngestTask | None:
        tasks = _load_tasks()
        target: IngestTask | None = None
        for task in tasks:
            if task.id != task_id:
                continue
            if task.status in (TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.QUEUED):
                raise ValueError(f"任务 {task_id} 仍在运行，请先暂停或删除")
            target = task
            task.status = TaskStatus.QUEUED
            task.pid = None
            task.phase = ""
            task.message = "等待重启"
            task.progress_current = 0
            task.progress_total = 0
            task.memory_fact_count = 0
            task.knowledge_chunk_count = 0
            task.result_status = ""
            task.error = ""
            task.updated_at = _now()
            break
        if target is None:
            return None
        _save_tasks(tasks)
        append_task_log(task_id, "任务重启中…")
        return target

    def get_log_text(self, task_id: str, *, tail: int = 50) -> str:
        return read_task_log(task_id, tail=tail)


_store: TaskStore | None = None


def get_task_store() -> TaskStore:
    global _store
    if _store is None:
        _store = TaskStore()
    return _store


def reset_task_store() -> None:
    global _store
    _store = None


def format_task_line(task: IngestTask) -> str:
    if task.status == TaskStatus.RUNNING and task.progress_total > 0:
        progress = f" {task.phase} {task.progress_current}/{task.progress_total}"
    elif task.status == TaskStatus.PAUSED:
        progress = " (paused)"
    elif task.phase:
        progress = f" {task.phase}"
    else:
        progress = ""

    if task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
        detail = f" facts={task.memory_fact_count} chunks={task.knowledge_chunk_count}"
    elif task.status == TaskStatus.FAILED:
        detail = f" !{task.error[:60]}"
    else:
        detail = ""

    return f"  {task.id} [{task.status.value}] {task.filename}{progress}{detail}  {task.updated_at}"
