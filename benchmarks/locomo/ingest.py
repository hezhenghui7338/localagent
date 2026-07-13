"""Ingest LoCoMo conversations into LocalAgent long-term memory."""

from __future__ import annotations

from typing import Any, Callable

from benchmarks.locomo.dataset import iter_memory_items


def ingest_sample(
    sample: dict[str, Any],
    *,
    max_turns: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Retain dialog turns for one LoCoMo conversation into the active memory backend."""
    from localagent.memory.backend import get_memory_backend

    backend = get_memory_backend()
    items = list(iter_memory_items(sample))
    if max_turns is not None:
        meta = [item for item in items if item["metadata"].get("kind") == "conversation_meta"]
        dialogs = [item for item in items if item["metadata"].get("kind") != "conversation_meta"]
        items = meta + dialogs[: max(0, max_turns)]

    written = 0
    skipped = 0
    total = len(items)
    for index, item in enumerate(items, start=1):
        fact_id = backend.retain(item["text"], metadata=dict(item["metadata"]))
        if fact_id:
            written += 1
        else:
            skipped += 1
        if on_progress is not None and (index == total or index % 50 == 0):
            on_progress(index, total)

    return {
        "sample_id": sample.get("sample_id"),
        "backend": backend.backend_name(),
        "candidates": total,
        "written": written,
        "skipped": skipped,
        "memory_count": backend.count(),
    }
