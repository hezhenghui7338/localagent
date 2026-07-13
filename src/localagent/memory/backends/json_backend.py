"""JSON file store with scoped_recall (lightweight Warm fallback)."""

from __future__ import annotations

import uuid
from typing import Any

from localagent.memory.enrich import enrich_memory
from localagent.memory.store import get_memory_store
from localagent.memory.value_filter import is_valuable


class JsonMemoryBackend:
    """JSON file store with scoped_recall."""

    def backend_name(self) -> str:
        return "json"

    def retain(self, content: str, *, metadata: dict[str, Any] | None = None) -> str:
        if not is_valuable(content):
            return ""
        store = get_memory_store()
        meta = dict(metadata or {})
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
            extra_metadata={**meta, "backend": "json"},
        )
        store.save()
        return fact.id if fact else ""

    def retain_batch(self, items: list[str], *, metadata: dict[str, Any] | None = None) -> list[str]:
        ids: list[str] = []
        for item in items:
            fact_id = self.retain(item, metadata=metadata)
            if fact_id:
                ids.append(fact_id)
        return ids

    def recall(self, query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
        from localagent.memory.scoped_recall import scoped_recall

        return scoped_recall(query, max_results=max_results)

    def reflect(self, query: str) -> str | None:
        return None

    def delete(self, fact_id: str) -> bool:
        store = get_memory_store()
        removed = store.delete(fact_id)
        if removed is None:
            return False
        store.save()
        return True

    def remove_by_source_file(self, filename: str) -> int:
        store = get_memory_store()
        removed = store.remove_by_source_file(filename)
        if removed:
            store.save()
        return removed

    def clear(self) -> int:
        store = get_memory_store()
        count = store.count()
        store.clear()
        store.save()
        return count

    def count(self) -> int:
        return get_memory_store().count()
