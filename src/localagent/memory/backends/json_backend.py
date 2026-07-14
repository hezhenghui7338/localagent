"""JSON file store with embedding-primary recall + lexical supplement."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from localagent import config
from localagent.memory.enrich import enrich_memory
from localagent.memory.store import get_memory_store
from localagent.memory.value_filter import is_valuable

logger = logging.getLogger(__name__)


class JsonMemoryBackend:
    """JSON file store; recall prefers embedding, falls back to lexical scoped_recall."""

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
        from localagent.memory.decompose import decompose_recall_query
        from localagent.memory.rerank import rerank_memory_hits
        from localagent.memory.scoped_recall import (
            expand_recall_queries,
            finalize_hybrid_rank,
            rrf_fuse_hits,
            scoped_recall_multi,
        )

        candidate_n = max(max_results * 3, config.MEMORY_RERANK_CANDIDATES, 20)
        subqueries = decompose_recall_query(query) or [query]
        lexical_queries: list[str] = []
        seen: set[str] = set()
        for sub in subqueries:
            variants = (
                expand_recall_queries(sub)
                if config.MEMORY_RECALL_QUERY_EXPAND
                else [" ".join((sub or "").split())]
            )
            for item in variants:
                key = item.lower()
                if item and key not in seen:
                    seen.add(key)
                    lexical_queries.append(item)
        if not lexical_queries:
            lexical_queries = [query]

        lexical_hits = scoped_recall_multi(lexical_queries, max_results=candidate_n)
        dense_lists: list[list[dict[str, Any]]] = []
        vector_budget = max(1, config.MEMORY_RECALL_VECTOR_VARIANTS)
        for sub in subqueries[: max(1, vector_budget)]:
            dense = self._embedding_recall(sub, max_results=candidate_n)
            if dense:
                dense_lists.append(dense)

        ranked_lists: list[list[dict[str, Any]]] = []
        if dense_lists:
            ranked_lists.extend(dense_lists)
        if lexical_hits:
            ranked_lists.append(lexical_hits)
        if not ranked_lists:
            return []
        if len(ranked_lists) == 1 and not dense_lists:
            logger.debug("json recall: embedding unavailable, using lexical only")
            return lexical_hits[:max_results]

        merged = rrf_fuse_hits(ranked_lists)
        polished = finalize_hybrid_rank(query, merged, max_results=candidate_n)
        return rerank_memory_hits(query, polished, max_results=max_results)

    def _embedding_recall(self, query: str, *, max_results: int) -> list[dict[str, Any]]:
        try:
            from localagent.memory.embeddings import cosine_similarity, embed_texts
            from localagent.memory.temporal import memory_effective_time
        except Exception as exc:
            logger.debug("json embedding recall import failed: %s", exc)
            return []

        store = get_memory_store()
        facts = store.all_facts()
        if not facts or not query.strip():
            return []

        # Cap batch size for local/offline embedders.
        texts = [fact.text for fact in facts[:200]]
        try:
            vectors = embed_texts([query, *texts])
        except Exception as exc:
            logger.debug("json embedding recall failed: %s", exc)
            return []
        if len(vectors) < 2:
            return []
        q_vec = vectors[0]
        scored: list[tuple[float, dict[str, Any]]] = []
        for fact, vec in zip(facts[:200], vectors[1:]):
            sim = cosine_similarity(q_vec, vec)
            if sim <= 0:
                continue
            effective_at = memory_effective_time(
                metadata=fact.metadata,
                created_at=fact.created_at,
            )
            scored.append((
                sim,
                {
                    "id": fact.id,
                    "text": fact.text,
                    "score": sim,
                    "embedding_score": sim,
                    "source_file": fact.source_file,
                    "section_heading": fact.section_heading,
                    "created_at": effective_at,
                    "metadata": fact.metadata,
                    "source": "embedding",
                },
            ))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored[:max_results]]

    def reflect(self, query: str) -> str | None:
        """Multi-hop recall + LLM synthesis (same path as Mem0)."""
        from localagent.memory.reflect_loop import reflect_with_hops

        return reflect_with_hops(self, query)

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
