"""Background ingest worker entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from localagent import config
from localagent.ingest.pipeline import ingest_file
from localagent.ingest.progress import MultiProgressReporter, TaskProgressReporter
from localagent.ingest.task_logs import append_task_log
from localagent.ingest.tasks import TaskStatus, get_task_store


def run_task(task_id: str) -> int:
    store = get_task_store()
    task = store.get(task_id, reconcile=False)
    if task is None:
        print(f"[worker] task not found: {task_id}", file=sys.stderr)
        return 1

    if task.status == TaskStatus.PAUSED:
        append_task_log(task_id, "worker 在暂停状态下不应重启")
        return 1

    store.mark_running(task_id, pid=__import__("os").getpid())
    append_task_log(task_id, f"开始索引: {task.filename}")
    reporter = MultiProgressReporter([TaskProgressReporter(task_id)])

    try:
        result = ingest_file(Path(task.target_path), reporter=reporter)
        store.complete(task_id, result)
        return 0 if result.status.value != "failed" else 1
    except KeyboardInterrupt:
        store.fail(task_id, "用户中断 (KeyboardInterrupt)")
        append_task_log(task_id, "用户中断")
        return 130
    except Exception as exc:
        store.fail(task_id, str(exc))
        return 1


def main(argv: list[str] | None = None) -> int:
    config.ensure_data_dirs()
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m localagent.ingest.worker <task_id>", file=sys.stderr)
        return 2
    return run_task(args[0])


if __name__ == "__main__":
    raise SystemExit(main())
