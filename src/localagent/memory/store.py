"""Lightweight JSON memory store (Hindsight-compatible interface placeholder)."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from localagent.config import MEMORY_STORE_FILE
from localagent.memory.enrich import MemoryEnrichment, enrich_memory

logger = logging.getLogger(__name__)


@dataclass
class MemoryFact:
    id: str
    text: str
    source_file: str
    section_heading: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "source_file": self.source_file,
            "section_heading": self.section_heading,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryFact:
        return cls(
            id=data["id"],
            text=data["text"],
            source_file=data.get("source_file", ""),
            section_heading=data.get("section_heading", ""),
            created_at=data.get("created_at", ""),
            metadata=dict(data.get("metadata", {})),
        )


def _load_raw() -> dict[str, Any]:
    if not MEMORY_STORE_FILE.exists():
        return {"facts": []}
    try:
        return json.loads(MEMORY_STORE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("memory store read failed: %s", exc)
        return {"facts": []}


def _save_raw(data: dict[str, Any]) -> None:
    MEMORY_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_STORE_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


class MemoryStore:
    """Stores extracted facts from ingested documents."""

    def __init__(self) -> None:
        raw = _load_raw()
        self._facts: list[MemoryFact] = [
            MemoryFact.from_dict(item) for item in raw.get("facts", [])
        ]

    def retain_from_section(
        self,
        *,
        filename: str,
        heading: str,
        text: str,
        chunk_id: str,
        enrichment: MemoryEnrichment | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> MemoryFact | None:
        enriched = enrichment or enrich_memory(
            text,
            heading=heading,
            context=filename,
        )
        searchable = enriched.searchable_text.strip()
        if not searchable:
            searchable = _summarize_section(text)
        if not searchable:
            return None

        metadata = enriched.to_metadata(
            extra={
                "chunk_id": chunk_id,
                "char_count": len(text),
                **(extra_metadata or {}),
            },
        )

        fact = MemoryFact(
            id=str(uuid.uuid4()),
            text=searchable,
            source_file=filename,
            section_heading=heading or enriched.title,
            created_at=datetime.now().isoformat(timespec="seconds"),
            metadata=metadata,
        )
        self._facts.append(fact)
        return fact

    def remove_by_source_file(self, filename: str) -> int:
        before = len(self._facts)
        self._facts = [f for f in self._facts if f.source_file != filename]
        return before - len(self._facts)

    def delete(self, fact_id: str) -> MemoryFact | None:
        for index, fact in enumerate(self._facts):
            if fact.id == fact_id or fact.id.startswith(fact_id):
                return self._facts.pop(index)
        return None

    def get(self, fact_id: str) -> MemoryFact | None:
        for fact in self._facts:
            if fact.id == fact_id or fact.id.startswith(fact_id):
                return fact
        return None

    def clear(self) -> None:
        self._facts.clear()

    def count(self) -> int:
        return len(self._facts)

    def save(self) -> None:
        _save_raw({"facts": [f.to_dict() for f in self._facts]})

    def all_facts(self) -> list[MemoryFact]:
        return list(self._facts)


def _summarize_section(text: str, max_len: int = 400) -> str:
    """Extract a compact fact from section text for memory retain."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    # Prefer first substantive line; append more if short.
    summary = lines[0]
    for line in lines[1:3]:
        if len(summary) >= max_len:
            break
        summary = f"{summary}；{line}"
    if len(summary) > max_len:
        summary = summary[: max_len - 1] + "…"
    return summary


_store_singleton: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _store_singleton
    if _store_singleton is None:
        _store_singleton = MemoryStore()
    return _store_singleton


def reset_memory_store_singleton() -> None:
    global _store_singleton
    _store_singleton = None
