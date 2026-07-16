"""Runtime helpers: isolate LA data dirs and reset memory singletons."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def configure_data_dir(data_dir: Path | str) -> Path:
    """Point LocalAgent config + singletons at an isolated data directory."""
    path = Path(data_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    os.environ["LA_DATA_DIR"] = str(path)

    from localagent import config
    import localagent.knowledge.store as knowledge_store_mod
    import localagent.memory.store as memory_store_mod
    from localagent.ingest.sync_index import reset_sync_index_singleton
    from localagent.ingest.tasks import reset_task_store
    from localagent.knowledge.hybrid import reset_hybrid_retriever
    from localagent.knowledge.indexer import reset_knowledge_indexer
    from localagent.knowledge.store import reset_knowledge_store_singleton
    from localagent.memory.chatgpt_import import reset_chatgpt_import_index
    from localagent.memory.backend import reset_memory_backend
    from localagent.memory.store import reset_memory_store_singleton

    config._DATA_OVERRIDE = str(path)
    paths: dict[str, Any] = {
        "DATA_DIR": path,
        "KB_DIR": path / "kb",
        "SYNC_INDEX_FILE": path / "sync_index.json",
        "MEMORY_STORE_FILE": path / "memory_store.json",
        "MEMORY_GRAPH_FILE": path / "memory_graph.db",
        "KNOWLEDGE_STORE_FILE": path / "knowledge_store.json",
        "CORE_PROFILE_FILE": path / "core_profile.json",
        "CONVERSATIONS_DIR": path / "conversations",
        "CHATGPT_DATA_DIR": path / "chatGPTdata",
        "CHATGPT_IMPORT_INDEX_FILE": path / "chatgpt_import_index.json",
        "SESSIONS_DB": path / "sessions.db",
        "CHROMA_DIR": path / "chroma",
        "BM25_PATH": path / "bm25.pkl",
        "INGEST_TASKS_FILE": path / "ingest_tasks.json",
        "TASK_LOGS_DIR": path / "task_logs",
        "AUDIT_DIR": path / "audit",
        "USAGE_LOG_FILE": path / "audit" / "usage.jsonl",
        "EVENTS_LOG_FILE": path / "audit" / "events.jsonl",
    }
    for key, value in paths.items():
        setattr(config, key, value)

    # Modules that imported Path constants by value need an explicit refresh.
    memory_store_mod.MEMORY_STORE_FILE = paths["MEMORY_STORE_FILE"]
    knowledge_store_mod.KNOWLEDGE_STORE_FILE = paths["KNOWLEDGE_STORE_FILE"]

    for dirname in (
        paths["KB_DIR"],
        paths["CONVERSATIONS_DIR"],
        paths["CHATGPT_DATA_DIR"],
        paths["CHROMA_DIR"],
        paths["TASK_LOGS_DIR"],
        paths["AUDIT_DIR"],
    ):
        Path(dirname).mkdir(parents=True, exist_ok=True)

    from localagent.memory.graph import reset_memory_graph_singleton, reset_neo4j_store_singleton

    reset_sync_index_singleton()
    reset_memory_store_singleton()
    reset_memory_graph_singleton()
    reset_neo4j_store_singleton()
    reset_knowledge_store_singleton()
    reset_knowledge_indexer()
    reset_hybrid_retriever()
    reset_memory_backend()
    reset_task_store()
    reset_chatgpt_import_index()
    return path
