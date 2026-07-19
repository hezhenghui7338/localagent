"""Memory and ingest health metrics for audit reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from localagent import config
from localagent.i18n import t
from localagent.ingest.sync_index import get_sync_index
from localagent.memory.store import get_memory_store


@dataclass
class MemoryHealth:
    memory_facts: int = 0
    kb_files: int = 0
    indexed_files: int = 0
    orphan_kb_entries: list[str] = field(default_factory=list)
    missing_kb_files: list[str] = field(default_factory=list)
    failed_tasks: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_facts": self.memory_facts,
            "kb_files": self.kb_files,
            "indexed_files": self.indexed_files,
            "orphan_kb_entries": self.orphan_kb_entries,
            "missing_kb_files": self.missing_kb_files,
            "failed_tasks": self.failed_tasks,
            "notes": self.notes,
        }

    def to_text(self) -> str:
        lines = [
            t("audit.health_facts", n=self.memory_facts),
            t("audit.health_kb", kb=self.kb_files, indexed=self.indexed_files),
        ]
        if self.failed_tasks:
            lines.append(t("audit.health_failed", n=self.failed_tasks))
        if self.orphan_kb_entries:
            lines.append(t("audit.health_orphan", n=len(self.orphan_kb_entries)))
        if self.missing_kb_files:
            lines.append(t("audit.health_missing", n=len(self.missing_kb_files)))
        for note in self.notes:
            lines.append(f"  ! {note}")
        return "\n".join(lines)


def collect_memory_health() -> MemoryHealth:
    health = MemoryHealth()
    health.memory_facts = get_memory_store().count()

    kb_names = set()
    if config.KB_DIR.is_dir():
        for entry in config.KB_DIR.iterdir():
            if entry.is_file() or entry.is_symlink():
                kb_names.add(entry.name)
    health.kb_files = len(kb_names)

    index = get_sync_index()
    indexed = set(index.all_filenames())
    health.indexed_files = len(indexed)

    health.orphan_kb_entries = sorted(indexed - kb_names)
    health.missing_kb_files = sorted(kb_names - indexed)

    try:
        # Lazy import: avoid tasks ↔ pipeline ↔ audit circular import at module load.
        from localagent.ingest.tasks import TaskStatus, get_task_store

        tasks = get_task_store().list_tasks(limit=50, reconcile=False)
        health.failed_tasks = sum(1 for task in tasks if task.status == TaskStatus.FAILED)
    except Exception:
        pass

    if health.missing_kb_files:
        health.notes.append(t("audit.health_note_ingest"))
    return health
