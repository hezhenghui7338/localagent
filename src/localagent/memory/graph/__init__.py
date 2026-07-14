"""Local SQLite relation graph overlay for Warm memory (optional)."""

from __future__ import annotations

from localagent.memory.graph.expand import expand_hits_by_graph
from localagent.memory.graph.protect import protect_seed_prefix
from localagent.memory.graph.store import (
    MemoryGraphStore,
    get_memory_graph,
    graph_enabled,
    rebuild_memory_graph,
    reset_memory_graph_singleton,
    sync_fact_to_graph,
    unsync_fact_from_graph,
)

__all__ = [
    "MemoryGraphStore",
    "expand_hits_by_graph",
    "get_memory_graph",
    "graph_enabled",
    "protect_seed_prefix",
    "rebuild_memory_graph",
    "reset_memory_graph_singleton",
    "sync_fact_to_graph",
    "unsync_fact_from_graph",
]
