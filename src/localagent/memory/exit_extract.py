"""Silent background memory extraction during chat sessions."""

from __future__ import annotations

import subprocess
import sys

from localagent import config
from localagent.ingest.conversation_cold import index_conversation_cold
from localagent.memory.rememorize import mark_chat_ingested
from localagent.memory.save import confirm_save_facts
from localagent.memory.value_filter import filter_facts
from localagent.models.router import get_model_router
from localagent.persist.chatgpt import timestamp_to_iso
from localagent.persist.conversations import (
    conversation_file_for_fingerprint,
    load_conversation,
    load_conversation_object,
)


def _user_texts_from_messages(messages: list[dict]) -> list[str]:
    from localagent.session_commands import is_meta_user_content

    return [
        m["content"]
        for m in messages
        if m.get("role") == "user" and not is_meta_user_content(m.get("content", ""))
    ]


def _session_recorded_at(session_id: str) -> str | None:
    conversation = load_conversation_object(session_id)
    if conversation is None:
        return None
    created = timestamp_to_iso(conversation.create_time)
    return created or None


def _chat_metadata(session_id: str, *, recorded_at: str | None = None) -> dict:
    meta: dict = {"source": "chat", "session_id": session_id}
    recorded = recorded_at if recorded_at is not None else _session_recorded_at(session_id)
    if recorded:
        meta["recorded_at"] = recorded
    return meta


def _index_session_cold(session_id: str) -> int:
    conversation = load_conversation_object(session_id)
    if conversation is None or not conversation.messages:
        return 0
    path = conversation_file_for_fingerprint(session_id)
    archive = str(path) if path else f"{session_id}.json"
    return index_conversation_cold(
        conversation,
        origin="chat",
        archive_path=archive,
    )


def extract_session_memories(
    session_id: str,
    *,
    interactive: bool | None = None,
) -> list[str]:
    """Extract candidate memories from a session and save with optional confirmation.

    Always upserts the transcript into Cold RAG first (when enabled).
    """
    cold_count = _index_session_cold(session_id)
    recorded_at = _session_recorded_at(session_id)

    messages = load_conversation(session_id)
    user_texts = _user_texts_from_messages(messages)
    if not user_texts:
        mark_chat_ingested(session_id, saved_count=0, cold_chunk_count=cold_count)
        return []

    ids: list[str] = []

    # Warm session_summary only for durable substance; transcripts stay in persist/ + Cold.
    if config.MEMORY_SESSION_SUMMARY:
        from localagent.memory.summarize import build_session_summary_fact

        summary_item = build_session_summary_fact(
            session_id,
            user_texts,
            recorded_at=recorded_at,
        )
        if summary_item:
            summary_ids = confirm_save_facts(
                [str(summary_item["text"])],
                metadata=dict(summary_item.get("metadata") or {}),
                title=f"会话摘要 {session_id}",
                interactive=interactive,
            )
            ids.extend(summary_ids)

    combined = "\n".join(user_texts[-5:])
    try:
        facts = get_model_router().extract_facts(combined, context=f"session={session_id}")
    except Exception:
        facts = []

    facts = filter_facts(facts)
    if facts:
        meta = _chat_metadata(session_id, recorded_at=recorded_at)
        use_interactive = interactive if interactive is not None else False
        # Immediate consolidate only when not gating Warm writes through pending.
        can_consolidate = (
            config.MEMORY_CONSOLIDATE
            and config.MEMORY_CONSOLIDATE_ON_MEMORIZE
            and not use_interactive
            and (config.MEMORY_APPROVAL_AUTO or not config.MEMORY_APPROVAL_REQUIRED)
        )
        if can_consolidate:
            from localagent.memory.consolidate import consolidate_candidates
            from localagent.memory.profile_pin import pin_facts_to_profile

            report = consolidate_candidates(facts, metadata=meta, already_retained=False)
            ids.extend(report.retained_ids)
            ids.extend(report.updated_ids)
            pin_facts_to_profile(facts)
        else:
            saved = confirm_save_facts(
                facts,
                metadata=meta,
                title=f"从对话 {session_id} 提取到 {len(facts)} 条记忆",
                interactive=interactive,
            )
            ids.extend(saved)

    mark_chat_ingested(session_id, saved_count=len(ids), cold_chunk_count=cold_count)
    return ids


def schedule_session_memory_extract(session_id: str) -> str | None:
    """Extract and save session memories as a tracked background task.

    Returns task id when queued; None if task store unavailable (falls back to
    a detached process without progress tracking).
    """
    try:
        from localagent.ingest.add_file import spawn_background_task
        from localagent.ingest.tasks import get_task_store

        task = get_task_store().create_memorize_session(session_id=session_id)
        spawn_background_task(task)
        return task.id
    except Exception:
        subprocess.Popen(
            [sys.executable, "-m", "localagent.memory.exit_extract", session_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return None


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python -m localagent.memory.exit_extract <session_id>", file=sys.stderr)
        return 2
    extract_session_memories(args[0], interactive=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
