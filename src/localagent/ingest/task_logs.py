"""Task log file helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from localagent import config


def task_log_path(task_id: str) -> Path:
    return config.TASK_LOGS_DIR / f"{task_id}.log"


def ensure_task_log(task_id: str) -> Path:
    config.ensure_data_dirs()
    path = task_log_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_task_log(task_id: str, message: str) -> None:
    path = ensure_task_log(task_id)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {message}\n")


def read_task_log(task_id: str, *, tail: int = 50) -> str:
    path = task_log_path(task_id)
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    if tail <= 0 or tail >= len(lines):
        return "\n".join(lines)
    return "\n".join(lines[-tail:])


def delete_task_log(task_id: str) -> None:
    path = task_log_path(task_id)
    if path.exists():
        path.unlink()
