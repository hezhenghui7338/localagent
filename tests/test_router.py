"""Tests for Ollama model resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from localagent.models.router import (
    ChatMessage,
    ModelRouter,
    _format_messages_for_cursor,
    reset_model_router,
)
from localagent import config


@pytest.fixture(autouse=True)
def _reset_router():
    reset_model_router()
    yield
    reset_model_router()


def test_resolve_exact_model_match():
    router = ModelRouter()
    models = [{"name": "qwen3.5:4b", "capabilities": ["completion"]}]
    with patch.object(router, "_list_ollama_models", return_value=models):
        assert router.resolve_ollama_model() == "qwen3.5:4b"


def test_resolve_fallback_by_tag():
    router = ModelRouter()
    models = [{"name": "qwen3.5:4b", "capabilities": ["completion", "tools"]}]
    with patch.object(router, "_list_ollama_models", return_value=models):
        with patch("localagent.models.router.config.OLLAMA_MODEL", "qwen3:4b"):
            assert router.resolve_ollama_model() == "qwen3.5:4b"


def test_resolve_skips_embedding_only():
    router = ModelRouter()
    models = [
        {"name": "bge-m3:latest", "capabilities": ["embedding"]},
        {"name": "qwen3.5:4b", "capabilities": ["completion"]},
    ]
    with patch.object(router, "_list_ollama_models", return_value=models):
        with patch("localagent.models.router.config.OLLAMA_MODEL", "missing:7b"):
            assert router.resolve_ollama_model() == "qwen3.5:4b"


def test_provider_order_auto_uses_env_priority(monkeypatch):
    monkeypatch.setattr(
        "localagent.models.router.config.MODEL_PROVIDER_PRIORITY",
        ["openrouter", "ollama", "cursor"],
    )
    router = ModelRouter()
    assert router._provider_order(None) == ["openrouter", "ollama", "cursor"]


def test_provider_order_prefer_puts_choice_first(monkeypatch):
    monkeypatch.setattr(
        "localagent.models.router.config.MODEL_PROVIDER_PRIORITY",
        ["openrouter", "ollama", "cursor"],
    )
    router = ModelRouter()
    assert router._provider_order("ollama") == ["ollama", "openrouter", "cursor"]
    assert router._provider_order(None) == ["openrouter", "ollama", "cursor"]


def test_format_messages_for_cursor_includes_latest_user():
    messages = [
        ChatMessage(role="system", content="You are helpful."),
        ChatMessage(role="user", content="hello"),
    ]
    prompt = _format_messages_for_cursor(messages)
    assert "System:" in prompt
    assert "User:\nhello" in prompt
    assert prompt.endswith("Assistant:")


def test_chat_ollama_disables_thinking_by_default():
    from localagent.model_servers import ModelServer

    router = ModelRouter()
    server = config.get_model_server("ollama") or ModelServer(
        provider="ollama",
        base_url=config.OLLAMA_BASE_URL,
        model=config.OLLAMA_MODEL,
        keep_alive=config.OLLAMA_KEEP_ALIVE,
        num_predict=config.OLLAMA_NUM_PREDICT,
        num_ctx=config.OLLAMA_NUM_CTX,
    )
    messages = [ChatMessage(role="user", content="hi")]
    payload = router._ollama_chat_payload(server, messages, temperature=0.3, stream=False)
    assert payload["think"] is False
    assert payload["keep_alive"] == server.keep_alive
    assert payload["options"]["num_predict"] == server.num_predict
    assert payload["options"]["num_ctx"] == server.num_ctx


def test_chat_ollama_streaming_payload():
    from localagent.model_servers import ModelServer

    router = ModelRouter()
    server = config.get_model_server("ollama") or ModelServer(provider="ollama", model=config.OLLAMA_MODEL)
    messages = [ChatMessage(role="user", content="hi")]
    payload = router._ollama_chat_payload(server, messages, temperature=0.3, stream=True)
    assert payload["stream"] is True
    assert payload["think"] is False


def test_chat_auto_falls_back_when_ollama_times_out(monkeypatch):
    router = ModelRouter()
    monkeypatch.setattr(
        "localagent.models.router.config.MODEL_PROVIDER_PRIORITY",
        ["ollama", "openrouter", "cursor"],
    )

    def fake_chat_with_provider(provider, messages, **kwargs):
        if provider == "ollama":
            raise TimeoutError("ollama first token timeout (12s)")
        if provider == "openrouter":
            router.last_provider = "openrouter"
            router.last_model = config.OPENROUTER_MODEL
            return "cloud reply"
        raise RuntimeError(f"unexpected provider {provider}")

    monkeypatch.setattr(router, "_chat_with_provider", fake_chat_with_provider)

    reply = router.chat([ChatMessage(role="user", content="hi")])
    assert reply == "cloud reply"
    assert router._ollama_slow is True
    assert router.last_provider == "openrouter"
    assert router.last_model == config.OPENROUTER_MODEL


def test_chat_auto_skips_ollama_after_slow_mark(monkeypatch):
    router = ModelRouter()
    router._ollama_slow = True
    monkeypatch.setattr(
        "localagent.models.router.config.MODEL_PROVIDER_PRIORITY",
        ["ollama", "openrouter", "cursor"],
    )

    def fake_chat_with_provider(provider, messages, **kwargs):
        if provider == "ollama":
            raise AssertionError("ollama should be skipped")
        if provider == "openrouter":
            router.last_provider = "openrouter"
            router.last_model = config.OPENROUTER_MODEL
            return "ok"
        raise RuntimeError(f"unexpected provider {provider}")

    monkeypatch.setattr(router, "_chat_with_provider", fake_chat_with_provider)

    reply = router.chat([ChatMessage(role="user", content="hi")])
    assert reply == "ok"
    assert router.last_provider == "openrouter"
    assert router.last_model == config.OPENROUTER_MODEL


def test_chat_minimax_raises_clear_error_on_missing_model():
    from localagent.model_servers import ModelServer

    router = ModelRouter()
    server = ModelServer(
        provider="minimax",
        api_key="test-key",
        base_url="https://api.minimax.io/v1",
        model="bad-model",
        timeout=120,
    )
    response = MagicMock()
    response.status_code = 404
    response.text = '{"error":{"message":"model not found"}}'
    response.json.return_value = {"error": {"message": "model not found"}}
    with patch.object(router, "_server", return_value=server):
        with patch("localagent.models.router.httpx.Client") as client_cls:
            client_cls.return_value.__enter__.return_value.post.return_value = response
            with pytest.raises(RuntimeError, match="minimax model 'bad-model' unavailable"):
                router._chat_openai_compatible(
                    server=server,
                    messages=[ChatMessage(role="user", content="hi")],
                    temperature=0.1,
                )


def test_chat_openrouter_raises_clear_error_on_missing_model():
    from localagent.model_servers import ModelServer

    router = ModelRouter()
    server = ModelServer(
        provider="openrouter",
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        model="bad/model",
        timeout=120,
    )
    response = MagicMock()
    response.status_code = 404
    response.text = '{"error":{"message":"No endpoints found"}}'
    response.json.return_value = {"error": {"message": "No endpoints found for bad/model"}}
    with patch("localagent.models.router.httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.post.return_value = response
        with pytest.raises(RuntimeError, match="openrouter model 'bad/model' unavailable"):
            router._chat_openai_compatible(
                server=server,
                messages=[ChatMessage(role="user", content="hi")],
                temperature=0.1,
            )


def test_chat_cursor_uses_cursor_sdk():
    from localagent.model_servers import ModelServer

    router = ModelRouter()
    server = ModelServer(provider="cursor", api_key="test-key", model="composer-2.5", cwd="/tmp")
    fake_result = MagicMock(status="finished", result="hello from cursor")
    with patch("cursor_sdk.Agent.prompt", return_value=fake_result) as prompt:
        reply = router._chat_cursor(
            server,
            [ChatMessage(role="user", content="hi")],
            temperature=0.1,
        )
    assert reply == "hello from cursor"
    prompt.assert_called_once()


def test_chat_retries_ollama_after_cloud_failures_when_ollama_slow(monkeypatch):
    router = ModelRouter()
    router._ollama_slow = True
    monkeypatch.setattr(
        "localagent.models.router.config.MODEL_PROVIDER_PRIORITY",
        ["ollama", "openrouter", "cursor"],
    )
    monkeypatch.setattr(router, "is_ollama_available", lambda: True)

    def fake_chat_with_provider(provider, messages, **kwargs):
        if provider == "openrouter":
            raise RuntimeError("openrouter down")
        if provider == "cursor":
            raise RuntimeError("cursor down")
        if provider == "ollama":
            auto_mode = kwargs.get("auto_mode", True)
            if auto_mode:
                raise TimeoutError("ollama first token timeout (12s)")
            router.last_provider = "ollama"
            router.last_model = config.OLLAMA_MODEL
            router._ollama_slow = False
            return "local ok"
        raise RuntimeError(f"unexpected provider {provider}")

    monkeypatch.setattr(router, "_chat_with_provider", fake_chat_with_provider)

    reply = router.chat([ChatMessage(role="user", content="hi")])
    assert reply == "local ok"
    assert router.last_provider == "ollama"
    assert router._ollama_slow is False


def test_chat_cursor_retries_before_fallback(monkeypatch):
    from localagent.model_servers import ModelServer

    router = ModelRouter()
    server = ModelServer(provider="cursor", api_key="test-key", model="composer-2.5", max_retries=2)
    attempts = {"count": 0}

    def flaky_prompt(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("cursor transient error")
        return MagicMock(status="finished", result="ok after retry")

    monkeypatch.setattr("localagent.models.router.time.sleep", lambda _s: None)
    with patch("cursor_sdk.Agent.prompt", side_effect=flaky_prompt):
        reply = router._chat_cursor(server, [ChatMessage(role="user", content="hi")], temperature=0.1)
    assert reply == "ok after retry"
    assert attempts["count"] == 3


def test_chat_falls_back_to_ollama_when_cursor_fails(monkeypatch):
    router = ModelRouter()
    monkeypatch.setattr(
        "localagent.models.router.config.MODEL_PROVIDER_PRIORITY",
        ["openrouter", "cursor", "ollama"],
    )
    monkeypatch.setattr(router, "is_ollama_available", lambda: True)

    def fake_chat_with_provider(provider, messages, **kwargs):
        if provider in ("openrouter", "cursor"):
            raise RuntimeError(f"{provider} down")
        if provider == "ollama":
            router.last_provider = "ollama"
            router.last_model = config.OLLAMA_MODEL
            return "ollama fallback"
        raise RuntimeError(f"unexpected provider {provider}")

    monkeypatch.setattr(router, "_chat_with_provider", fake_chat_with_provider)

    reply = router.chat([ChatMessage(role="user", content="hi")])
    assert reply == "ollama fallback"
    assert router.last_provider == "ollama"


def test_format_model_hint_for_minimax():
    from localagent.model_servers import ModelServer

    router = ModelRouter()
    server = ModelServer(provider="minimax", model="MiniMax-M3")
    with patch("localagent.models.router.config.get_model_server", return_value=server):
        assert router.format_model_hint("minimax") == "MiniMax-M3"


def test_format_provider_hint(monkeypatch):
    monkeypatch.setattr(
        "localagent.models.router.config.MODEL_PROVIDER_PRIORITY",
        ["ollama", "minimax", "openrouter", "cursor"],
    )
    router = ModelRouter()
    assert router.format_provider_hint("auto") == "auto(ollama→minimax→openrouter→cursor)"
    assert router.format_provider_hint("openrouter") == "openrouter(ollama→minimax→cursor)"


def test_format_last_source():
    router = ModelRouter()
    assert router.format_last_source() is None
    router.last_provider = "openrouter"
    router.last_model = "anthropic/claude-sonnet-4"
    assert router.format_last_source() == "openrouter/anthropic/claude-sonnet-4"
    router.last_model = None
    assert router.format_last_source() == "openrouter"
