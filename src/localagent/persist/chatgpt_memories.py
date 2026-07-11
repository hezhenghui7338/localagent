"""Parse ChatGPT saved-memory export (memory.json / memories.json)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_MEMORY_FILENAMES = frozenset({"memory.json", "memories.json"})


@dataclass(frozen=True)
class ChatGPTSavedMemory:
    memory_id: str
    content: str
    enabled: bool
    created_at: str | None = None
    updated_at: str | None = None


def is_memory_export_filename(name: str) -> bool:
    return name.lower() in _MEMORY_FILENAMES


def _normalize_record(raw: dict[str, Any]) -> ChatGPTSavedMemory | None:
    content = raw.get("content") or raw.get("text") or ""
    if isinstance(content, list):
        content = "\n".join(str(part).strip() for part in content if str(part).strip())
    content = str(content).strip()
    if not content:
        return None

    memory_id = str(raw.get("id") or raw.get("memory_id") or "").strip()
    if not memory_id:
        memory_id = f"hash:{hash(content) & 0xFFFFFFFF:08x}"

    enabled = raw.get("enabled")
    if enabled is None:
        enabled = not raw.get("is_deleted", False)

    return ChatGPTSavedMemory(
        memory_id=memory_id,
        content=content,
        enabled=bool(enabled),
        created_at=_as_optional_str(raw.get("created_at") or raw.get("create_time")),
        updated_at=_as_optional_str(raw.get("updated_at") or raw.get("update_time")),
    )


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _unwrap_records(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("memory", "memories"):
            nested = raw.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    raise ValueError("expected memory export array or {memory|memories: [...]} object")


def detect_chatgpt_export_kind(raw: Any, *, filename: str = "") -> str:
    """Return ``conversations`` or ``memories`` for a parsed JSON export."""
    if is_memory_export_filename(filename):
        return "memories"

    if isinstance(raw, dict) and ("memory" in raw or "memories" in raw):
        return "memories"

    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict):
            if "mapping" in first or "conversation_id" in first or "current_node" in first:
                return "conversations"
            if "content" in first or "text" in first:
                return "memories"

    if isinstance(raw, list):
        return "conversations"

    raise ValueError("unrecognized ChatGPT export JSON shape")


def load_memories_file(path: Path) -> list[ChatGPTSavedMemory]:
    """Load ChatGPT saved memories from memory.json or memories.json."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = _unwrap_records(raw)
    memories: list[ChatGPTSavedMemory] = []
    for record in records:
        memory = _normalize_record(record)
        if memory is not None:
            memories.append(memory)
    return memories
