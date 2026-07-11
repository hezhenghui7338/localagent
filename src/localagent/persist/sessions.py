"""LangGraph SQLite checkpointer for session recovery."""

from __future__ import annotations

from localagent import config


def get_checkpointer():
    """Return LangGraph SqliteSaver if available, else None."""
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        config.ensure_data_dirs()
        return SqliteSaver.from_conn_string(str(config.SESSIONS_DB))
    except ImportError:
        return None
