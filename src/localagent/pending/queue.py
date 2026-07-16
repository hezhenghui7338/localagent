"""JSON-backed Warm memory write queue: enqueue → approve/reject."""

from __future__ import annotations

import json
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from localagent import config

if TYPE_CHECKING:
    from localagent.memory.conversation_extract import ExtractedMemory


@dataclass
class PendingItem:
    id: str
    text: str
    kind: str  # fact | extracted
    metadata: dict[str, Any] = field(default_factory=dict)
    slots: dict[str, str] = field(default_factory=dict)
    memory_type: str = "fact"
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    title: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PendingItem:
        return cls(
            id=str(raw.get("id") or ""),
            text=str(raw.get("text") or ""),
            kind=str(raw.get("kind") or "fact"),
            metadata=dict(raw.get("metadata") or {}),
            slots={str(k): str(v) for k, v in dict(raw.get("slots") or {}).items()},
            memory_type=str(raw.get("memory_type") or "fact"),
            tags=[str(t) for t in list(raw.get("tags") or [])],
            created_at=str(raw.get("created_at") or ""),
            title=str(raw.get("title") or ""),
        )


def _queue_path() -> Path:
    return Path(config.MEMORY_PENDING_QUEUE_FILE)


def load_queue() -> list[PendingItem]:
    path = _queue_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[PendingItem] = []
    for row in items:
        if isinstance(row, dict) and row.get("id") and row.get("text"):
            out.append(PendingItem.from_dict(row))
    return out


def _atomic_write(items: list[PendingItem]) -> None:
    config.ensure_data_dirs()
    path = _queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "items": [item.to_dict() for item in items],
    }
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        suffix=".tmp",
    ) as tmp:
        tmp.write(json.dumps(payload, ensure_ascii=False, indent=2))
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def pending_count() -> int:
    return len(load_queue())


def list_pending(*, limit: int | None = None) -> list[PendingItem]:
    items = load_queue()
    if limit is not None and limit >= 0:
        return items[:limit]
    return items


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enqueue_facts(
    facts: list[str],
    *,
    metadata: dict[str, Any] | None = None,
    title: str = "",
) -> list[str]:
    """Enqueue plain fact strings. Returns pending ids (not Warm ids)."""
    if not facts:
        return []
    items = load_queue()
    meta = dict(metadata or {})
    ids: list[str] = []
    for fact in facts:
        text = str(fact).strip()
        if not text:
            continue
        pid = _new_id()
        items.append(
            PendingItem(
                id=pid,
                text=text,
                kind="fact",
                metadata=meta,
                created_at=_now(),
                title=title,
            )
        )
        ids.append(pid)
    _atomic_write(items)
    return ids


def enqueue_extracted(
    memories: list[ExtractedMemory],
    *,
    metadata: dict[str, Any] | None = None,
    title: str = "",
) -> list[str]:
    """Enqueue ExtractedMemory rows. Returns pending ids."""
    if not memories:
        return []
    items = load_queue()
    meta = dict(metadata or {})
    ids: list[str] = []
    for mem in memories:
        text = str(mem.text).strip()
        if not text:
            continue
        pid = _new_id()
        items.append(
            PendingItem(
                id=pid,
                text=text,
                kind="extracted",
                metadata=meta,
                slots=dict(mem.slots or {}),
                memory_type=str(mem.memory_type or "fact"),
                tags=list(mem.tags or [])[:2],
                created_at=_now(),
                title=title,
            )
        )
        ids.append(pid)
    _atomic_write(items)
    return ids


def _pop_ids(ids: set[str]) -> list[PendingItem]:
    items = load_queue()
    kept: list[PendingItem] = []
    removed: list[PendingItem] = []
    for item in items:
        if item.id in ids:
            removed.append(item)
        else:
            kept.append(item)
    if removed:
        _atomic_write(kept)
    return removed


def approve_ids(ids: list[str]) -> list[str]:
    """Approve pending ids → Warm retain. Returns Warm fact ids."""
    if not ids:
        return []
    removed = _pop_ids(set(ids))
    if not removed:
        return []
    from localagent.memory.conversation_extract import ExtractedMemory
    from localagent.memory.save import save_extracted, save_facts

    warm_ids: list[str] = []
    facts: list[tuple[str, dict[str, Any]]] = []
    extracted: list[tuple[ExtractedMemory, dict[str, Any]]] = []
    for item in removed:
        if item.kind == "extracted":
            extracted.append(
                (
                    ExtractedMemory(
                        text=item.text,
                        slots=item.slots,
                        memory_type=item.memory_type,
                        tags=item.tags,
                    ),
                    item.metadata,
                )
            )
        else:
            facts.append((item.text, item.metadata))

    # Group by metadata identity for batch retain when possible
    if facts:
        # save one-by-one to preserve per-item metadata differences
        for text, meta in facts:
            warm_ids.extend(save_facts([text], metadata=meta))
    for mem, meta in extracted:
        warm_ids.extend(save_extracted([mem], metadata=meta))
    return warm_ids


def reject_ids(ids: list[str]) -> int:
    """Remove pending ids without retaining. Returns count removed."""
    if not ids:
        return 0
    return len(_pop_ids(set(ids)))


def approve_all() -> list[str]:
    return approve_ids([item.id for item in load_queue()])


def reject_all() -> int:
    return reject_ids([item.id for item in load_queue()])
