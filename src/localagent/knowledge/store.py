"""Lightweight JSON knowledge store for RAG chunks."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from localagent.config import KNOWLEDGE_STORE_FILE
from localagent.ingest.chunker import TextChunk

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeChunk:
    chunk_id: str
    text: str
    source_file: str
    heading: str
    index: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "source_file": self.source_file,
            "heading": self.heading,
            "index": self.index,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeChunk:
        return cls(
            chunk_id=data["chunk_id"],
            text=data["text"],
            source_file=data.get("source_file", ""),
            heading=data.get("heading", ""),
            index=int(data.get("index", 0)),
            metadata=dict(data.get("metadata", {})),
        )


def _load_raw() -> dict[str, Any]:
    if not KNOWLEDGE_STORE_FILE.exists():
        return {"chunks": []}
    try:
        return json.loads(KNOWLEDGE_STORE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("knowledge store read failed: %s", exc)
        return {"chunks": []}


def _save_raw(data: dict[str, Any]) -> None:
    KNOWLEDGE_STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_STORE_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


class KnowledgeStore:
    """Stores document chunks for retrieval."""

    def __init__(self) -> None:
        raw = _load_raw()
        self._chunks: list[KnowledgeChunk] = [
            KnowledgeChunk.from_dict(item) for item in raw.get("chunks", [])
        ]

    def index_chunks(self, *, filename: str, chunks: list[TextChunk]) -> int:
        self.remove_by_source_file(filename)
        for chunk in chunks:
            self._chunks.append(
                KnowledgeChunk(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    source_file=filename,
                    heading=chunk.heading,
                    index=chunk.index,
                    metadata=chunk.metadata,
                )
            )
        return len(chunks)

    def remove_by_source_file(self, filename: str) -> int:
        before = len(self._chunks)
        self._chunks = [c for c in self._chunks if c.source_file != filename]
        return before - len(self._chunks)

    def clear(self) -> None:
        self._chunks.clear()

    def count(self) -> int:
        return len(self._chunks)

    def save(self) -> None:
        _save_raw({"chunks": [c.to_dict() for c in self._chunks]})

    def search(self, query: str, *, top_k: int = 5) -> list[KnowledgeChunk]:
        """Simple keyword overlap search (MVP; replace with hybrid RAG later)."""
        if not query.strip():
            return []
        terms = [t.lower() for t in query.split() if len(t) > 1]
        if not terms:
            return []

        scored: list[tuple[int, KnowledgeChunk]] = []
        for chunk in self._chunks:
            text_lower = chunk.text.lower()
            score = sum(1 for term in terms if term in text_lower)
            if score:
                scored.append((score, chunk))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored[:top_k]]


_store_singleton: KnowledgeStore | None = None


def get_knowledge_store() -> KnowledgeStore:
    global _store_singleton
    if _store_singleton is None:
        _store_singleton = KnowledgeStore()
    return _store_singleton


def reset_knowledge_store_singleton() -> None:
    global _store_singleton
    _store_singleton = None
