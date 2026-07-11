"""Conversation jsonl persistence."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from localagent import config


def new_session_id() -> str:
    return f"s-{uuid.uuid4().hex[:10]}"


def conversation_path(session_id: str) -> Path:
    return config.CONVERSATIONS_DIR / f"{session_id}.jsonl"


def append_message(session_id: str, role: str, content: str, **extra: Any) -> None:
    config.ensure_data_dirs()
    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "content": content,
        **extra,
    }
    with conversation_path(session_id).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_conversation(session_id: str) -> list[dict[str, Any]]:
    path = conversation_path(session_id)
    if not path.exists():
        return []
    messages = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            messages.append(json.loads(line))
    return messages


def list_sessions() -> list[str]:
    config.ensure_data_dirs()
    return sorted(p.stem for p in config.CONVERSATIONS_DIR.glob("*.jsonl"))


def format_conversation_text(messages: list[dict[str, Any]]) -> str:
    lines = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)
