"""Shared pytest fixtures for isolated LocalAgent data dirs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from localagent.ingest.sync_index import reset_sync_index_singleton
from localagent.knowledge.hybrid import reset_hybrid_retriever
from localagent.knowledge.indexer import reset_knowledge_indexer
from localagent.knowledge.store import reset_knowledge_store_singleton
from localagent.memory.hindsight_client import JsonMemoryBackend, reset_memory_backend
from localagent.memory.chatgpt_import import reset_chatgpt_import_index
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
        "KNOWLEDGE_STORE_FILE": data_dir / "knowledge_store.json",
        "CORE_PROFILE_FILE": data_dir / "core_profile.json",
        "CONVERSATIONS_DIR": data_dir / "conversations",
        "CHATGPT_DATA_DIR": data_dir / "chatGPTdata",
        "CHATGPT_IMPORT_INDEX_FILE": data_dir / "chatgpt_import_index.json",
        "SESSIONS_DB": data_dir / "sessions.db",
        "CHROMA_DIR": data_dir / "chroma",
        "BM25_PATH": data_dir / "bm25.pkl",
        "INGEST_TASKS_FILE": data_dir / "ingest_tasks.json",
        "TASK_LOGS_DIR": data_dir / "task_logs",
        "AUDIT_DIR": data_dir / "audit",
        "USAGE_LOG_FILE": data_dir / "audit" / "usage.jsonl",
    }
    for key, val in paths.items():
        monkeypatch.setattr(f"localagent.config.{key}", val)

    monkeypatch.setattr("localagent.ingest.sync_index.SYNC_INDEX_FILE", paths["SYNC_INDEX_FILE"])
    monkeypatch.setattr("localagent.memory.store.MEMORY_STORE_FILE", paths["MEMORY_STORE_FILE"])
    monkeypatch.setattr("localagent.knowledge.store.KNOWLEDGE_STORE_FILE", paths["KNOWLEDGE_STORE_FILE"])

    (data_dir / "conversations").mkdir(parents=True, exist_ok=True)
    (data_dir / "chatGPTdata").mkdir(parents=True, exist_ok=True)
    (data_dir / "chroma").mkdir(parents=True, exist_ok=True)
    (data_dir / "audit").mkdir(parents=True, exist_ok=True)

    reset_sync_index_singleton()
    reset_memory_store_singleton()
    reset_knowledge_store_singleton()
    reset_knowledge_indexer()
    reset_hybrid_retriever()
    reset_memory_backend()
    reset_task_store()
    reset_chatgpt_import_index()

    mock_router = MagicMock()
    mock_router.extract_facts.return_value = []
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
        "localagent.memory.hindsight_client.get_memory_backend",
        lambda: JsonMemoryBackend(),
    )

    yield {"router": mock_router, "data_dir": data_dir, "kb_dir": kb_dir}


def write_doc(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path
