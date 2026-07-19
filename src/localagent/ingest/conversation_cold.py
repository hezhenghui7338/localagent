"""Index conversation transcripts into Cold RAG (summary + body chunks)."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from localagent import config
from localagent.ingest.chunker import TextChunk, chunk_for_rag
from localagent.knowledge.indexer import get_knowledge_indexer
from localagent.persist.chatgpt import ChatGPTConversation, timestamp_to_iso

ConversationOrigin = Literal["chat", "chatgpt", "locomo"]


def cold_source_key(origin: ConversationOrigin | str, conversation_id: str) -> str:
    """Stable KnowledgeIndexer source_file key (avoids colliding with kb filenames)."""
    return f"{origin}:{conversation_id}"


def needs_cold_backfill(entry: dict[str, Any] | None) -> bool:
    """True when an ingest index entry predates Cold conversation indexing."""
    if not config.COLD_CONVERSATION:
        return False
    if entry is None:
        return False
    return "cold_chunk_count" not in entry


def _sanitize_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Chroma only accepts str/int/float/bool metadata values."""
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


def format_turns_markdown(conversation: ChatGPTConversation) -> str:
    """Markdown with per-turn headings for section-aware chunking."""
    title = (conversation.title or conversation.conversation_id or "未命名对话").strip()
    lines: list[str] = [f"# {title}", ""]
    created = timestamp_to_iso(conversation.create_time)
    if created:
        lines.append(f"date: {created}")
        lines.append("")
    for index, msg in enumerate(conversation.messages, start=1):
        role = msg.role or "unknown"
        lines.append(f"## Turn {index} · {role}")
        lines.append("")
        lines.append(msg.content.strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _base_provenance(
    *,
    origin: str,
    conversation_id: str,
    title: str,
    archive_path: str,
    create_time: float | None,
    update_time: float | None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "origin": origin,
        "conversation_id": conversation_id,
        "archive_path": archive_path,
        "title": title,
    }
    created = timestamp_to_iso(create_time)
    updated = timestamp_to_iso(update_time)
    if created:
        meta["chatgpt_created_at"] = created
        meta["recorded_at"] = created
        from localagent.memory.temporal import to_ymd

        ymd = to_ymd(created)
        if ymd:
            meta["recorded_at_ymd"] = ymd
    if updated:
        meta["chatgpt_updated_at"] = updated
    return meta


def build_conversation_chunks(
    conversation: ChatGPTConversation,
    *,
    origin: ConversationOrigin | str,
    archive_path: str,
) -> list[TextChunk]:
    """Build summary (+ optional body) chunks for one conversation."""
    if not conversation.messages:
        return []

    source_key = cold_source_key(origin, conversation.conversation_id)
    title = (conversation.title or conversation.conversation_id or "未命名对话").strip()
    base = _base_provenance(
        origin=origin,
        conversation_id=conversation.conversation_id,
        title=title,
        archive_path=archive_path,
        create_time=conversation.create_time,
        update_time=conversation.update_time,
    )

    body_md = format_turns_markdown(conversation)
    chunks: list[TextChunk] = []

    if config.COLD_CONVERSATION_SUMMARY:
        from localagent.memory.summarize import summarize_text

        summary = summarize_text(
            body_md,
            context=f"origin={origin}; title={title}; id={conversation.conversation_id}",
        )
        if summary:
            provenance = (
                f"origin={origin} conversation_id={conversation.conversation_id} "
                f"archive={archive_path}"
            )
            summary_text = (
                f"[会话摘要:{title}]\n{summary}\n\n溯源: {provenance}"
            )
            digest = hashlib.sha256(f"{source_key}:summary".encode()).hexdigest()[:16]
            chunks.append(
                TextChunk(
                    chunk_id=f"{digest}-summary",
                    heading=f"# 会话摘要: {title}",
                    text=summary_text,
                    start_line=1,
                    index=0,
                    metadata=_sanitize_meta({**base, "chunk_kind": "summary"}),
                )
            )

    body_chunks = chunk_for_rag(body_md, filename=source_key)
    for offset, chunk in enumerate(body_chunks):
        chunk.index = len(chunks) + offset
        chunk.metadata = _sanitize_meta(
            {
                **chunk.metadata,
                **base,
                "chunk_kind": "body",
            }
        )
        chunks.append(chunk)

    return chunks


def index_conversation_cold(
    conversation: ChatGPTConversation,
    *,
    origin: ConversationOrigin | str,
    archive_path: str,
) -> int:
    """Index one conversation into Cold hybrid store. Returns chunk count."""
    if not config.COLD_CONVERSATION:
        return 0
    if conversation.is_do_not_remember:
        return 0
    if not conversation.conversation_id or not conversation.messages:
        return 0

    chunks = build_conversation_chunks(
        conversation,
        origin=origin,
        archive_path=archive_path,
    )
    source_key = cold_source_key(origin, conversation.conversation_id)
    return get_knowledge_indexer().index_chunks(filename=source_key, chunks=chunks)


def index_chatgpt_saved_memories_cold(
    memories: list[Any],
    *,
    archive_path: str,
) -> int:
    """Index ChatGPT saved-memory export texts into Cold (origin=chatgpt)."""
    if not config.COLD_CONVERSATION:
        return 0
    lines: list[str] = ["# ChatGPT saved memories", ""]
    count = 0
    for mem in memories:
        content = str(getattr(mem, "content", "") or "").strip()
        if not content:
            continue
        enabled = getattr(mem, "enabled", True)
        if enabled is False:
            continue
        mid = str(getattr(mem, "memory_id", "") or count)
        lines.append(f"## Memory {mid}")
        lines.append("")
        lines.append(content)
        lines.append("")
        count += 1
    if count == 0:
        return 0

    body = "\n".join(lines).strip() + "\n"
    # Stable key per archive file so rebuild replaces cleanly
    stem = Path(archive_path).stem if archive_path else "memories"
    source_key = cold_source_key("chatgpt", f"memories:{stem}")
    base = {
        "origin": "chatgpt",
        "conversation_id": f"memories:{stem}",
        "archive_path": archive_path,
        "title": f"ChatGPT memories ({stem})",
        "chunk_kind": "body",
    }
    rag_chunks = chunk_for_rag(body, filename=source_key)
    chunks: list[TextChunk] = []
    for chunk in rag_chunks:
        chunk.metadata = _sanitize_meta({**(chunk.metadata or {}), **base})
        chunks.append(chunk)
    return get_knowledge_indexer().index_chunks(filename=source_key, chunks=chunks)


def remove_conversation_cold(origin: ConversationOrigin | str, conversation_id: str) -> int:
    """Remove Cold chunks for one conversation."""
    key = cold_source_key(origin, conversation_id)
    return get_knowledge_indexer().remove_by_source_file(key)


def remove_conversations_by_origin(origin: ConversationOrigin | str) -> int:
    """Remove all Cold chunks with the given origin."""
    return get_knowledge_indexer().remove_by_origin(str(origin))


def count_chunks_by_origin() -> dict[str, int]:
    """Aggregate Cold chunk counts by metadata.origin (kb chunks have no origin)."""
    indexer = get_knowledge_indexer()
    counts: dict[str, int] = {"kb": 0, "chat": 0, "chatgpt": 0, "locomo": 0, "other": 0}
    for meta in indexer.iter_metas():
        origin = str(meta.get("origin") or "").strip()
        if not origin:
            counts["kb"] = counts.get("kb", 0) + 1
        elif origin in counts:
            counts[origin] = counts.get(origin, 0) + 1
        else:
            counts["other"] = counts.get("other", 0) + 1
    return counts


def reindex_conversation_archives(*, force: bool = True) -> dict[str, int]:
    """Re-index LA chats + ChatGPT exports into Cold (used by rag rebuild)."""
    from localagent.persist.chatgpt import load_conversations_file
    from localagent.persist.chatgpt_memories import detect_chatgpt_export_kind
    from localagent.persist.conversations import (
        conversation_file_for_fingerprint,
        list_sessions,
        load_conversation_object,
    )

    stats = {"chat": 0, "chatgpt": 0, "chunks": 0, "skipped": 0, "errors": 0}
    if not config.COLD_CONVERSATION:
        return stats

    for session_id in list_sessions():
        conversation = load_conversation_object(session_id)
        if conversation is None or not conversation.messages:
            stats["skipped"] += 1
            continue
        path = conversation_file_for_fingerprint(session_id)
        archive = str(path) if path else f"{session_id}.json"
        try:
            n = index_conversation_cold(
                conversation,
                origin="chat",
                archive_path=archive,
            )
            stats["chat"] += 1
            stats["chunks"] += n
        except Exception:
            stats["errors"] += 1

    chatgpt_dir = config.CHATGPT_DATA_DIR
    if chatgpt_dir.is_dir():
        for path in sorted(chatgpt_dir.glob("*.json")):
            try:
                import json

                raw = json.loads(path.read_text(encoding="utf-8"))
                kind = detect_chatgpt_export_kind(raw, filename=path.name)
                if kind == "memories":
                    from localagent.persist.chatgpt_memories import load_memories_file

                    memories = load_memories_file(path)
                    n = index_chatgpt_saved_memories_cold(
                        memories,
                        archive_path=path.name,
                    )
                    if n:
                        stats["chatgpt"] += 1
                        stats["chunks"] += n
                    else:
                        stats["skipped"] += 1
                    continue
                if kind != "conversations":
                    continue
                for conversation in load_conversations_file(path):
                    if conversation.is_do_not_remember or not conversation.messages:
                        stats["skipped"] += 1
                        continue
                    n = index_conversation_cold(
                        conversation,
                        origin="chatgpt",
                        archive_path=path.name,
                    )
                    stats["chatgpt"] += 1
                    stats["chunks"] += n
            except Exception:
                stats["errors"] += 1

    _ = force  # always re-writes via index_chunks remove+upsert
    return stats


def cold_indexed_at_now() -> str:
    return datetime.now().isoformat(timespec="seconds")
