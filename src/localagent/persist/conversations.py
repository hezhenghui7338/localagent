"""LA conversation persistence — ChatGPT-export isomorphic JSON.

Each session is stored as one conversation object with a ``mapping`` tree so
LA chat and ChatGPT imports share parse / format / extract paths.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from localagent import config
from localagent.persist.chatgpt import (
    ChatGPTConversation,
    ChatGPTMessage,
    format_conversation_text as format_chatgpt_conversation_text,
    parse_conversation,
    reconstruct_messages,
)


def new_session_id() -> str:
    return f"s-{uuid.uuid4().hex[:10]}"


def conversation_path(session_id: str) -> Path:
    return config.CONVERSATIONS_DIR / f"{session_id}.json"


def _legacy_jsonl_path(session_id: str) -> Path:
    return config.CONVERSATIONS_DIR / f"{session_id}.jsonl"


def _now_unix() -> float:
    return time.time()


def _iso_to_unix(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        text = ts.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _empty_conversation(session_id: str, *, now: float | None = None) -> dict[str, Any]:
    ts = now if now is not None else _now_unix()
    root_id = str(uuid.uuid4())
    return {
        "conversation_id": session_id,
        "title": "未命名对话",
        "create_time": ts,
        "update_time": ts,
        "is_do_not_remember": False,
        "current_node": root_id,
        "mapping": {
            root_id: {
                "id": root_id,
                "parent": None,
                "children": [],
                "message": None,
            }
        },
    }


def _load_raw(session_id: str) -> dict[str, Any] | None:
    path = conversation_path(session_id)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else None
        except Exception:
            return None
    return None


def _save_raw(session_id: str, data: dict[str, Any]) -> None:
    config.ensure_data_dirs()
    path = conversation_path(session_id)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _migrate_jsonl_if_needed(session_id: str) -> dict[str, Any] | None:
    """Convert legacy ``*.jsonl`` archives to ChatGPT-isomorphic JSON once."""
    legacy = _legacy_jsonl_path(session_id)
    if not legacy.is_file():
        return None
    if conversation_path(session_id).is_file():
        return _load_raw(session_id)

    lines = [ln for ln in legacy.read_text(encoding="utf-8").splitlines() if ln.strip()]
    first_ts: float | None = None
    messages: list[tuple[str, str, float | None, dict[str, Any]]] = []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        role = str(record.get("role") or "")
        content = str(record.get("content") or "")
        if role not in ("user", "assistant") or not content.strip():
            continue
        create_time = _iso_to_unix(str(record.get("ts") or "")) or _now_unix()
        if first_ts is None:
            first_ts = create_time
        extra = {k: v for k, v in record.items() if k not in ("ts", "role", "content")}
        messages.append((role, content, create_time, extra))

    now = first_ts or _now_unix()
    data = _empty_conversation(session_id, now=now)
    for role, content, create_time, extra in messages:
        _append_to_mapping(data, role=role, content=content, create_time=create_time, extra=extra)

    _save_raw(session_id, data)
    backup = legacy.with_suffix(".jsonl.bak")
    try:
        legacy.rename(backup)
    except OSError:
        pass
    return data


def _append_to_mapping(
    data: dict[str, Any],
    *,
    role: str,
    content: str,
    create_time: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    mapping: dict[str, Any] = data.setdefault("mapping", {})
    parent_id = data.get("current_node")
    if not parent_id or parent_id not in mapping:
        root = _empty_conversation(str(data.get("conversation_id") or new_session_id()))
        data.clear()
        data.update(root)
        mapping = data["mapping"]
        parent_id = data["current_node"]

    node_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())
    ts = create_time if create_time is not None else _now_unix()
    message: dict[str, Any] = {
        "id": msg_id,
        "author": {"role": role},
        "create_time": ts,
        "content": {"content_type": "text", "parts": [content]},
    }
    if extra:
        for key, value in extra.items():
            if key not in message:
                message[key] = value

    mapping[node_id] = {
        "id": node_id,
        "parent": parent_id,
        "children": [],
        "message": message,
    }
    parent = mapping.get(parent_id) or {}
    children = list(parent.get("children") or [])
    children.append(node_id)
    parent["children"] = children
    mapping[parent_id] = parent
    data["current_node"] = node_id
    data["update_time"] = ts
    if data.get("create_time") is None:
        data["create_time"] = ts


def ensure_conversation(session_id: str) -> dict[str, Any]:
    """Load or create a ChatGPT-isomorphic conversation object."""
    raw = _load_raw(session_id)
    if raw is not None:
        return raw
    migrated = _migrate_jsonl_if_needed(session_id)
    if migrated is not None:
        return migrated
    data = _empty_conversation(session_id)
    _save_raw(session_id, data)
    return data


def append_message(session_id: str, role: str, content: str, **extra: Any) -> None:
    """Append a user/assistant turn onto the conversation mapping tree."""
    data = ensure_conversation(session_id)
    _append_to_mapping(
        data,
        role=role,
        content=content,
        create_time=_now_unix(),
        extra=extra or None,
    )
    # Auto-title from first user message
    if role == "user" and (not data.get("title") or data.get("title") == "未命名对话"):
        title = content.strip().splitlines()[0][:40] if content.strip() else "未命名对话"
        data["title"] = title or "未命名对话"
    _save_raw(session_id, data)


def load_conversation_object(session_id: str) -> ChatGPTConversation | None:
    """Load session as a ChatGPTConversation (shared with ChatGPT import)."""
    raw = _load_raw(session_id)
    if raw is None:
        raw = _migrate_jsonl_if_needed(session_id)
    if raw is None:
        return None
    return parse_conversation(raw)


def load_conversation(session_id: str) -> list[dict[str, Any]]:
    """Load messages as flat dicts for callers that expect role/content/ts.

    Preserves LA extension fields on the message node (e.g. ``tool``).
    """
    raw = _load_raw(session_id)
    if raw is None:
        raw = _migrate_jsonl_if_needed(session_id)
    if raw is None:
        return []

    mapping = raw.get("mapping") or {}
    current = raw.get("current_node")
    if not current or current not in mapping:
        # Fallback to parsed ChatGPT messages
        obj = parse_conversation(raw)
        return [
            {
                "role": m.role,
                "content": m.content,
                **(
                    {
                        "ts": datetime.fromtimestamp(
                            m.create_time, tz=timezone.utc
                        ).isoformat(timespec="seconds"),
                        "create_time": m.create_time,
                    }
                    if m.create_time is not None
                    else {}
                ),
            }
            for m in obj.messages
        ]

    chain: list[str] = []
    node_id: str | None = current
    while node_id:
        node = mapping.get(node_id)
        if not node:
            break
        chain.append(node_id)
        node_id = node.get("parent")
    chain.reverse()

    result: list[dict[str, Any]] = []
    for nid in chain:
        node = mapping.get(nid) or {}
        message = node.get("message")
        if not isinstance(message, dict):
            continue
        role = (message.get("author") or {}).get("role")
        if role not in ("user", "assistant"):
            continue
        content_obj = message.get("content") or {}
        parts = content_obj.get("parts") or []
        text = "\n".join(str(p).strip() for p in parts if isinstance(p, str) and p.strip())
        if not text:
            continue
        entry: dict[str, Any] = {"role": role, "content": text}
        create_time = message.get("create_time")
        if isinstance(create_time, (int, float)):
            try:
                entry["ts"] = datetime.fromtimestamp(
                    create_time, tz=timezone.utc
                ).isoformat(timespec="seconds")
            except (OSError, OverflowError, ValueError):
                pass
            entry["create_time"] = create_time
        # Preserve LA extensions (tool, etc.)
        for key, value in message.items():
            if key in ("id", "author", "create_time", "content"):
                continue
            entry[key] = value
        result.append(entry)
    return result


def list_sessions() -> list[str]:
    config.ensure_data_dirs()
    ids: set[str] = set()
    for path in config.CONVERSATIONS_DIR.glob("s-*.json"):
        ids.add(path.stem)
    for path in config.CONVERSATIONS_DIR.glob("s-*.jsonl"):
        ids.add(path.stem)
    return sorted(ids)


def session_update_time(session_id: str) -> float:
    """Return conversation update_time (unix); fall back to file mtime or 0."""
    raw = _load_raw(session_id)
    if raw is None:
        raw = _migrate_jsonl_if_needed(session_id)
    if isinstance(raw, dict):
        ut = raw.get("update_time")
        if isinstance(ut, (int, float)):
            return float(ut)
    path = conversation_file_for_fingerprint(session_id)
    if path is not None and path.is_file():
        try:
            return path.stat().st_mtime
        except OSError:
            pass
    return 0.0


def list_sessions_by_update_time(*, descending: bool = True) -> list[str]:
    """Session ids ordered by update_time (newest first by default)."""
    ids = list_sessions()
    ids.sort(key=session_update_time, reverse=descending)
    return ids


def previous_session_id(current_session_id: str | None) -> str | None:
    """Most recently updated session other than ``current_session_id``."""
    for sid in list_sessions_by_update_time(descending=True):
        if current_session_id and sid == current_session_id:
            continue
        return sid
    return None


def message_create_time(message: dict[str, Any]) -> float | None:
    """Unix timestamp for a flat message dict, if available."""
    ct = message.get("create_time")
    if isinstance(ct, (int, float)):
        return float(ct)
    ts = message.get("ts")
    if isinstance(ts, str) and ts.strip():
        return _iso_to_unix(ts)
    return None


def stm_window_start_unix(now: float | None = None) -> float:
    """Start of the STM rolling window (unix seconds)."""
    hours = float(getattr(config, "STM_WINDOW_HOURS", 24) or 24)
    if hours <= 0:
        hours = 24.0
    base = now if now is not None else _now_unix()
    return base - hours * 3600.0


def list_sessions_in_stm_window(
    *,
    now: float | None = None,
    descending: bool = True,
) -> list[str]:
    """Sessions with update_time or any message inside the STM window."""
    since = stm_window_start_unix(now)
    matched: list[str] = []
    for sid in list_sessions():
        if session_update_time(sid) >= since:
            matched.append(sid)
            continue
        for msg in load_conversation(sid):
            ct = message_create_time(msg)
            if ct is not None and ct >= since:
                matched.append(sid)
                break
    matched.sort(key=session_update_time, reverse=descending)
    return matched


def format_conversation_text(messages: list[dict[str, Any]] | ChatGPTConversation) -> str:
    """Format for memory extraction (ChatGPT-compatible layout)."""
    if isinstance(messages, ChatGPTConversation):
        return format_chatgpt_conversation_text(messages)

    # Flat message list (legacy callers / tests)
    fake = ChatGPTConversation(
        conversation_id="",
        title="",
        create_time=None,
        update_time=None,
        is_do_not_remember=False,
        messages=[
            ChatGPTMessage(
                role=str(m.get("role") or "user"),
                content=str(m.get("content") or ""),
                create_time=m.get("create_time")
                if isinstance(m.get("create_time"), (int, float))
                else _iso_to_unix(str(m.get("ts") or "")),
            )
            for m in messages
            if str(m.get("content") or "").strip()
        ],
    )
    return format_chatgpt_conversation_text(fake)


def conversation_file_for_fingerprint(session_id: str) -> Path | None:
    """Prefer JSON; fall back to legacy jsonl for fingerprinting."""
    path = conversation_path(session_id)
    if path.is_file():
        return path
    legacy = _legacy_jsonl_path(session_id)
    if legacy.is_file():
        return legacy
    return None
