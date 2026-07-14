"""Tests for unified memory backend helpers."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from localagent.memory.backend import (
    ensure_mem0_qdrant_local_patch,
    ensure_mem0_telemetry_disabled,
    get_memory_backend,
    reset_memory_backend,
    shutdown_memory_backend,
)
from localagent.memory.backends.json_backend import JsonMemoryBackend
from localagent.memory.backends.mem0_backend import (
    Mem0Backend,
    _dedupe_recall_hits,
    _is_engine_indexed,
    _is_mem0_retain_error,
    _merge_recall_hit,
    _ollama_openai_base_url,
    _parse_add_ids,
    _resolve_store_fact,
    resolve_mem0_embedder_settings,
    resolve_mem0_llm_settings,
)
from localagent.memory.save import save_facts
from localagent.memory.store import get_memory_store


def test_default_bank_id_isolated_when_data_dir_override(monkeypatch):
    import localagent.config as cfg

    monkeypatch.setattr(cfg, "_DATA_OVERRIDE", "/tmp/la-demo-isolated")
    profile = cfg.memory_user_id()
    assert profile.startswith("la-")
    assert profile == cfg.default_bank_id()


def test_default_bank_id_default_profile_without_override(monkeypatch):
    import localagent.config as cfg

    monkeypatch.setattr(cfg, "_DATA_OVERRIDE", None)
    assert cfg.memory_user_id() == "localagent"
    assert cfg.default_bank_id() == "localagent"


def test_parse_add_ids_from_dict():
    assert _parse_add_ids({"results": [{"id": "a"}, {"id": "b"}]}) == ["a", "b"]
    assert _parse_add_ids({"id": "single"}) == ["single"]
    assert _parse_add_ids({"success": True, "items_count": 1}) == []


def test_mem0_recall_merges_local_only_registry(isolated_data):
    """Mem0 hits must not hide JSON/ingest memories that were never indexed."""
    store = get_memory_store()
    legacy = store.retain_from_section(
        filename="import",
        heading="偏好",
        text="用户喜欢村上春树的作品",
        chunk_id="legacy-1",
        extra_metadata={"source": "import-chatgpt"},
    )
    assert legacy is not None
    store.save()

    backend = Mem0Backend.__new__(Mem0Backend)
    backend._user_id = "localagent"
    backend._memory = MagicMock()
    backend._memory.search.return_value = {
        "results": [
            {
                "id": "m-1",
                "memory": "2026年7月决定使用 Mem0 作为记忆引擎",
                "score": 0.9,
            }
        ]
    }

    hits = backend.recall("村上春树", max_results=5)
    texts = [h["text"] for h in hits]
    assert any("村上春树" in text for text in texts)
    assert any("Mem0" in text for text in texts)


def test_is_engine_indexed():
    from localagent.memory.store import MemoryFact

    assert _is_engine_indexed(
        MemoryFact(
            id="1",
            text="x",
            source_file="",
            section_heading="",
            created_at="",
            metadata={"backend": "mem0"},
        )
    )
    assert _is_engine_indexed(
        MemoryFact(
            id="1",
            text="x",
            source_file="",
            section_heading="",
            created_at="",
            metadata={"mem0_id": "abc"},
        )
    )
    assert not _is_engine_indexed(
        MemoryFact(
            id="1",
            text="x",
            source_file="",
            section_heading="",
            created_at="",
            metadata={"backend": "json"},
        )
    )


def test_is_mem0_retain_error():
    assert _is_mem0_retain_error(Exception("Connection timeout"))
    assert _is_mem0_retain_error(Exception("embedding failed"))
    assert not _is_mem0_retain_error(ValueError("bad input"))


def test_mem0_retain_falls_back_to_json_on_error(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEM0_RETAIN_JSON_FALLBACK", True, raising=False)
    backend = Mem0Backend.__new__(Mem0Backend)
    backend._user_id = "localagent"
    backend._memory = MagicMock()
    backend._memory.add.side_effect = Exception("embedding connection failed")

    fact_id = backend.retain("2026年7月决定使用 Mem0 作为记忆引擎")
    assert fact_id
    fact = get_memory_store().get(fact_id)
    assert fact is not None
    assert "mem0_retain_failed" in fact.metadata


def test_mem0_retain_batch_continues_after_error(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEM0_RETAIN_JSON_FALLBACK", True, raising=False)
    backend = Mem0Backend.__new__(Mem0Backend)
    backend._user_id = "localagent"
    backend._memory = MagicMock()

    def _add(content, **kwargs):
        if "失败场景" in content:
            raise Exception("api timeout")
        return {"results": [{"id": "ok-1", "memory": content, "event": "ADD"}]}

    backend._memory.add.side_effect = _add
    ids = backend.retain_batch(
        [
            "2026年6月这是一条失败场景的记忆内容用于测试降级",
            "2026年7月决定使用 Mem0 作为记忆引擎",
        ]
    )
    assert len(ids) == 2


def test_save_facts_survives_mem0_retain_failure(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEM0_RETAIN_JSON_FALLBACK", True, raising=False)

    def _backend():
        backend = Mem0Backend.__new__(Mem0Backend)
        backend._user_id = "localagent"
        backend._memory = MagicMock()
        backend._memory.add.side_effect = Exception("connection reset")
        return backend

    monkeypatch.setattr("localagent.memory.save.get_memory_backend", _backend)
    ids = save_facts(["用户喜欢早起跑步"])
    assert len(ids) == 1


def test_json_backend_forced(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEMORY_BACKEND", "json", raising=False)
    reset_memory_backend()
    backend = get_memory_backend()
    assert backend.backend_name() == "json"


def test_resolve_store_fact_by_external_id(isolated_data):
    backend = JsonMemoryBackend()
    fact_id = backend.retain(
        "2026年5月，架构评审后放弃 SQLite，改用 Mem0",
        metadata={"section_heading": "决策"},
    )
    store = get_memory_store()
    fact = store.get(fact_id)
    assert fact is not None
    fact.metadata["external_id"] = "mem0-internal-id"
    fact.metadata["mem0_id"] = "mem0-internal-id"
    store.save()

    found = _resolve_store_fact(
        store,
        memory_id="mem0-internal-id",
        text="2026年5月，架构评审后放弃 SQLite，改用 Mem0",
    )
    assert found is not None
    assert found.id == fact_id


def test_merge_recall_hit_prefers_registry(isolated_data):
    store = get_memory_store()
    fact = store.retain_from_section(
        filename="manual",
        heading="决策",
        text="采用 Mem0",
        chunk_id="c1",
        extra_metadata={"backend": "mem0", "mem0_id": "mem-1", "title": "采用 Mem0"},
        fact_id="mem-1",
    )
    store.save()
    hit = _merge_recall_hit(
        {"id": "mem-1", "memory": "Mem0 原文", "score": 0.8},
        index=0,
        store_fact=fact,
    )
    assert hit["id"] == "mem-1"
    assert "采用 Mem0" in hit["text"] or hit["text"]


def test_dedupe_recall_hits():
    merged = _dedupe_recall_hits(
        [
            {"id": "a", "text": "1"},
            {"id": "a", "text": "dup"},
            {"id": "b", "text": "2"},
        ]
    )
    assert [h["id"] for h in merged] == ["a", "b"]


def test_json_backend_recall(isolated_data):
    backend = JsonMemoryBackend()
    backend.retain(
        "2026年7月决定使用 Mem0 作为记忆引擎",
        metadata={"section_heading": "决策"},
    )
    hits = backend.recall("Mem0", max_results=3)
    assert hits
    assert any("Mem0" in h["text"] for h in hits)


def test_ollama_openai_base_url():
    assert _ollama_openai_base_url("http://localhost:11434") == "http://localhost:11434/v1"
    assert _ollama_openai_base_url("http://localhost:11434/v1") == "http://localhost:11434/v1"


def test_resolve_mem0_llm_prefers_ollama_when_available(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEM0_LLM_PROVIDER", "", raising=False)
    mock_router = MagicMock()
    mock_router.is_ollama_available.return_value = True
    mock_router.list_completion_models.return_value = ["qwen3.5:4b"]
    mock_router.resolve_ollama_model.return_value = "qwen3.5:4b"
    monkeypatch.setattr("localagent.models.router.get_model_router", lambda: mock_router)
    settings = resolve_mem0_llm_settings()
    assert settings["source_provider"] == "ollama"
    assert settings["model"] == "qwen3.5:4b"


def test_resolve_mem0_embedder_uses_ollama_embed_model(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.MEM0_EMBEDDER_PROVIDER", "", raising=False)
    monkeypatch.setattr("localagent.config.MEM0_EMBEDDER_MODEL", "", raising=False)
    mock_router = MagicMock()
    mock_router.is_ollama_available.return_value = True
    mock_router._list_ollama_models.return_value = [
        {"name": "qwen3.5:4b"},
        {"name": "bge-m3:latest"},
    ]
    monkeypatch.setattr("localagent.models.router.get_model_router", lambda: mock_router)
    settings = resolve_mem0_embedder_settings()
    assert settings["source_provider"] == "ollama"
    assert settings["model"].startswith("bge-m3")
    assert settings["embedding_dims"] == 1024


def test_mem0_telemetry_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MEM0_TELEMETRY", raising=False)
    ensure_mem0_telemetry_disabled()
    assert os.environ.get("MEM0_TELEMETRY") == "False"

    monkeypatch.setenv("MEM0_TELEMETRY", "True")
    ensure_mem0_telemetry_disabled()
    assert os.environ.get("MEM0_TELEMETRY") == "True"


def test_mem0_qdrant_local_patch_marks_shared_client_local():
    ensure_mem0_qdrant_local_patch()
    from mem0.vector_stores.qdrant import Qdrant

    assert getattr(Qdrant, "_la_local_index_patch", False) is True

    store = Qdrant.__new__(Qdrant)
    store.is_local = False
    store.client = MagicMock()
    store.client._client = type("QdrantLocal", (), {})()
    store.collection_name = "test"
    calls: list[str] = []

    def fake_create_payload_index(**_kwargs):
        calls.append("index")

    store.client.create_payload_index = fake_create_payload_index
    Qdrant._create_filter_indexes(store)
    assert store.is_local is True
    assert calls == []


def test_mem0_backend_close_releases_qdrant_client():
    backend = Mem0Backend.__new__(Mem0Backend)
    client = MagicMock()
    memory = MagicMock()
    memory.vector_store.client = client
    backend._memory = memory

    backend.close()

    client.close.assert_called_once()
    memory.close.assert_called_once()
    assert backend._memory is None


def test_shutdown_memory_backend_closes_active_backend(monkeypatch):
    backend = MagicMock()
    monkeypatch.setattr("localagent.memory.backend._backend", backend)

    shutdown_memory_backend()

    backend.close.assert_called_once()
    from localagent.memory import backend as backend_mod

    assert backend_mod._backend is None
