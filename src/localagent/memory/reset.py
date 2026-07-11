"""Memory reset and rebuild helpers."""

from __future__ import annotations

from localagent import config
from localagent.ingest.sync_file import SyncSummary, sync_files
from localagent.ingest.sync_index import get_sync_index, reset_sync_index_singleton
from localagent.knowledge.indexer import get_knowledge_indexer, reset_knowledge_indexer
from localagent.knowledge.store import get_knowledge_store, reset_knowledge_store_singleton
from localagent.ingest.progress import ProgressEvent, ProgressReporter
from localagent.memory.hindsight_client import get_memory_backend, reset_memory_backend
from localagent.memory.store import get_memory_store, reset_memory_store_singleton


def reset_memory(
    *,
    clear_knowledge: bool = True,
    reporter: ProgressReporter | None = None,
) -> dict[str, int | bool]:
    """Clear memory store and sync_index; optionally clear knowledge index."""
    config.ensure_data_dirs()

    def _report(message: str) -> None:
        if reporter is not None:
            reporter.update(ProgressEvent(phase="reset", message=message))

    _report("清空记忆存储…")
    backend = get_memory_backend()
    memory_removed = backend.clear()

    memory_store = get_memory_store()
    memory_removed = max(memory_removed, memory_store.count())
    memory_store.clear()
    memory_store.save()

    _report("清空 sync_index…")
    sync_index = get_sync_index()
    sync_files_tracked = len(sync_index.all_filenames())
    sync_index.clear()
    sync_index.save()

    knowledge_removed = 0
    if clear_knowledge:
        _report("清空知识库索引…")
        indexer = get_knowledge_indexer()
        knowledge_removed = indexer.count()
        indexer.clear()
        legacy = get_knowledge_store()
        legacy.clear()
        legacy.save()
    else:
        _report("保留知识库索引")

    reset_memory_store_singleton()
    reset_knowledge_store_singleton()
    reset_sync_index_singleton()
    reset_knowledge_indexer()
    reset_memory_backend()

    if config.SYNC_INDEX_FILE.exists():
        config.SYNC_INDEX_FILE.unlink()

    _report("重置完成")
    return {
        "memory_facts_removed": memory_removed,
        "sync_index_entries_removed": sync_files_tracked,
        "knowledge_chunks_removed": knowledge_removed,
        "clear_knowledge": clear_knowledge,
    }


def rebuild_memory(
    *,
    reporter: ProgressReporter | None = None,
) -> tuple[dict[str, int | bool], SyncSummary]:
    """Reset memory then force re-index all kb/ documents."""
    reset_stats = reset_memory(clear_knowledge=True, reporter=reporter)
    if reporter is not None:
        reporter.update(ProgressEvent(phase="rebuild", message="重新索引 kb/ 文档…"))
    summary = sync_files(force=True, reporter=reporter)
    return reset_stats, summary
