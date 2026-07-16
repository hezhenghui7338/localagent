"""Keep seed recall winners ahead of graph-expanded fillers."""

from __future__ import annotations

from typing import Any

from localagent import config


def protect_seed_prefix(
    seed_hits: list[dict[str, Any]],
    ranked_hits: list[dict[str, Any]],
    *,
    max_results: int,
    protect_n: int | None = None,
    force_graph_n: int | None = None,
) -> list[dict[str, Any]]:
    """Pin seed-only winners, then blend in graph extras for coverage.

    1. Protected prefix = top-N from seed-only ranking (stabilizes Hit@1).
    2. Remaining slots prefer expanded/reranked order.
    3. Force-insert up to ``force_graph_n`` ``source=graph`` hits after the
       prefix so multi-hop evidence can still enter top-5/8 when the
       cross-encoder under-ranks them.
    """
    n = config.MEMORY_GRAPH_PROTECT_TOP if protect_n is None else protect_n
    force_n = (
        config.MEMORY_GRAPH_FORCE_IN_TOP if force_graph_n is None else force_graph_n
    )
    if not ranked_hits:
        return []
    if n <= 0 and force_n <= 0:
        return ranked_hits[:max_results]

    by_id = {
        str(hit.get("id") or ""): hit
        for hit in ranked_hits
        if hit.get("id")
    }
    prefix: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in seed_hits:
        if len(prefix) >= max(0, n):
            break
        hit_id = str(hit.get("id") or "")
        if not hit_id or hit_id in seen:
            continue
        chosen = dict(by_id.get(hit_id) or hit)
        chosen["graph_protected"] = True
        prefix.append(chosen)
        seen.add(hit_id)

    rest = [
        hit
        for hit in ranked_hits
        if str(hit.get("id") or "") not in seen
    ]

    if force_n > 0:
        graph_pool = [
            dict(hit)
            for hit in ranked_hits
            if str(hit.get("source") or "") in {"graph", "neo4j"}
            and str(hit.get("id") or "") not in seen
        ]
        forced: list[dict[str, Any]] = []
        for hit in graph_pool[:force_n]:
            hit_id = str(hit.get("id") or "")
            if not hit_id or hit_id in seen:
                continue
            item = dict(hit)
            item["graph_forced"] = True
            forced.append(item)
            seen.add(hit_id)
        # Drop forced ids from rest to avoid duplicates.
        rest = [hit for hit in rest if str(hit.get("id") or "") not in seen]
        # Place forced graph hits right after the protected prefix.
        merged = prefix + forced + rest
    else:
        merged = prefix + rest

    return merged[:max_results]
