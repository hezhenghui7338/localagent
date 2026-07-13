"""Memory reset and rebuild helpers."""

from __future__ import annotations

from localagent import config
from localagent.ingest.sync_file import SyncSummary, sync_files
from localagent.ingest.sync_index import get_sync_index, reset_sync_index_singleton
from localagent.knowledge.indexer import get_knowledge_indexer, reset_knowledge_indexer
from localagent.knowledge.store import get_knowledge_store, reset_knowledge_store_singleton
from localagent.ingest.progress import ProgressEvent, ProgressReporter
from localagent.memory.backend import get_memory_backend, reset_memory_backend
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


def reindex_memory_engine(
    *,
    reporter: ProgressReporter | None = None,
) -> dict[str, int | str]:
    """Rebuild Warm engine (Mem0) from JSON registry without wiping facts."""

    def _report(message: str) -> None:
        if reporter is not None:
            reporter.update(ProgressEvent(phase="reindex", message=message))

    config.ensure_data_dirs()
    backend = get_memory_backend()
    if backend.backend_name() != "mem0":
        _report(f"当前后端为 {backend.backend_name()}，跳过引擎重建")
        return {
            "reindexed": 0,
            "backend": backend.backend_name(),
            "skipped": 1,
        }

    _report("从 memory_store.json 重建 Mem0 索引…")
    reindex = getattr(backend, "reindex_from_registry", None)
    count = int(reindex()) if callable(reindex) else 0
    _report(f"已重建 {count} 条")
    return {"reindexed": count, "backend": "mem0", "skipped": 0}


def rebuild_memory(
    *,
    reporter: ProgressReporter | None = None,
) -> tuple[dict[str, int | bool], SyncSummary]:
    """Reset memory then force re-index all kb/ documents."""
    store = get_memory_store()
    snapshot = [fact.to_dict() for fact in store.all_facts()]

    reset_stats = reset_memory(clear_knowledge=True, reporter=reporter)
    if reporter is not None:
        reporter.update(ProgressEvent(phase="rebuild", message="重新索引 kb/ 文档…"))
    summary = sync_files(force=True, reporter=reporter)

    if snapshot:
        if reporter is not None:
            reporter.update(ProgressEvent(phase="rebuild", message="恢复非文档来源记忆…"))
        backend = get_memory_backend()
        existing_texts = {f.text.strip() for f in get_memory_store().all_facts()}
        for item in snapshot:
            text = str(item.get("text") or "").strip()
            source_file = str(item.get("source_file") or "")
            if not text or text in existing_texts:
                continue
            if source_file and (config.KB_DIR / source_file).exists():
                continue
            meta = dict(item.get("metadata") or {})
            meta["source_file"] = source_file
            meta["section_heading"] = (
                item.get("section_heading") or meta.get("section_heading") or "rebuild"
            )
            backend.retain(text, metadata=meta)

    return reset_stats, summary
