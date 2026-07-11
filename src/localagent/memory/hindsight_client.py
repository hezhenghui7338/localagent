"""Hindsight client with JSON store fallback."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Protocol

from localagent import config
from localagent.memory.enrich import enrich_memory
from localagent.memory.store import MemoryFact, get_memory_store
from localagent.memory.value_filter import is_valuable

logger = logging.getLogger(__name__)


class MemoryBackend(Protocol):
    def retain(self, content: str, *, metadata: dict[str, Any] | None = None) -> str: ...
    def retain_batch(self, items: list[str], *, metadata: dict[str, Any] | None = None) -> list[str]: ...
    def recall(self, query: str, *, max_results: int = 10) -> list[dict[str, Any]]: ...
    def delete(self, fact_id: str) -> bool: ...
    def clear(self) -> int: ...
    def count(self) -> int: ...


class JsonMemoryBackend:
    """Fallback when Hindsight is unavailable."""

    def retain(self, content: str, *, metadata: dict[str, Any] | None = None) -> str:
        if not is_valuable(content):
            return ""
        store = get_memory_store()
        meta = metadata or {}
        enriched = enrich_memory(
            content,
            heading=meta.get("section_heading", meta.get("source", "direct")),
            context=meta.get("source_file", "manual"),
        )
        fact = store.retain_from_section(
            filename=meta.get("source_file", "manual"),
            heading=meta.get("section_heading", meta.get("source", "direct")),
            text=content,
            chunk_id=meta.get("chunk_id", str(uuid.uuid4())[:8]),
            enrichment=enriched,
            extra_metadata=meta,
        )
        store.save()
        return fact.id if fact else ""

    def retain_batch(self, items: list[str], *, metadata: dict[str, Any] | None = None) -> list[str]:
        ids = []
        for item in items:
            fid = self.retain(item, metadata=metadata)
            if fid:
                ids.append(fid)
        return ids

    def recall(self, query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
        from localagent.memory.scoped_recall import scoped_recall

        return scoped_recall(query, max_results=max_results)

    def delete(self, fact_id: str) -> bool:
        store = get_memory_store()
        removed = store.delete(fact_id)
        if removed is None:
            return False
        store.save()
        return True

    def clear(self) -> int:
        store = get_memory_store()
        count = store.count()
        store.clear()
        store.save()
        return count

    def count(self) -> int:
        return get_memory_store().count()


class HindsightBackend:
    """Hindsight embedded client (optional dependency)."""

    def __init__(self) -> None:
        from hindsight import HindsightEmbedded  # type: ignore

        self._client = HindsightEmbedded(
            profile="localagent",
            llm_provider="ollama",
            llm_model=config.OLLAMA_MODEL,
            llm_base_url=config.OLLAMA_BASE_URL,
        )
        self._bank_id = config.DEFAULT_BANK_ID

    def retain(self, content: str, *, metadata: dict[str, Any] | None = None) -> str:
        if not is_valuable(content):
            return ""
        enriched = enrich_memory(
            content,
            heading=(metadata or {}).get("section_heading", ""),
            context=(metadata or {}).get("source_file", "manual"),
        )
        retain_meta = dict(metadata or {})
        retain_meta.update(enriched.to_metadata())
        tags = [f"topic:{tag}" for tag in enriched.tags]
        if retain_meta.get("source"):
            tags.append(f"source:{retain_meta['source']}")
        self._client.retain(
            bank_id=self._bank_id,
            content=content,
            metadata={k: str(v) for k, v in retain_meta.items() if v is not None},
            tags=tags or None,
        )
        return str(uuid.uuid4())

    def retain_batch(self, items: list[str], *, metadata: dict[str, Any] | None = None) -> list[str]:
        ids = []
        for item in items:
            fid = self.retain(item, metadata=metadata)
            if fid:
                ids.append(fid)
        return ids

    def recall(self, query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
        results = self._client.recall(bank_id=self._bank_id, query=query, max_tokens=4096)
        hits = []
        for r in getattr(results, "results", results)[:max_results]:
            hits.append({
                "text": getattr(r, "text", str(r)),
                "score": 1.0,
                "source": "hindsight",
            })
        return hits

    def delete(self, fact_id: str) -> bool:
        logger.warning("Hindsight backend does not support deleting by id (%s)", fact_id)
        return False

    def clear(self) -> int:
        # Hindsight bank reset via delete + recreate
        try:
            self._client.delete_bank(bank_id=self._bank_id)
        except Exception:
            pass
        return 0

    def count(self) -> int:
        return 0


_backend: MemoryBackend | None = None


def get_memory_backend() -> MemoryBackend:
    global _backend
    if _backend is not None:
        return _backend
    try:
        import hindsight  # noqa: F401

        _backend = HindsightBackend()
        logger.info("using Hindsight memory backend")
    except Exception as exc:
        logger.info("Hindsight unavailable (%s), using JSON fallback", exc)
        _backend = JsonMemoryBackend()
    return _backend


def reset_memory_backend() -> None:
    global _backend
    _backend = None
