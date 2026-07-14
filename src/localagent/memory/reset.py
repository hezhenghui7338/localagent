"""Memory reset and rebuild helpers."""

from __future__ import annotations

from localagent import config
from localagent.ingest.sync_file import SyncSummary, sync_files
from localagent.ingest.sync_index import get_sync_index, reset_sync_index_singleton
from localagent.knowledge.indexer import get_knowledge_indexer, reset_knowledge_indexer
from localagent.knowledge.store import get_knowledge_store, reset_knowledge_store_singleton
from localagent.ingest.progress import ProgressEvent, ProgressReporter
from localagent.memory.backend import get_memory_backend, reset_memory_backend
from localagent.memory.chatgpt_import import reset_chatgpt_import_index
from localagent.memory.rememorize import reset_chat_ingest_index
from localagent.memory.store import get_memory_store, reset_memory_store_singleton

# metadata.source values grouped by LA memory reset / ingest origin
SOURCE_GROUPS: dict[str, frozenset[str]] = {
    "chat": frozenset({"chat", "rememorize-chat", "chat_explicit"}),
    "file": frozenset({"ingest"}),
    "chatgpt": frozenset({"import-chatgpt", "import-chatgpt-memory"}),
}


def _fact_source(fact) -> str:
    meta = fact.metadata or {}
    return str(meta.get("source") or "")


def _delete_facts_by_sources(
    sources: frozenset[str],
    *,
    reporter: ProgressReporter | None = None,
) -> int:
    backend = get_memory_backend()
    store = get_memory_store()
    removed = 0
    for fact in list(store.all_facts()):
        if _fact_source(fact) not in sources:
            continue
        if backend.delete(fact.id):
            removed += 1
        elif store.delete(fact.id) is not None:
            removed += 1
    if reporter is not None:
        reporter.update(
            ProgressEvent(phase="reset", message=f"已删除 {removed} 条匹配来源的记忆")
        )
    store.save()
    return removed


def _clear_file_indexes(*, clear_knowledge: bool, reporter: ProgressReporter | None) -> tuple[int, int]:
    def _report(message: str) -> None:
        if reporter is not None:
            reporter.update(ProgressEvent(phase="reset", message=message))

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

    reset_sync_index_singleton()
    reset_knowledge_store_singleton()
    reset_knowledge_indexer()
    if config.SYNC_INDEX_FILE.exists():
        config.SYNC_INDEX_FILE.unlink()
    return sync_files_tracked, knowledge_removed


def reset_memory(
    *,
    clear_knowledge: bool = True,
    source: str = "all",
    reporter: ProgressReporter | None = None,
) -> dict[str, int | bool | str]:
    """Clear memory by origin (chat / file / chatgpt / all)."""
    config.ensure_data_dirs()
    origin = (source or "all").strip().lower()
    if origin not in ("all", "chat", "file", "chatgpt"):
        raise ValueError(f"未知来源: {source}（可用: chat, file, chatgpt, all）")

    def _report(message: str) -> None:
        if reporter is not None:
            reporter.update(ProgressEvent(phase="reset", message=message))

    if origin == "all":
        _report("清空记忆存储…")
        backend = get_memory_backend()
        memory_removed = backend.clear()

        memory_store = get_memory_store()
        memory_removed = max(memory_removed, memory_store.count())
        memory_store.clear()
        memory_store.save()

        sync_files_tracked = 0
        knowledge_removed = 0
        if clear_knowledge:
            sync_files_tracked, knowledge_removed = _clear_file_indexes(
                clear_knowledge=True,
                reporter=reporter,
            )
        reset_chat_ingest_index()
        reset_chatgpt_import_index()
        reset_memory_store_singleton()
        reset_memory_backend()
        _report("重置完成")
        return {
            "source": "all",
            "memory_facts_removed": memory_removed,
            "sync_index_entries_removed": sync_files_tracked,
            "knowledge_chunks_removed": knowledge_removed,
            "clear_knowledge": clear_knowledge,
        }

    _report(f"按来源清空记忆: {origin}")
    memory_removed = _delete_facts_by_sources(SOURCE_GROUPS[origin], reporter=reporter)
    sync_files_tracked = 0
    knowledge_removed = 0

    if origin == "chat":
        reset_chat_ingest_index()
    elif origin == "chatgpt":
        reset_chatgpt_import_index()
    elif origin == "file":
        sync_files_tracked, knowledge_removed = _clear_file_indexes(
            clear_knowledge=clear_knowledge,
            reporter=reporter,
        )

    reset_memory_backend()
    _report("重置完成")
    return {
        "source": origin,
        "memory_facts_removed": memory_removed,
        "sync_index_entries_removed": sync_files_tracked,
        "knowledge_chunks_removed": knowledge_removed,
        "clear_knowledge": clear_knowledge if origin == "file" else False,
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


def rebuild_knowledge(
    *,
    reporter: ProgressReporter | None = None,
) -> tuple[dict[str, int | bool | str], SyncSummary]:
    """Clear Cold knowledge indexes then force re-index all kb/ documents."""
    reset_stats = reset_knowledge(clear_knowledge=True, reporter=reporter)
    if reporter is not None:
        reporter.update(ProgressEvent(phase="rebuild", message="重新索引 kb/ 文档…"))
    summary = sync_files(force=True, reporter=reporter)
    return reset_stats, summary


def reset_knowledge(
    *,
    clear_knowledge: bool = True,
    reporter: ProgressReporter | None = None,
) -> dict[str, int | bool | str]:
    """Clear Cold RAG indexes (sync_index + knowledge). Does not touch Warm memory."""
    config.ensure_data_dirs()

    def _report(message: str) -> None:
        if reporter is not None:
            reporter.update(ProgressEvent(phase="reset", message=message))

    _report("清空知识库索引…")
    sync_files_tracked, knowledge_removed = _clear_file_indexes(
        clear_knowledge=clear_knowledge,
        reporter=reporter,
    )
    # Also drop legacy document-sourced Warm facts if any remain
    ingest_removed = _delete_facts_by_sources(SOURCE_GROUPS["file"], reporter=reporter)
    _report("知识库重置完成")
    return {
        "source": "rag",
        "memory_facts_removed": ingest_removed,
        "sync_index_entries_removed": sync_files_tracked,
        "knowledge_chunks_removed": knowledge_removed,
        "clear_knowledge": clear_knowledge,
    }


def rebuild_memory(
    *,
    reporter: ProgressReporter | None = None,
) -> tuple[dict[str, int | bool | str], SyncSummary]:
    """Deprecated alias: reset Warm all then rebuild knowledge (prefer rag rebuild)."""
    store = get_memory_store()
    snapshot = [fact.to_dict() for fact in store.all_facts()]

    reset_stats = reset_memory(clear_knowledge=True, source="all", reporter=reporter)
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
            meta = dict(item.get("metadata") or {})
            source = str(meta.get("source") or "")
            if not text or text in existing_texts:
                continue
            if source == "ingest" or (source_file and (config.KB_DIR / source_file).exists()):
                continue
            meta["source_file"] = source_file
            meta["section_heading"] = (
                item.get("section_heading") or meta.get("section_heading") or "rebuild"
            )
            backend.retain(text, metadata=meta)

    return reset_stats, summary
