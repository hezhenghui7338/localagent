"""Ingest LoCoMo conversations into LocalAgent long-term memory."""

from __future__ import annotations

import hashlib
from typing import Any, Callable

from benchmarks.locomo.dataset import format_sample_cold_markdown, iter_memory_items, iter_sessions


def _index_sample_cold(sample: dict[str, Any]) -> int:
    """Index official dialog transcript into Cold hybrid store."""
    from localagent import config
    from localagent.ingest.chunker import TextChunk, chunk_for_rag
    from localagent.ingest.conversation_cold import cold_source_key
    from localagent.knowledge.indexer import get_knowledge_indexer
    from localagent.memory.temporal import extract_occurred_at, to_ymd

    if not getattr(config, "COLD_CONVERSATION", True):
        return 0

    sample_id = str(sample.get("sample_id") or "unknown")
    conversation = sample.get("conversation") or {}
    body_md = format_sample_cold_markdown(sample)
    source_key = cold_source_key("locomo", sample_id)

    # Prefer earliest session timestamp as recorded_at for temporal Cold filters.
    recorded_at = ""
    for _num, date_time, _turns in iter_sessions(conversation):
        occurred = extract_occurred_at(date_time)
        if occurred:
            recorded_at = occurred
            break

    base: dict[str, Any] = {
        "origin": "locomo",
        "conversation_id": sample_id,
        "archive_path": f"locomo:{sample_id}",
        "title": f"LoCoMo {sample_id}",
        "sample_id": sample_id,
    }
    if recorded_at:
        base["recorded_at"] = recorded_at
        ymd = to_ymd(recorded_at)
        if ymd:
            base["recorded_at_ymd"] = ymd

    def _sanitize(meta: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in meta.items():
            if value is None:
                continue
            if isinstance(value, bool):
                out[key] = value
            elif isinstance(value, (int, float)):
                out[key] = value
            else:
                out[key] = str(value)
        return out

    chunks: list[TextChunk] = []
    # Skip LLM session summary for benchmark speed/determinism; body chunks keep dia_ids.
    body_chunks = chunk_for_rag(body_md, filename=source_key)
    for offset, chunk in enumerate(body_chunks):
        chunk.index = offset
        meta = {
            **chunk.metadata,
            **base,
            "chunk_kind": "body",
        }
        # Propagate first dia_id found in the chunk text for evidence alignment.
        import re

        match = re.search(r"\b(D\d+:\d+)\b", chunk.text or "")
        if match:
            meta["dia_id"] = match.group(1)
        chunk.metadata = _sanitize(meta)
        if not chunk.chunk_id:
            digest = hashlib.sha256(f"{source_key}:{offset}".encode()).hexdigest()[:16]
            chunk.chunk_id = f"{digest}-{offset}"
        chunks.append(chunk)

    if not chunks:
        return 0
    return get_knowledge_indexer().index_chunks(filename=source_key, chunks=chunks)


def _rebuild_graphs_if_enabled() -> dict[str, Any]:
    from localagent import config

    info: dict[str, Any] = {}
    if getattr(config, "MEMORY_GRAPH", False):
        from localagent.memory.graph import rebuild_memory_graph

        info["memory_graph"] = rebuild_memory_graph()
    if getattr(config, "NEO4J", False):
        from localagent.memory.graph import neo4j_available, rebuild_neo4j_graph

        if neo4j_available():
            info["neo4j"] = rebuild_neo4j_graph()
        else:
            info["neo4j"] = {"skipped": True, "reason": "unavailable"}
    return info


def _retain_items(
    items: list[dict[str, Any]],
    *,
    on_progress: Callable[[int, int], None] | None = None,
    progress_base: int = 0,
    progress_total: int | None = None,
) -> tuple[int, int]:
    from localagent.memory.backend import get_memory_backend

    backend = get_memory_backend()
    written = 0
    skipped = 0
    total = progress_total if progress_total is not None else len(items)
    for index, item in enumerate(items, start=1):
        fact_id = backend.retain(item["text"], metadata=dict(item["metadata"]))
        if fact_id:
            written += 1
        else:
            skipped += 1
        absolute = progress_base + index
        if on_progress is not None and (absolute == total or absolute % 50 == 0):
            on_progress(absolute, total)
    return written, skipped


def ingest_sample(
    sample: dict[str, Any],
    *,
    max_turns: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    index_cold: bool = True,
    rebuild_graph: bool = True,
    incremental_sessions: bool = False,
) -> dict[str, Any]:
    """Retain dialog turns for one LoCoMo conversation into the active memory backend.

    When ``incremental_sessions`` is True, retain conversation_meta first, then each
    session's summary + dialogs in chronological order (timeline-realistic).
    Cold indexing still runs once at the end for the full sample transcript.
    """
    from localagent.memory.backend import get_memory_backend

    backend = get_memory_backend()
    items = list(iter_memory_items(sample))
    if max_turns is not None:
        meta = [
            item
            for item in items
            if item["metadata"].get("kind") in {"conversation_meta", "session_summary"}
        ]
        dialogs = [item for item in items if item["metadata"].get("kind") == "dialog"]
        items = meta + dialogs[: max(0, max_turns)]

    written = 0
    skipped = 0
    total = len(items)
    sessions_ingested = 0

    if incremental_sessions:
        meta_items = [
            item for item in items if item["metadata"].get("kind") == "conversation_meta"
        ]
        w, s = _retain_items(
            meta_items,
            on_progress=on_progress,
            progress_base=0,
            progress_total=total,
        )
        written += w
        skipped += s
        progress_base = len(meta_items)

        session_nums = sorted(
            {
                int(item["metadata"]["session"])
                for item in items
                if item["metadata"].get("kind") in {"session_summary", "dialog"}
                and item["metadata"].get("session") is not None
            }
        )
        for session_num in session_nums:
            batch = [
                item
                for item in items
                if item["metadata"].get("kind") in {"session_summary", "dialog"}
                and int(item["metadata"].get("session") or -1) == session_num
            ]
            # Summaries before dialog turns within the session.
            batch.sort(
                key=lambda item: 0 if item["metadata"].get("kind") == "session_summary" else 1
            )
            w, s = _retain_items(
                batch,
                on_progress=on_progress,
                progress_base=progress_base,
                progress_total=total,
            )
            written += w
            skipped += s
            progress_base += len(batch)
            sessions_ingested += 1
    else:
        w, s = _retain_items(items, on_progress=on_progress, progress_total=total)
        written += w
        skipped += s

    cold_chunks = 0
    if index_cold:
        try:
            cold_chunks = _index_sample_cold(sample)
        except Exception:
            cold_chunks = 0

    graph_info: dict[str, Any] = {}
    if rebuild_graph:
        try:
            graph_info = _rebuild_graphs_if_enabled()
        except Exception as exc:
            graph_info = {"error": str(exc)}

    return {
        "sample_id": sample.get("sample_id"),
        "backend": backend.backend_name(),
        "candidates": total,
        "written": written,
        "skipped": skipped,
        "memory_count": backend.count(),
        "cold_chunks": cold_chunks,
        "graph": graph_info,
        "incremental_sessions": bool(incremental_sessions),
        "sessions_ingested": sessions_ingested if incremental_sessions else None,
    }
