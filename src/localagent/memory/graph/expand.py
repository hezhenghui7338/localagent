"""Expand recall seed hits via SQLite and/or Neo4j graph hops."""

from __future__ import annotations

from typing import Any

from localagent import config
from localagent.memory.entities import extract_entities
from localagent.memory.graph.store import get_memory_graph, graph_enabled
from localagent.memory.store import get_memory_store
from localagent.memory.temporal import memory_effective_time


def expand_hits_by_graph(
    query: str,
    hits: list[dict[str, Any]],
    *,
    facts: list[Any] | None = None,
    hops: int | None = None,
    max_extras: int | None = None,
) -> list[dict[str, Any]]:
    """Append fact hits discovered by 1–N hop graph traversal from seed entities.

    Uses Neo4j when ``LA_NEO4J=1`` (preferred for precise-index experiments);
    otherwise falls back to the optional SQLite overlay when ``LA_MEMORY_GRAPH=1``.
    """
    from localagent.memory.graph.neo4j_store import (
        get_neo4j_store,
        neo4j_available,
        neo4j_enabled,
    )

    use_neo4j = neo4j_enabled() and neo4j_available()
    use_sqlite = graph_enabled()
    if (not use_neo4j and not use_sqlite) or not hits:
        return hits

    hop_n = config.MEMORY_GRAPH_HOPS if hops is None else hops
    if hop_n <= 0:
        return hits

    extra_budget = (
        max(4, config.MEMORY_GRAPH_MAX_EXTRAS)
        if max_extras is None
        else max(0, max_extras)
    )
    if extra_budget <= 0:
        return hits

    graph: Any = None
    source_label = "graph"
    if use_neo4j:
        neo = get_neo4j_store()
        # Prefer Neo4j when populated; otherwise fall back to SQLite if enabled.
        if neo.stats().get("entities", 0) > 0 or not use_sqlite:
            graph = neo
            source_label = "neo4j"
    if graph is None and use_sqlite:
        graph = get_memory_graph()
        source_label = "graph"
    if graph is None:
        return hits
    store_facts = list(facts) if facts is not None else list(get_memory_store().all_facts())
    by_id = {str(fact.id): fact for fact in store_facts}

    seed_ids = {str(hit.get("id") or "") for hit in hits if hit.get("id")}
    existing_ids = set(seed_ids)

    seed_names: list[str] = []
    seed_names.extend(extract_entities(query, limit=10))
    for hit in hits[:12]:
        meta = hit.get("metadata") or {}
        ents = meta.get("entities") or []
        if isinstance(ents, list):
            seed_names.extend(str(e) for e in ents if e)
        slots = meta.get("slots") or {}
        if isinstance(slots, dict):
            for key in ("subject", "object", "location", "outcome"):
                val = slots.get(key)
                if val:
                    seed_names.append(str(val))

    entity_ids = graph.resolve_entity_ids(seed_names)
    if seed_ids:
        for fact_id in list(seed_ids)[:24]:
            fact = by_id.get(fact_id)
            if fact is None:
                continue
            meta = getattr(fact, "metadata", None) or {}
            ents = meta.get("entities") or []
            if isinstance(ents, list):
                entity_ids.extend(graph.resolve_entity_ids([str(e) for e in ents if e]))

    seen_e: set[str] = set()
    uniq_entities: list[str] = []
    for eid in entity_ids:
        if eid not in seen_e:
            seen_e.add(eid)
            uniq_entities.append(eid)

    if not uniq_entities:
        return hits

    expanded_entities = graph.neighbor_entity_ids(uniq_entities, hops=hop_n)
    related_fact_ids = graph.fact_ids_for_entities(expanded_entities) - existing_ids
    if not related_fact_ids:
        return hits

    extras: list[dict[str, Any]] = []
    seed_scores = [float(hit.get("score") or 0.0) for hit in hits]
    floor = (min(seed_scores) if seed_scores else 0.1) * 0.3
    floor = max(0.01, min(floor, 0.2))
    for fact_id in related_fact_ids:
        fact = by_id.get(fact_id)
        if fact is None:
            continue
        effective_at = memory_effective_time(
            metadata=fact.metadata,
            created_at=fact.created_at,
        )
        extras.append(
            {
                "id": fact.id,
                "text": fact.text,
                "score": floor,
                "rrf_score": 0.0,
                "graph_score": 0.0,
                "source_file": fact.source_file,
                "section_heading": fact.section_heading,
                "created_at": effective_at,
                "metadata": fact.metadata,
                "source": source_label,
            }
        )
        if len(extras) >= extra_budget:
            break

    if not extras:
        return hits

    if source_label == "graph" and hasattr(graph, "paths_between_facts"):
        paths = graph.paths_between_facts(seed_ids, {e["id"] for e in extras}, max_paths=6)
        if paths:
            for hit in hits:
                hit.setdefault("graph_paths", paths)
            for extra in extras:
                extra["graph_paths"] = paths

    return hits + extras
