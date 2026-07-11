"""Rememorize from persisted conversations."""

from __future__ import annotations

from localagent.ingest.progress import ProgressEvent, ProgressReporter
from localagent.memory.save import confirm_save_facts
from localagent.memory.value_filter import filter_facts
from localagent.models.router import get_model_router
from localagent.persist.conversations import format_conversation_text, list_sessions, load_conversation


def rememorize_chat(
    *,
    session_id: str | None = None,
    reporter: ProgressReporter | None = None,
    interactive: bool | None = None,
) -> list[str]:
    """Re-extract memories from conversation archives and save them."""
    router = get_model_router()
    saved_ids: list[str] = []

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
        messages = load_conversation(sid)
        if not messages:
            continue
        text = format_conversation_text(messages)
        facts = router.extract_facts(text, context=f"rememorize session={sid}")
        facts = filter_facts(facts)
        if not facts:
            continue
        ids = confirm_save_facts(
            facts,
            metadata={"source": "rememorize-chat", "session_id": sid},
            title=f"从对话 {sid} 提取到 {len(facts)} 条记忆",
            interactive=interactive if session_id else False,
        )
        saved_ids.extend(ids)

    return saved_ids
