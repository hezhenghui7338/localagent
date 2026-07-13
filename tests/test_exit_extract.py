"""Tests for background memory extraction from chat sessions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from localagent.memory.exit_extract import extract_session_memories, schedule_session_memory_extract
from localagent.memory.store import get_memory_store
from localagent.persist.conversations import append_message


def test_extract_session_memories_from_persisted_jsonl(isolated_data):
    isolated_data["router"].extract_facts.return_value = [
        "2026年7月决定使用 Hindsight 作为记忆引擎",
    ]

    session_id = "s-bg-extract"
    append_message(session_id, "user", "我决定用 Hindsight")
    append_message(session_id, "assistant", "好的")

    before = get_memory_store().count()
    ids = extract_session_memories(session_id, interactive=False)

    assert len(ids) == 1
    assert get_memory_store().count() == before + 1


def test_extract_session_memories_skips_commands(isolated_data):
    isolated_data["router"].extract_facts.return_value = ["不应提取"]

    session_id = "s-cmd-only"
    append_message(session_id, "user", ":deepsearch foo")
    append_message(session_id, "assistant", "report")

    assert extract_session_memories(session_id, interactive=False) == []

    session_id2 = "s-cmd-slash"
    append_message(session_id2, "user", "/search bar")
    append_message(session_id2, "assistant", "ok")
    assert extract_session_memories(session_id2, interactive=False) == []


def test_schedule_session_memory_extract_spawns_detached_process():
    import subprocess

    mock_proc = MagicMock()
    with patch("localagent.memory.exit_extract.subprocess.Popen", return_value=mock_proc) as popen:
        schedule_session_memory_extract("s-bg")

    popen.assert_called_once()
    args, kwargs = popen.call_args
    assert args[0][-1] == "s-bg"
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
