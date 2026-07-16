"""Ingest memories from persisted LocalAgent conversation archives."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from localagent import config
from localagent.ingest.conversation_cold import (
    cold_indexed_at_now,
    index_conversation_cold,
    needs_cold_backfill,
)
from localagent.ingest.progress import ProgressEvent, ProgressReporter
from localagent.memory.save import confirm_save_extracted
from localagent.models.router import get_model_router
from localagent.persist.chatgpt import timestamp_to_iso
from localagent.persist.conversations import (
    conversation_file_for_fingerprint,
    format_conversation_text,
    list_sessions,
    load_conversation_object,
)


def _load_index() -> dict[str, dict]:
    path = config.CHAT_INGEST_INDEX_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        processed = raw.get("processed", {})
        return processed if isinstance(processed, dict) else {}
    except Exception:
        return {}


def _save_index(processed: dict[str, dict]) -> None:
    config.ensure_data_dirs()
    config.CHAT_INGEST_INDEX_FILE.write_text(
        json.dumps({"processed": processed}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def conversation_fingerprint(session_id: str) -> str:
    """Stable fingerprint of a conversation archive (mtime + size + content hash)."""
    path = conversation_file_for_fingerprint(session_id)
    if path is None or not path.is_file():
        return ""
    try:
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        return f"{stat.st_mtime_ns}:{stat.st_size}:{digest}"
    except OSError:
        return ""


def mark_chat_ingested(
    session_id: str,
    *,
    saved_count: int = 0,
    cold_chunk_count: int | None = None,
    fingerprint: str | None = None,
    processed: dict[str, dict] | None = None,
    persist: bool = True,
) -> None:
    """Record that a session has been consumed by chat ingest / exit extract."""
    if processed is None:
        processed = _load_index()
    fp = fingerprint if fingerprint is not None else conversation_fingerprint(session_id)
    entry: dict = {
        "session_id": session_id,
        "ingested_at": datetime.now().isoformat(timespec="seconds"),
        "saved_count": saved_count,
        "fingerprint": fp,
    }
    if cold_chunk_count is not None:
        entry["cold_chunk_count"] = cold_chunk_count
        entry["cold_indexed_at"] = cold_indexed_at_now()
    elif session_id in processed and "cold_chunk_count" in processed[session_id]:
        entry["cold_chunk_count"] = processed[session_id]["cold_chunk_count"]
        entry["cold_indexed_at"] = processed[session_id].get("cold_indexed_at", "")
    processed[session_id] = entry
    if persist:
        _save_index(processed)


def reset_chat_ingest_index() -> None:
    """Clear chat ingest progress index."""
    path = config.CHAT_INGEST_INDEX_FILE
    if path.exists():
        path.unlink()


def _should_skip(
    session_id: str,
    *,
    force: bool,
    processed: dict[str, dict],
) -> bool:
    if force:
        return False
    entry = processed.get(session_id)
    if not entry:
        return False
    if needs_cold_backfill(entry):
        return False
    current = conversation_fingerprint(session_id)
    stored = str(entry.get("fingerprint") or "")
    if current and stored and current != stored:
        return False
    return True


def _archive_path_for(session_id: str) -> str:
    path = conversation_file_for_fingerprint(session_id)
    return str(path) if path else f"{session_id}.json"


def ingest_chat(
    *,
    session_id: str | None = None,
    force: bool = False,
    reporter: ProgressReporter | None = None,
    interactive: bool | None = None,
) -> list[str]:
    """Extract memories from conversation archives (incremental by default).

    Always indexes eligible transcripts into Cold before Warm fact extraction.
    """
    saved_ids: list[str] = []
    processed = _load_index()

    sessions = [session_id] if session_id else list_sessions()
    total = len(sessions)
    if reporter is not None:
        reporter.update(
            ProgressEvent(
                phase="scan",
                message=f"发现 {total} 个对话档案",
                current=0,
                total=total,
            )
        )

    for index, sid in enumerate(sessions, start=1):
        if reporter is not None:
            reporter.update(
                ProgressEvent(
                    phase="session",
                    message=f"分析对话 {sid}",
                    current=index,
                    total=total,
                )
            )
        if _should_skip(sid, force=force, processed=processed):
            if reporter is not None:
                reporter.update(
                    ProgressEvent(
                        phase="skip",
                        message=f"跳过已处理对话 {sid}",
                        current=index,
                        total=total,
                    )
                )
            continue

        conversation = load_conversation_object(sid)
        if conversation is None or not conversation.messages:
            mark_chat_ingested(sid, saved_count=0, cold_chunk_count=0, processed=processed)
            continue

        entry = processed.get(sid)
        current_fp = conversation_fingerprint(sid)
        cold_only = (
            not force
            and entry is not None
            and needs_cold_backfill(entry)
            and str(entry.get("fingerprint") or "") == current_fp
        )

        cold_count = index_conversation_cold(
            conversation,
            origin="chat",
            archive_path=_archive_path_for(sid),
        )
        if reporter is not None and cold_count:
            reporter.update(
                ProgressEvent(
                    phase="cold",
                    message=f"→ Cold 索引 {cold_count} chunks",
                    current=index,
                    total=total,
                )
            )

        if cold_only:
            mark_chat_ingested(
                sid,
                saved_count=int(entry.get("saved_count") or 0),
                cold_chunk_count=cold_count,
                fingerprint=current_fp,
                processed=processed,
            )
            continue

        text = format_conversation_text(conversation)
        if not config.INGEST_USE_LLM:
            memories = []
        else:
            memories = get_model_router().extract_memories(
                text, context=f"ingest chat session={sid}"
            )
        if not memories:
            mark_chat_ingested(
                sid,
                saved_count=0,
                cold_chunk_count=cold_count,
                fingerprint=current_fp,
                processed=processed,
            )
            continue

        chat_meta: dict = {"source": "chat", "session_id": sid}
        recorded = timestamp_to_iso(conversation.create_time)
        if recorded:
            chat_meta["recorded_at"] = recorded
        ids = confirm_save_extracted(
            memories,
            metadata=chat_meta,
            title=f"从对话 {sid} 提取到 {len(memories)} 条记忆",
            interactive=interactive if session_id else False,
        )
        mark_chat_ingested(
            sid,
            saved_count=len(ids),
            cold_chunk_count=cold_count,
            fingerprint=current_fp,
            processed=processed,
        )
        saved_ids.extend(ids)

    return saved_ids


# Back-compat alias for internal callers / tests during transition.
rememorize_chat = ingest_chat


def backfill_chat_recorded_at() -> int:
    """Fill missing recorded_at on Warm chat facts from session create_time.

    Returns the number of facts updated.
    """
    from localagent.memory.store import get_memory_store

    store = get_memory_store()
    updated = 0
    cache: dict[str, str | None] = {}
    for fact in store.all_facts():
        meta = fact.metadata or {}
        if str(meta.get("recorded_at") or "").strip():
            continue
        source = str(meta.get("source") or "")
        if source not in ("chat", "chat_summary"):
            continue
        sid = str(meta.get("session_id") or "").strip()
        if not sid:
            continue
        if sid not in cache:
            conversation = load_conversation_object(sid)
            cache[sid] = (
                timestamp_to_iso(conversation.create_time)
                if conversation is not None
                else None
            )
        recorded = cache[sid]
        if not recorded:
            continue
        store.update_metadata(fact.id, {"recorded_at": recorded})
        updated += 1
    return updated
