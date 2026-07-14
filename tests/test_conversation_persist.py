"""Tests for ChatGPT-isomorphic conversation persistence and extract parsing."""

from __future__ import annotations

import json

from localagent.memory.conversation_extract import parse_extracted_memories
from localagent.memory.value_filter import is_narrative_memory
from localagent.persist.chatgpt import parse_conversation
from localagent.persist.conversations import (
    append_message,
    conversation_path,
    format_conversation_text,
    load_conversation,
    load_conversation_object,
)


def test_append_message_writes_chatgpt_mapping(isolated_data):
    sid = "s-persist-1"
    append_message(sid, "user", "我喜欢喝葡萄酒")
    append_message(sid, "assistant", "记下了")

    path = conversation_path(sid)
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["conversation_id"] == sid
    assert "mapping" in raw
    assert raw["current_node"]

    obj = load_conversation_object(sid)
    assert obj is not None
    assert len(obj.messages) == 2
    assert obj.messages[0].role == "user"
    assert "葡萄酒" in obj.messages[0].content

    # Shared ChatGPT parser accepts LA files
    parsed = parse_conversation(raw)
    assert len(parsed.messages) == 2

    flat = load_conversation(sid)
    assert flat[0]["role"] == "user"
    text = format_conversation_text(obj)
    assert "user:" in text
    assert "葡萄酒" in text


def test_migrate_legacy_jsonl(isolated_data):
    from localagent import config

    sid = "s-legacy-jsonl"
    legacy = config.CONVERSATIONS_DIR / f"{sid}.jsonl"
    legacy.write_text(
        json.dumps({"ts": "2026-07-01T10:00:00", "role": "user", "content": "我决定用 Mem0"}, ensure_ascii=False)
        + "\n"
        + json.dumps({"ts": "2026-07-01T10:00:01", "role": "assistant", "content": "好的"}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    obj = load_conversation_object(sid)
    assert obj is not None
    assert len(obj.messages) == 2
    assert conversation_path(sid).is_file()


def test_is_narrative_memory_rejects_keyword_soup():
    assert not is_narrative_memory("总部；HUMAN；目标管理")
    assert not is_narrative_memory("计划plan；任务拆解；skill使用")
    assert is_narrative_memory("用户喜欢喝葡萄酒。")
    assert is_narrative_memory("用户于 2026-03-20 决定采用 Mem0 作为记忆引擎。")


def test_parse_extracted_memories_json():
    reply = json.dumps(
        [
            {
                "text": "用户喜欢喝葡萄酒。",
                "slots": {"subject": "用户", "action": "喜欢", "object": "葡萄酒"},
                "type": "preference",
                "tags": ["偏好"],
            }
        ],
        ensure_ascii=False,
    )
    memories = parse_extracted_memories(reply)
    assert len(memories) == 1
    assert memories[0].text.startswith("用户喜欢")
    assert memories[0].slots.get("object") == "葡萄酒"


def test_parse_extracted_memories_rejects_soup():
    reply = json.dumps([{"text": "总部；HUMAN；目标管理", "type": "plan"}], ensure_ascii=False)
    assert parse_extracted_memories(reply) == []
