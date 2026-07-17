"""Shared pytest fixtures for isolated LocalAgent data dirs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from localagent.ingest.sync_index import reset_sync_index_singleton
from localagent.knowledge.hybrid import reset_hybrid_retriever
from localagent.knowledge.indexer import reset_knowledge_indexer
from localagent.knowledge.store import reset_knowledge_store_singleton
from localagent.memory.backends.json_backend import JsonMemoryBackend
from localagent.memory.backend import reset_memory_backend
from localagent.memory.chatgpt_import import reset_chatgpt_import_index
from localagent.memory.graph import reset_memory_graph_singleton
from localagent.memory.store import reset_memory_store_singleton
from localagent.ingest.tasks import reset_task_store


@pytest.fixture(autouse=True)
def isolated_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """Redirect all runtime data paths to a temp directory."""
    if "/tests/e2e/" in str(request.fspath):
        yield {}
        return

    data_dir = tmp_path / "data"
    kb_dir = data_dir / "kb"
    kb_dir.mkdir(parents=True)

    paths = {
        "DATA_DIR": data_dir,
        "KB_DIR": kb_dir,
        "SYNC_INDEX_FILE": data_dir / "sync_index.json",
        "MEMORY_STORE_FILE": data_dir / "memory_store.json",
        "MEMORY_GRAPH_FILE": data_dir / "memory_graph.db",
        "KNOWLEDGE_STORE_FILE": data_dir / "knowledge_store.json",
        "CORE_PROFILE_FILE": data_dir / "core_profile.json",
        "CONVERSATIONS_DIR": data_dir / "conversations",
        "CHATGPT_DATA_DIR": data_dir / "chatGPTdata",
        "CHATGPT_IMPORT_INDEX_FILE": data_dir / "chatgpt_import_index.json",
        "CHAT_INGEST_INDEX_FILE": data_dir / "chat_ingest_index.json",
        "SESSIONS_DB": data_dir / "sessions.db",
        "CHROMA_DIR": data_dir / "chroma",
        "BM25_PATH": data_dir / "bm25.pkl",
        "INGEST_TASKS_FILE": data_dir / "ingest_tasks.json",
        "TASK_LOGS_DIR": data_dir / "task_logs",
        "AUDIT_DIR": data_dir / "audit",
        "USAGE_LOG_FILE": data_dir / "audit" / "usage.jsonl",
        "EVENTS_LOG_FILE": data_dir / "audit" / "events.jsonl",
        "LOGS_DIR": data_dir / "logs",
        "APP_LOG_FILE": data_dir / "logs" / "localagent.log",
        "NEWS_DIR": data_dir / "news",
        "NEWS_DB_FILE": data_dir / "news" / "articles.sqlite",
        "NEWS_PROFILE_FILE": data_dir / "news" / "news_profile.json",
        "NEWS_SYNC_STATE_FILE": data_dir / "news" / "sync_state.json",
        "NEWS_SYNC_LOG_FILE": data_dir / "news" / "sync.log",
        "NEWS_CACHE_DIR": data_dir / "news" / "cache",
    }
    for key, val in paths.items():
        monkeypatch.setattr(f"localagent.config.{key}", val)

    monkeypatch.setattr("localagent.config.MEMORY_BACKEND", "json")
    monkeypatch.setattr("localagent.config.TOOL_APPROVAL", "off")
    # Tests expect immediate Warm retain unless they exercise the pending gate.
    monkeypatch.setattr("localagent.config.MEMORY_APPROVAL_AUTO", True)
    monkeypatch.setattr("localagent.config.MEMORY_APPROVAL_REQUIRED", False)
    monkeypatch.setattr(
        "localagent.config.MEMORY_PENDING_QUEUE_FILE",
        data_dir / "pending_queue.json",
    )
    # Unit tests use regex pin by default; LLM pin tests enable + mock explicitly.
    monkeypatch.setattr("localagent.config.PROFILE_PIN_LLM", False)
    monkeypatch.setattr("localagent.config.PROFILE_PIN_REGEX_FALLBACK", True)
    # Router is mocked below; keep LLM ingest path enabled so extract_memories mocks apply.
    monkeypatch.setattr("localagent.config.INGEST_USE_LLM", True)
    monkeypatch.setattr("localagent.config.INGEST_WHOLE_SECTION_WARM", True)
    monkeypatch.setattr("localagent.ingest.sync_index.SYNC_INDEX_FILE", paths["SYNC_INDEX_FILE"])
    monkeypatch.setattr("localagent.memory.store.MEMORY_STORE_FILE", paths["MEMORY_STORE_FILE"])
    monkeypatch.setattr("localagent.knowledge.store.KNOWLEDGE_STORE_FILE", paths["KNOWLEDGE_STORE_FILE"])

    (data_dir / "conversations").mkdir(parents=True, exist_ok=True)
    (data_dir / "chatGPTdata").mkdir(parents=True, exist_ok=True)
    (data_dir / "chroma").mkdir(parents=True, exist_ok=True)
    (data_dir / "mem0").mkdir(parents=True, exist_ok=True)
    (data_dir / "audit").mkdir(parents=True, exist_ok=True)
    (data_dir / "news" / "cache").mkdir(parents=True, exist_ok=True)

    reset_sync_index_singleton()
    reset_memory_store_singleton()
    reset_memory_graph_singleton()
    reset_knowledge_store_singleton()
    reset_knowledge_indexer()
    reset_hybrid_retriever()
    reset_memory_backend()
    reset_task_store()
    reset_chatgpt_import_index()

    # Avoid live Ollama/embedder hangs in unit tests; BM25 still indexes Cold chunks.
    monkeypatch.setattr(
        "localagent.knowledge.chroma_store.ChromaStore.upsert",
        lambda self, **kwargs: None,
    )
    monkeypatch.setattr(
        "localagent.knowledge.chroma_store.ChromaStore.query",
        lambda self, query, top_k: [],
    )
    monkeypatch.setattr(
        "localagent.knowledge.chroma_store.ChromaStore.delete_by_source_file",
        lambda self, source_file: None,
    )
    monkeypatch.setattr(
        "localagent.knowledge.chroma_store.ChromaStore.delete_by_origin",
        lambda self, origin: None,
    )

    mock_router = MagicMock()
    mock_router.extract_facts.return_value = []
    mock_router.extract_memories.return_value = []
    mock_router.extract_profile_updates.return_value = []
    mock_router.chat.return_value = "测试回复"
    router_targets = (
        "localagent.models.router.get_model_router",
        "localagent.chat_repl.get_model_router",
        "localagent.memory.rememorize.get_model_router",
        "localagent.memory.chatgpt_import.get_model_router",
        "localagent.memory.exit_extract.get_model_router",
        "localagent.agent.runtime.get_model_router",
    )
    for target in router_targets:
        monkeypatch.setattr(target, lambda: mock_router)
    monkeypatch.setattr(
        "localagent.memory.backend.get_memory_backend",
        lambda: JsonMemoryBackend(),
    )

    yield {"router": mock_router, "data_dir": data_dir, "kb_dir": kb_dir}


def write_doc(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path
