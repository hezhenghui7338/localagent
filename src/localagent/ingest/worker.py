"""Background ingest / memorize worker entry point."""

from __future__ import annotations

import sys
from pathlib import Path

from localagent import config
from localagent.ingest.pipeline import ingest_file
from localagent.ingest.progress import MultiProgressReporter, TaskProgressReporter
from localagent.ingest.task_logs import append_task_log
from localagent.ingest.tasks import TaskStatus, get_task_store


def run_add_file(task_id: str, *, target_path: str, filename: str) -> int:
    store = get_task_store()
    append_task_log(task_id, f"开始索引: {filename}")
    reporter = MultiProgressReporter([TaskProgressReporter(task_id)])
    try:
        result = ingest_file(Path(target_path), reporter=reporter)
        store.complete(task_id, result)
        return 0 if result.status.value != "failed" else 1
    except KeyboardInterrupt:
        store.fail(task_id, "用户中断 (KeyboardInterrupt)")
        append_task_log(task_id, "用户中断")
        return 130
    except Exception as exc:
        store.fail(task_id, str(exc))
        return 1


def run_memorize_session(task_id: str, *, session_id: str) -> int:
    store = get_task_store()
    append_task_log(task_id, f"开始会话记忆化: {session_id}")
    store.update_progress(task_id, phase="extract", message="提取会话记忆")
    try:
        from localagent.memory.exit_extract import extract_session_memories

        ids = extract_session_memories(session_id, interactive=False)
        store.update_progress(
            task_id,
            phase="consolidate",
            message="巩固完成（写入阶段已处理）",
            current=len(ids),
            total=max(len(ids), 1),
        )
        store.complete_counts(
            task_id,
            memory_fact_count=len(ids),
            message=f"会话记忆化完成 ({len(ids)} facts)",
        )
        return 0
    except KeyboardInterrupt:
        store.fail(task_id, "用户中断 (KeyboardInterrupt)")
        append_task_log(task_id, "用户中断")
        return 130
    except Exception as exc:
        store.fail(task_id, str(exc))
        return 1


def run_consolidate(task_id: str, *, limit: int = 40) -> int:
    store = get_task_store()
    append_task_log(task_id, f"开始记忆巩固: recent={limit}")
    store.update_progress(task_id, phase="consolidate", message="扫描并巩固近期记忆")
    try:
        from localagent.memory.consolidate import consolidate_recent

        report = consolidate_recent(limit=limit)
        append_task_log(
            task_id,
            f"actions={len(report.actions)} retained={len(report.retained_ids)} "
            f"updated={len(report.updated_ids)} deleted={len(report.deleted_ids)} "
            f"noop={report.noop_count}",
        )
        if report.errors:
            append_task_log(task_id, f"errors={';'.join(report.errors[:5])}")
        store.complete_counts(
            task_id,
            memory_fact_count=report.changed,
            message=(
                f"巩固完成 changed={report.changed} "
                f"(+{len(report.retained_ids)} ~{len(report.updated_ids)} "
                f"-{len(report.deleted_ids)} noop={report.noop_count})"
            ),
        )
        return 0
    except KeyboardInterrupt:
        store.fail(task_id, "用户中断 (KeyboardInterrupt)")
        append_task_log(task_id, "用户中断")
        return 130
    except Exception as exc:
        store.fail(task_id, str(exc))
        return 1


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

    if task.type == "memorize_session":
        return run_memorize_session(task_id, session_id=task.source_path)
    if task.type == "consolidate":
        try:
            limit = int(task.source_path or "40")
        except ValueError:
            limit = 40
        return run_consolidate(task_id, limit=limit)
    # Default / legacy: file ingest
    return run_add_file(task_id, target_path=task.target_path, filename=task.filename)


def main(argv: list[str] | None = None) -> int:
    config.ensure_data_dirs()
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m localagent.ingest.worker <task_id>", file=sys.stderr)
        return 2
    return run_task(args[0])


if __name__ == "__main__":
    raise SystemExit(main())
