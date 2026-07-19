"""Suggestion queue for non-whitelist aware actions."""

from __future__ import annotations

import json
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from localagent import config
from localagent.aware.types import utc_now

ALLOWED_CMD_PREFIXES = (
    "la ingest doc",
    "la ingest text",
    "la summarize",
    "LA ingest doc",
    "LA ingest text",
    "LA summarize",
    # legacy suggestions still present in older inbox files
    "la rag add",
    "la memory add",
    "LA rag add",
    "LA memory add",
)

# Soft suggestions (insight / wellness): approve = acknowledge + dismiss, no shell.
ACK_CMD_PREFIXES = ("# aware wellness", "# aware insight")


@dataclass
class SuggestionItem:
    id: str
    source: str
    title: str
    rationale: str
    suggested_cmd: str
    created_at: str = ""
    risk: str = "low"
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SuggestionItem:
        return cls(
            id=str(raw.get("id") or ""),
            source=str(raw.get("source") or ""),
            title=str(raw.get("title") or ""),
            rationale=str(raw.get("rationale") or ""),
            suggested_cmd=str(raw.get("suggested_cmd") or ""),
            created_at=str(raw.get("created_at") or ""),
            risk=str(raw.get("risk") or "low"),
            data=dict(raw.get("data") or {}),
        )


def _suggestions_path() -> Path:
    return Path(config.AWARE_SUGGESTIONS_FILE)


def _legacy_inbox_path() -> Path:
    return Path(config.AWARE_DIR) / "inbox.json"


def load_suggestions() -> list[SuggestionItem]:
    path = _suggestions_path()
    legacy = _legacy_inbox_path()
    if not path.exists() and legacy.exists():
        try:
            raw = json.loads(legacy.read_text(encoding="utf-8"))
            items = _parse_items(raw)
            if items:
                _atomic_write(items)
            return items
        except (OSError, json.JSONDecodeError):
            return []
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return _parse_items(raw)


def _parse_items(raw: Any) -> list[SuggestionItem]:
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[SuggestionItem] = []
    for row in items:
        if isinstance(row, dict) and row.get("id"):
            out.append(SuggestionItem.from_dict(row))
    return out


def _atomic_write(items: list[SuggestionItem]) -> None:
    config.ensure_data_dirs()
    path = _suggestions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": utc_now(), "items": [i.to_dict() for i in items]}
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


def suggestion_count() -> int:
    return len(load_suggestions())


def enqueue(
    *,
    source: str,
    title: str,
    rationale: str,
    suggested_cmd: str,
    risk: str = "low",
    data: dict[str, Any] | None = None,
) -> str:
    items = load_suggestions()
    for item in items:
        if item.suggested_cmd == suggested_cmd and item.source == source:
            return item.id
    iid = uuid.uuid4().hex[:12]
    items.append(
        SuggestionItem(
            id=iid,
            source=source,
            title=title,
            rationale=rationale,
            suggested_cmd=suggested_cmd,
            created_at=utc_now(),
            risk=risk,
            data=dict(data or {}),
        )
    )
    _atomic_write(items)
    return iid


def remove_items(ids: list[str] | None = None, *, all_items: bool = False) -> int:
    items = load_suggestions()
    if all_items:
        n = len(items)
        _atomic_write([])
        return n
    id_set = set(ids or [])
    kept = [i for i in items if i.id not in id_set]
    removed = len(items) - len(kept)
    if removed:
        _atomic_write(kept)
    return removed


def get_item(item_id: str) -> SuggestionItem | None:
    for item in load_suggestions():
        if item.id == item_id:
            return item
    return None


def is_allowed_cmd(cmd: str) -> bool:
    text = (cmd or "").strip()
    if any(text.startswith(prefix) for prefix in ACK_CMD_PREFIXES):
        return True
    return any(text.startswith(prefix) for prefix in ALLOWED_CMD_PREFIXES)


def is_ack_only_cmd(cmd: str) -> bool:
    text = (cmd or "").strip()
    return any(text.startswith(prefix) for prefix in ACK_CMD_PREFIXES)


def suggestion_ids(limit: int = 30) -> list[str]:
    return [i.id for i in load_suggestions()[:limit]]
