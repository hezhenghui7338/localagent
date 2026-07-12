"""Tests for unified memory backend helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from localagent.memory.hindsight_client import (
    HindsightBackend,
    JsonMemoryBackend,
    _dedupe_recall_hits,
    _is_hindsight_indexed,
    _is_hindsight_retain_error,
    _is_hindsight_transient_error,
    _merge_recall_hit,
    _ollama_openai_base_url,
    _parse_retain_ids,
    _resolve_store_fact,
    get_memory_backend,
    hindsight_llm_available,
    reset_memory_backend,
    resolve_hindsight_extraction_mode,
    resolve_hindsight_llm_settings,
)
from localagent.memory.save import save_facts
from localagent.memory.store import get_memory_store


def test_default_bank_id_isolated_when_data_dir_override(monkeypatch):
    monkeypatch.setenv("LA_DATA_DIR", "/tmp/la-demo-isolated")
    # Re-import would be heavy; call functions after patching module state
    import localagent.config as cfg

    monkeypatch.setattr(cfg, "_DATA_OVERRIDE", "/tmp/la-demo-isolated")
    profile = cfg.hindsight_profile()
    assert profile.startswith("la-")
    assert profile == cfg.default_bank_id()


def test_default_bank_id_default_profile_without_override(monkeypatch):
    import localagent.config as cfg

    monkeypatch.setattr(cfg, "_DATA_OVERRIDE", None)
    assert cfg.hindsight_profile() == "localagent"
    assert cfg.default_bank_id() == "localagent"


def test_parse_retain_ids_from_dict():
    assert _parse_retain_ids({"memory_ids": ["a", "b"]}) == ["a", "b"]
    assert _parse_retain_ids({"id": "single"}) == ["single"]
    assert _parse_retain_ids({"success": True, "items_count": 1}) == []


def test_hindsight_recall_merges_local_only_registry(isolated_data):
    """Hindsight hits must not hide JSON/ingest memories that were never indexed."""
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

    backend = HindsightBackend.__new__(HindsightBackend)
    backend._bank_id = "localagent"
    backend._client = MagicMock()
    backend._client.recall.return_value = [
        MagicMock(id="hs-1", text="2026年7月决定使用 Hindsight 作为记忆引擎", score=0.9),
    ]

    hits = backend.recall("村上春树", max_results=5)
    texts = [h["text"] for h in hits]
    assert any("村上春树" in text for text in texts)
    assert any("Hindsight" in text for text in texts)


def test_is_hindsight_indexed():
    from localagent.memory.store import MemoryFact

    assert _is_hindsight_indexed(
        MemoryFact(
            id="1",
            text="x",
            source_file="",
            section_heading="",
            created_at="",
            metadata={"backend": "hindsight"},
        )
    )
    assert not _is_hindsight_indexed(
        MemoryFact(
            id="2",
            text="x",
            source_file="",
            section_heading="",
            created_at="",
            metadata={"source": "ingest"},
        )
    )


def test_dedupe_recall_hits():
    hits = [
        {"id": "a", "text": "one"},
        {"id": "a", "text": "dup"},
        {"id": "b", "text": "two"},
    ]
    merged = _dedupe_recall_hits(hits)
    assert len(merged) == 2
    assert merged[0]["text"] == "one"


def test_is_hindsight_retain_error():
    assert _is_hindsight_retain_error(Exception("Fact extraction failed: 404 Not Found"))
    assert _is_hindsight_retain_error(Exception("Internal Server Error"))
    assert _is_hindsight_retain_error(Exception("Server disconnected"))
    assert not _is_hindsight_retain_error(ValueError("bad input"))


def test_is_hindsight_transient_error():
    class ServerDisconnectedError(Exception):
        pass

    assert _is_hindsight_transient_error(ServerDisconnectedError("Server disconnected"))
    assert _is_hindsight_transient_error(Exception("connection reset by peer"))
    assert not _is_hindsight_transient_error(ValueError("bad input"))


def test_hindsight_retain_retries_transient_disconnect(isolated_data):
    backend = HindsightBackend.__new__(HindsightBackend)
    backend._bank_id = "localagent"
    backend._client = MagicMock()
    backend._client.retain.side_effect = [
        Exception("Server disconnected"),
        {"memory_ids": ["hs-retry-1"]},
    ]

    fact_id = backend.retain(
        "用户拥有一台内存为16GB的Mac电脑。",
        metadata={"source": "import-chatgpt", "source_file": "conv.json"},
    )
    assert fact_id == "hs-retry-1"
    assert backend._client.retain.call_count == 2


def test_hindsight_retain_falls_back_to_json_on_disconnect(isolated_data):
    backend = HindsightBackend.__new__(HindsightBackend)
    backend._bank_id = "localagent"
    backend._client = MagicMock()
    backend._client.retain.side_effect = Exception("Server disconnected")

    fact_id = backend.retain(
        "用户拥有一台内存为16GB的Mac电脑。",
        metadata={"source": "import-chatgpt", "source_file": "conv.json"},
    )
    assert fact_id
    fact = get_memory_store().get(fact_id)
    assert fact is not None
    assert fact.metadata.get("backend") == "json"
    assert "hindsight_retain_failed" in fact.metadata
    assert backend._client.retain.call_count == 2


def test_resolve_store_fact_matches_by_text(isolated_data):
    backend = JsonMemoryBackend()
    fact_id = backend.retain(
        "2026年5月，架构评审后放弃 SQLite，改用 Hindsight",
        metadata={"source": "test", "source_file": "LA add"},
    )
    store = get_memory_store()
    resolved = _resolve_store_fact(
        store,
        memory_id="hindsight-internal-id",
        text="2026年5月，架构评审后放弃 SQLite，改用 Hindsight",
    )
    assert resolved is not None
    assert resolved.id == fact_id


def test_merge_recall_hit_uses_registry():
    class Fact:
        id = "mem-1"
        text = "本地摘要"
        source_file = "diary.md"
        section_heading = "计划"
        created_at = "2026-07-01"
        metadata = {"title": "计划", "tags": ["计划"]}

    hit = _merge_recall_hit(
        {"id": "mem-1", "text": "Hindsight 原文"},
        index=0,
        store_fact=Fact(),  # type: ignore[arg-type]
    )
    assert hit["id"] == "mem-1"
    assert hit["text"] == "本地摘要"
    assert hit["source_file"] == "diary.md"


def test_json_backend_retain_and_recall(isolated_data):
    backend = JsonMemoryBackend()
    fact_id = backend.retain(
        "2026年7月决定使用 Hindsight 作为记忆引擎",
        metadata={"source": "test", "source_file": "LA add"},
    )
    assert fact_id
    hits = backend.recall("Hindsight", max_results=3)
    assert hits
    assert any("Hindsight" in h["text"] for h in hits)


def test_hindsight_retain_falls_back_to_json_on_service_error(isolated_data):
    backend = HindsightBackend.__new__(HindsightBackend)
    backend._bank_id = "localagent"
    backend._client = MagicMock()
    backend._client.retain.side_effect = Exception(
        "Fact extraction failed: 404 Not Found for url 'http://localhost:11434/api/chat'"
    )

    fact_id = backend.retain(
        "用户拥有一台内存为16GB的Mac电脑。",
        metadata={"source": "import-chatgpt", "source_file": "conv.json"},
    )
    assert fact_id
    fact = get_memory_store().get(fact_id)
    assert fact is not None
    assert fact.metadata.get("backend") == "json"
    assert "hindsight_retain_failed" in fact.metadata


def test_hindsight_retain_batch_continues_after_service_error(isolated_data):
    backend = HindsightBackend.__new__(HindsightBackend)
    backend._bank_id = "localagent"
    backend._client = MagicMock()
    backend._client.retain.side_effect = Exception("Fact extraction failed: 404")

    ids = backend.retain_batch(
        [
            "用户正在使用 Hermes Agent 框架。",
            "用户使用 Ollama 进行本地 LLM 推理。",
        ],
        metadata={"source": "import-chatgpt"},
    )
    assert len(ids) == 2
    assert get_memory_store().count() == 2


def test_save_facts_survives_hindsight_retain_failure(isolated_data, monkeypatch):
    class FlakyBackend:
        def retain_batch(self, items, *, metadata=None):
            backend = HindsightBackend.__new__(HindsightBackend)
            backend._bank_id = "localagent"
            backend._client = MagicMock()
            backend._client.retain.side_effect = Exception("Fact extraction failed: 404")
            return backend.retain_batch(items, metadata=metadata)

    monkeypatch.setattr(
        "localagent.memory.save.get_memory_backend",
        lambda: FlakyBackend(),
    )

    ids = save_facts(
        ["用户拥有一台内存为16GB的Mac电脑。", "用户希望了解可运行的模型范围。"],
        metadata={"source": "import-chatgpt"},
    )
    assert len(ids) == 2


def test_auto_backend_uses_json_when_hindsight_llm_unavailable(isolated_data, monkeypatch):
    reset_memory_backend()
    monkeypatch.setattr("localagent.memory.hindsight_client._hindsight_importable", lambda: True)
    monkeypatch.setattr("localagent.memory.hindsight_client.hindsight_usable", lambda: False)

    backend = get_memory_backend()
    assert backend.backend_name() == "json"


def test_resolve_hindsight_extraction_mode_uses_chunks_for_ollama(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.HINDSIGHT_EXTRACTION_MODE", "auto", raising=False)
    monkeypatch.setattr(
        "localagent.memory.hindsight_client.resolve_hindsight_llm_settings",
        lambda: {"provider": "ollama", "model": "qwen3.5:4b"},
    )
    assert resolve_hindsight_extraction_mode() == "chunks"


def test_resolve_hindsight_extraction_mode_honors_explicit(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.HINDSIGHT_EXTRACTION_MODE", "concise", raising=False)
    assert resolve_hindsight_extraction_mode() == "concise"


def test_ollama_openai_base_url_appends_v1_suffix():
    assert _ollama_openai_base_url("http://localhost:11434") == "http://localhost:11434/v1"
    assert _ollama_openai_base_url("http://localhost:11434/") == "http://localhost:11434/v1"
    assert _ollama_openai_base_url("http://localhost:11434/v1") == "http://localhost:11434/v1"
    assert _ollama_openai_base_url(None) is None


def test_resolve_hindsight_llm_uses_installed_ollama_model(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.HINDSIGHT_LLM_PROVIDER", "", raising=False)
    monkeypatch.setattr("localagent.config.OLLAMA_MODEL", "qwen3:4b", raising=False)
    monkeypatch.setattr("localagent.config.MINIMAX_API_KEY", "", raising=False)

    class FakeRouter:
        def is_ollama_available(self) -> bool:
            return True

        def list_completion_models(self) -> list[str]:
            return ["qwen3.5:4b"]

        def resolve_ollama_model(self) -> str:
            return "qwen3.5:4b"

    monkeypatch.setattr(
        "localagent.models.router.get_model_router",
        lambda: FakeRouter(),
    )
    settings = resolve_hindsight_llm_settings()
    assert settings["provider"] == "ollama"
    assert settings["model"] == "qwen3.5:4b"
    assert settings["base_url"] == "http://localhost:11434/v1"


def test_resolve_hindsight_llm_prefers_ollama_when_available(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.HINDSIGHT_LLM_PROVIDER", "", raising=False)
    monkeypatch.setattr(
        "localagent.models.router.get_model_router",
        lambda: type(
            "R",
            (),
            {
                "is_ollama_available": lambda self: True,
                "list_completion_models": lambda self: ["qwen3.5:4b"],
                "resolve_ollama_model": lambda self: "qwen3.5:4b",
            },
        )(),
    )
    settings = resolve_hindsight_llm_settings()
    assert settings["provider"] == "ollama"
    assert settings["model"]


def test_resolve_hindsight_llm_falls_back_to_openrouter(isolated_data, monkeypatch):
    from localagent.model_servers import ModelServer

    monkeypatch.setattr("localagent.config.HINDSIGHT_LLM_PROVIDER", "", raising=False)
    monkeypatch.setattr(
        "localagent.models.router.get_model_router",
        lambda: type("R", (), {"is_ollama_available": lambda self: False})(),
    )
    monkeypatch.setattr(
        "localagent.config.MODEL_SERVERS",
        [
            ModelServer(
                provider="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key="test-key",
                model="anthropic/claude-sonnet-4",
            )
        ],
    )
    settings = resolve_hindsight_llm_settings()
    assert settings["provider"] == "openai"
    assert settings["api_key"] == "test-key"


def test_hindsight_llm_available_requires_ollama_or_api_key(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.HINDSIGHT_LLM_PROVIDER", "", raising=False)
    monkeypatch.setattr(
        "localagent.models.router.get_model_router",
        lambda: type(
            "R",
            (),
            {
                "is_ollama_available": lambda self: False,
                "list_completion_models": lambda self: [],
                "resolve_ollama_model": lambda self: "qwen3:4b",
            },
        )(),
    )
    monkeypatch.setattr("localagent.config.MODEL_SERVERS", [])
    assert hindsight_llm_available() is False

    from localagent.model_servers import ModelServer

    monkeypatch.setattr(
        "localagent.config.MODEL_SERVERS",
        [ModelServer(provider="openrouter", api_key="k", base_url="https://x", model="m")],
    )
    assert hindsight_llm_available() is True