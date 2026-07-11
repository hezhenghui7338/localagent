"""Progress reporting for ingest operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ProgressEvent:
    phase: str
    message: str
    current: int = 0
    total: int = 0


class ProgressReporter(Protocol):
    def update(self, event: ProgressEvent) -> None: ...


class ConsoleProgressReporter:
    def __init__(self, *, prefix: str = "add-file") -> None:
        self.prefix = prefix

    def update(self, event: ProgressEvent) -> None:
        if event.total > 0:
            print(
                f"[{self.prefix}] {event.message} ({event.current}/{event.total})",
                flush=True,
            )
        else:
            print(f"[{self.prefix}] {event.message}", flush=True)


class TaskProgressReporter:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id

    def update(self, event: ProgressEvent) -> None:
        from localagent.ingest.task_logs import append_task_log
        from localagent.ingest.tasks import get_task_store

        get_task_store().update_progress(
            self.task_id,
            phase=event.phase,
            message=event.message,
            current=event.current,
            total=event.total,
        )
        if event.total > 0:
            append_task_log(
                self.task_id,
                f"{event.message} ({event.current}/{event.total})",
            )
        else:
            append_task_log(self.task_id, event.message)


class MultiProgressReporter:
    def __init__(self, reporters: list[ProgressReporter]) -> None:
        self._reporters = reporters

    def update(self, event: ProgressEvent) -> None:
        for reporter in self._reporters:
            reporter.update(event)
