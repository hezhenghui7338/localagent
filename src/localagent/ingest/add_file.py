"""LA add-file: symlink into data/kb/ and index with optional background task."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from localagent import config
from localagent.audit.events import log_event
from localagent.audit.security import is_sensitive_path, sensitive_path_reason
from localagent.ingest.pipeline import IngestResult, ingest_file
from localagent.ingest.progress import ConsoleProgressReporter, MultiProgressReporter, ProgressEvent
from localagent.ingest.task_logs import append_task_log, ensure_task_log
from localagent.ingest.tasks import IngestTask, get_task_store


class SensitiveIngestError(ValueError):
    """Raised when add-file / ingest refuses a sensitive path."""


def _format_size(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return "unknown size"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def prepare_symlink(source_path: str | Path) -> tuple[Path, Path]:
    """Validate source file and create symlink in kb/."""
    config.ensure_data_dirs()
    source = Path(source_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"source not found: {source}")
    if not source.is_file():
        raise ValueError(f"not a file: {source}")

    if is_sensitive_path(source):
        reason = sensitive_path_reason(source)
        log_event(
            "kb.blocked",
            policy_id="kb.sensitive_path",
            action="block",
            path=str(source),
            reason=reason,
        )
        log_event(
            "guardrail.triggered",
            policy_id="kb.sensitive_path",
            action="block",
            path=str(source),
            reason=reason,
        )
        raise SensitiveIngestError(reason)

    suffix = source.suffix.lower()
    if suffix not in config.SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(config.SUPPORTED_SUFFIXES))
        raise ValueError(f"unsupported file type {suffix!r}; supported: {supported}")

    target = config.KB_DIR / source.name
    if target.exists() or target.is_symlink():
        if target.is_symlink():
            target.unlink()
        elif target.is_file():
            raise FileExistsError(
                f"kb entry already exists and is not a symlink: {target}"
            )
        else:
            raise FileExistsError(f"kb entry already exists: {target}")

    os.symlink(source, target)
    log_event("kb.ingest", path=str(source), target=str(target), phase="symlink")
    return source, target


def index_file(
    target: Path,
    *,
    reporter: MultiProgressReporter | ConsoleProgressReporter | None = None,
) -> IngestResult:
    return ingest_file(target, force=False, reporter=reporter)


def add_file(
    source_path: str | Path,
    *,
    reporter: MultiProgressReporter | ConsoleProgressReporter | None = None,
) -> tuple[Path, IngestResult]:
    """Create symlink in kb/ and index the file."""
    source = Path(source_path).expanduser().resolve()
    if reporter is not None:
        reporter.update(
            ProgressEvent(
                phase="prepare",
                message=f"源文件: {source} ({_format_size(source)})",
            )
        )

    source, target = prepare_symlink(source_path)
    if reporter is not None:
        reporter.update(
            ProgressEvent(
                phase="symlink",
                message=f"软链已创建 → {target}",
            )
        )
    result = index_file(target, reporter=reporter)
    return target, result


def spawn_background_task(task: IngestTask) -> int:
    log_path = ensure_task_log(task.id)
    append_task_log(task.id, "spawn worker…")

    env = os.environ.copy()
    log_file = log_path.open("a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "localagent.ingest.worker", task.id],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        log_file.close()
    get_task_store().mark_running(task.id, pid=proc.pid)
    return proc.pid


def add_file_background(source_path: str | Path) -> tuple[Path, IngestTask, int]:
    """Symlink immediately and index in a detached background worker."""
    source = Path(source_path).expanduser().resolve()
    source, target = prepare_symlink(source_path)
    task = get_task_store().create_add_file(
        source_path=str(source),
        target_path=str(target),
        filename=target.name,
    )
    append_task_log(task.id, f"文件大小: {_format_size(source)}")
    pid = spawn_background_task(task)
    return target, task, pid


def restart_background_task(task_id: str) -> tuple[IngestTask, int]:
    """Restart a finished or failed background task."""
    store = get_task_store()
    task = store.prepare_restart(task_id)
    if task is None:
        raise ValueError(f"task not found: {task_id}")
    pid = spawn_background_task(task)
    return task, pid
