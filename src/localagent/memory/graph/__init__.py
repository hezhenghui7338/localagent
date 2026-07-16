"""Local SQLite relation graph overlay + optional Neo4j precise queries."""

from __future__ import annotations

from localagent.memory.graph.expand import expand_hits_by_graph
from localagent.memory.graph.neo4j_store import (
    Neo4jMemoryStore,
    get_neo4j_store,
    neo4j_available,
    neo4j_enabled,
    rebuild_neo4j_graph,
    reset_neo4j_store_singleton,
    sync_fact_to_neo4j,
    unsync_fact_from_neo4j,
)
from localagent.memory.graph.precise_query import (
    classify_precise_query,
    format_precise_result,
    precise_graph_query,
)
from localagent.memory.graph.protect import protect_seed_prefix
from localagent.memory.graph.store import (
    MemoryGraphStore,
    get_memory_graph,
    graph_enabled,
    graph_expand_enabled,
    rebuild_memory_graph,
    reset_memory_graph_singleton,
    sync_fact_to_graph,
    unsync_fact_from_graph,
)

__all__ = [
    "MemoryGraphStore",
    "Neo4jMemoryStore",
    "classify_precise_query",
    "expand_hits_by_graph",
    "format_precise_result",
    "get_memory_graph",
    "get_neo4j_store",
    "graph_enabled",
    "graph_expand_enabled",
    "neo4j_available",
    "neo4j_enabled",
    "precise_graph_query",
    "protect_seed_prefix",
    "rebuild_memory_graph",
    "rebuild_neo4j_graph",
    "reset_memory_graph_singleton",
    "reset_neo4j_store_singleton",
    "sync_fact_to_graph",
    "sync_fact_to_neo4j",
    "unsync_fact_from_graph",
    "unsync_fact_from_neo4j",
]
