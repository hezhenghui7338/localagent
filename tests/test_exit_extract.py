"""Tests for background memory extraction from chat sessions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from localagent.memory.exit_extract import extract_session_memories, schedule_session_memory_extract
from localagent.memory.store import get_memory_store
from localagent.memory.summarize import build_session_summary_fact
from localagent.memory.value_filter import is_warm_worthy_session
from localagent.persist.conversations import append_message


def test_extract_session_memories_from_persisted_conversation(isolated_data):
    isolated_data["router"].extract_facts.return_value = [
        "2026年7月决定使用 Hindsight 作为记忆引擎",
    ]

    session_id = "s-bg-extract"
    append_message(session_id, "user", "我决定用 Hindsight 作为记忆引擎")
    append_message(session_id, "assistant", "好的")

    before = get_memory_store().count()
    ids = extract_session_memories(session_id, interactive=False)

    assert len(ids) >= 1
    assert get_memory_store().count() >= before + 1
    saved = [f for f in get_memory_store().all_facts() if f.id in ids or f.id[:8] in {i[:8] for i in ids}]
    assert saved
    assert any(str((f.metadata or {}).get("recorded_at") or "").strip() for f in saved)


def test_extract_session_memories_skips_commands(isolated_data):
    isolated_data["router"].extract_facts.return_value = [
        "不应提取",
    ]

    session_id = "s-cmd-only"
    append_message(session_id, "user", ":deepsearch foo")
    append_message(session_id, "assistant", "report")

    assert extract_session_memories(session_id, interactive=False) == []

    session_id2 = "s-cmd-slash"
    append_message(session_id2, "user", "/search bar")
    append_message(session_id2, "assistant", "ok")
    assert extract_session_memories(session_id2, interactive=False) == []


def test_ephemeral_session_skips_warm_summary(isolated_data):
    """Weather / news / identity probes stay in persist/, not Warm."""
    isolated_data["router"].extract_facts.return_value = []

    cases = [
        ("s-weather", "今天天气怎么样? 深圳"),
        ("s-news", "AI最近有什么新闻吗?"),
        ("s-who", "我是谁"),
    ]
    for session_id, text in cases:
        append_message(session_id, "user", text)
        append_message(session_id, "assistant", "…")
        assert extract_session_memories(session_id, interactive=False) == []
        assert build_session_summary_fact(session_id, [text]) is None


def test_is_warm_worthy_session_gate():
    assert not is_warm_worthy_session(["天气怎么样?"])
    assert not is_warm_worthy_session(["AI最近有什么新闻吗?"])
    assert not is_warm_worthy_session(["我是谁"])
    assert is_warm_worthy_session(["我决定采用 Mem0 作为 Warm 记忆引擎"])


def test_schedule_session_memory_extract_spawns_detached_process():
    import subprocess

    mock_proc = MagicMock()
    with patch("localagent.memory.exit_extract.subprocess.Popen", return_value=mock_proc) as popen:
        schedule_session_memory_extract("s-bg")

    assert popen.call_count >= 1
    # Last call should be the exit_extract worker (ignore unrelated Popen from other fixtures)
    args, kwargs = popen.call_args
    assert "localagent.memory.exit_extract" in args[0]
    assert args[0][-1] == "s-bg"
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
