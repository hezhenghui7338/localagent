"""Session work prefetch for cross-turn task continuity."""

from __future__ import annotations

from localagent.persist.session_work import (
    clear_session_work,
    format_work_prefetch,
    load_session_work,
    work_stale,
)


def prefetch_work_context(session_id: str | None) -> str:
    if not session_id:
        return ""
    stored_work = load_session_work(session_id)
    if stored_work and not work_stale(stored_work):
        return format_work_prefetch(stored_work)
    if stored_work:
        clear_session_work(session_id)
    return ""
