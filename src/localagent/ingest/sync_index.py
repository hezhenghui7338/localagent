"""File-level sync index: tracks which kb/ files have been indexed."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from localagent.config import SYNC_INDEX_FILE

logger = logging.getLogger(__name__)


@dataclass
class FileSyncRecord:
    path: str
    content_hash: str
    synced_at: str
    memory_fact_count: int = 0
    knowledge_chunk_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "content_hash": self.content_hash,
            "synced_at": self.synced_at,
            "memory_fact_count": self.memory_fact_count,
            "knowledge_chunk_count": self.knowledge_chunk_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileSyncRecord:
        return cls(
            path=data["path"],
            content_hash=data["content_hash"],
            synced_at=data["synced_at"],
            memory_fact_count=int(data.get("memory_fact_count", 0)),
            knowledge_chunk_count=int(data.get("knowledge_chunk_count", 0)),
        )


def content_hash(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def _load_raw() -> dict[str, Any]:
    if not SYNC_INDEX_FILE.exists():
        return {}
    try:
        return json.loads(SYNC_INDEX_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("sync_index read failed: %s", exc)
        return {}


def _save_raw(data: dict[str, Any]) -> None:
    SYNC_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYNC_INDEX_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


class SyncIndex:
    """Tracks indexed files by basename under data/kb/."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = _load_raw()

    def get(self, filename: str) -> FileSyncRecord | None:
        entry = self._data.get(filename)
        if not entry:
            return None
        return FileSyncRecord.from_dict(entry)

    def should_skip(self, filename: str, current_hash: str, *, force: bool = False) -> bool:
        if force:
            return False
        record = self.get(filename)
        return record is not None and record.content_hash == current_hash

    def upsert(
        self,
        filename: str,
        *,
        path: str,
        current_hash: str,
        memory_fact_count: int,
        knowledge_chunk_count: int,
    ) -> FileSyncRecord:
        record = FileSyncRecord(
            path=path,
            content_hash=current_hash,
            synced_at=datetime.now().isoformat(timespec="seconds"),
            memory_fact_count=memory_fact_count,
            knowledge_chunk_count=knowledge_chunk_count,
        )
        self._data[filename] = record.to_dict()
        return record

    def remove(self, filename: str) -> None:
        self._data.pop(filename, None)

    def clear(self) -> None:
        self._data.clear()

    def save(self) -> None:
        _save_raw(self._data)

    def all_filenames(self) -> list[str]:
        return sorted(self._data.keys())

    def raw(self) -> dict[str, Any]:
        return dict(self._data)


_index_singleton: SyncIndex | None = None


def get_sync_index() -> SyncIndex:
    global _index_singleton
    if _index_singleton is None:
        _index_singleton = SyncIndex()
    return _index_singleton


def reset_sync_index_singleton() -> None:
    global _index_singleton
    _index_singleton = None
