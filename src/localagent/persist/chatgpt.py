"""Parse ChatGPT export JSON (conversations.json)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_CITE_PATTERN = re.compile(r"\ue200cite\ue202[^\ue201]*\ue201")
_TEXT_CONTENT_TYPES = frozenset({"text"})


@dataclass(frozen=True)
class ChatGPTMessage:
    role: str
    content: str
    create_time: float | None = None


@dataclass(frozen=True)
class ChatGPTConversation:
    conversation_id: str
    title: str
    create_time: float | None
    update_time: float | None
    is_do_not_remember: bool
    messages: list[ChatGPTMessage]


def strip_cite_markers(text: str) -> str:
    """Remove ChatGPT inline citation markers from assistant text."""
    return _CITE_PATTERN.sub("", text).strip()


def _format_timestamp(ts: float | None) -> str:
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return ""


def _extract_message_text(message: dict[str, Any]) -> str:
    content = message.get("content") or {}
    content_type = content.get("content_type", "text")
    if content_type not in _TEXT_CONTENT_TYPES:
        return ""

    parts = content.get("parts") or []
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, str) and part.strip():
            chunks.append(part.strip())
    text = "\n".join(chunks)
    role = (message.get("author") or {}).get("role", "")
    if role == "assistant":
        text = strip_cite_markers(text)
    return text


def reconstruct_messages(conversation: dict[str, Any]) -> list[ChatGPTMessage]:
    """Walk mapping tree from current_node to root, return chronological messages."""
    mapping = conversation.get("mapping") or {}
    current = conversation.get("current_node")
    if not current or current not in mapping:
        return []

    chain: list[str] = []
    node_id: str | None = current
    while node_id:
        node = mapping.get(node_id)
        if not node:
            break
        chain.append(node_id)
        node_id = node.get("parent")
    chain.reverse()

    messages: list[ChatGPTMessage] = []
    for nid in chain:
        node = mapping.get(nid) or {}
        message = node.get("message")
        if not message:
            continue
        role = (message.get("author") or {}).get("role")
        if role not in ("user", "assistant"):
            continue
        text = _extract_message_text(message)
        if not text:
            continue
        messages.append(
            ChatGPTMessage(
                role=role,
                content=text,
                create_time=message.get("create_time"),
            )
        )
    return messages


def parse_conversation(raw: dict[str, Any]) -> ChatGPTConversation:
    conversation_id = raw.get("conversation_id") or raw.get("id") or ""
    return ChatGPTConversation(
        conversation_id=str(conversation_id),
        title=str(raw.get("title") or "未命名对话"),
        create_time=raw.get("create_time"),
        update_time=raw.get("update_time"),
        is_do_not_remember=bool(raw.get("is_do_not_remember")),
        messages=reconstruct_messages(raw),
    )


def load_conversations_file(path: Path) -> list[ChatGPTConversation]:
    """Load a ChatGPT export JSON file (array of conversations)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"expected JSON array in {path}")
    return [parse_conversation(item) for item in raw if isinstance(item, dict)]


def format_conversation_text(conversation: ChatGPTConversation) -> str:
    """Format conversation for memory extraction."""
    lines: list[str] = []
    title = conversation.title.strip()
    if title:
        lines.append(f"title: {title}")

    ts = _format_timestamp(conversation.create_time)
    if ts:
        lines.append(f"date: {ts}")

    for msg in conversation.messages:
        lines.append(f"{msg.role}: {msg.content}")
    return "\n".join(lines)
