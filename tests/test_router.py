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
    router = ModelRouter()
    messages = [ChatMessage(role="user", content="hi")]
    payload = router._ollama_chat_payload(messages, temperature=0.3, stream=False)
    assert payload["think"] is False
    assert payload["keep_alive"] == config.OLLAMA_KEEP_ALIVE
    assert payload["options"]["num_predict"] == config.OLLAMA_NUM_PREDICT
    assert payload["options"]["num_ctx"] == config.OLLAMA_NUM_CTX


def test_chat_ollama_streaming_payload():
    router = ModelRouter()
    messages = [ChatMessage(role="user", content="hi")]
    payload = router._ollama_chat_payload(messages, temperature=0.3, stream=True)
    assert payload["stream"] is True
    assert payload["think"] is False


def test_chat_auto_falls_back_when_ollama_times_out(monkeypatch):
    router = ModelRouter()
    monkeypatch.setattr(
        "localagent.models.router.config.MODEL_PROVIDER_PRIORITY",
        ["ollama", "openrouter", "cursor"],
    )

    def slow_ollama(*args, **kwargs):
        raise TimeoutError("ollama first token timeout (12s)")

    def fast_openrouter(messages, *, temperature):
        return "cloud reply", {"prompt_tokens": 1, "completion_tokens": 2}

    monkeypatch.setattr(router, "_chat_ollama", slow_ollama)
    monkeypatch.setattr(router, "_chat_openrouter", fast_openrouter)
    monkeypatch.setattr(router, "_record_usage", lambda *a, **k: None)

    reply = router.chat([ChatMessage(role="user", content="hi")])
    assert reply == "cloud reply"
    assert router._ollama_slow is True
    assert router.last_provider == "openrouter"
    assert router.last_model == config.OPENROUTER_MODEL


def test_chat_auto_skips_ollama_after_slow_mark(monkeypatch):
    router = ModelRouter()
    router._ollama_slow = True

    def fast_openrouter(messages, *, temperature):
        return "ok", {"prompt_tokens": 1, "completion_tokens": 1}

    monkeypatch.setattr(router, "_chat_openrouter", fast_openrouter)
    monkeypatch.setattr(router, "_record_usage", lambda *a, **k: None)
    monkeypatch.setattr(
        router,
        "_chat_ollama",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("ollama should be skipped")),
    )

    reply = router.chat([ChatMessage(role="user", content="hi")])
    assert reply == "ok"
    assert router.last_provider == "openrouter"
    assert router.last_model == config.OPENROUTER_MODEL


def test_chat_openrouter_raises_clear_error_on_missing_model():
    router = ModelRouter()
    response = MagicMock()
    response.status_code = 404
    response.text = '{"error":{"message":"No endpoints found"}}'
    response.json.return_value = {"error": {"message": "No endpoints found for bad/model"}}
    with patch("localagent.models.router.config.OPENROUTER_API_KEY", "test-key"):
        with patch("localagent.models.router.config.OPENROUTER_MODEL", "bad/model"):
            with patch("localagent.models.router.httpx.Client") as client_cls:
                client_cls.return_value.__enter__.return_value.post.return_value = response
                with pytest.raises(RuntimeError, match="openrouter model 'bad/model' unavailable"):
                    router._chat_openrouter([ChatMessage(role="user", content="hi")], temperature=0.1)[0]


def test_chat_cursor_uses_cursor_sdk():
    router = ModelRouter()
    fake_result = MagicMock(status="finished", result="hello from cursor")
    with patch("localagent.models.router.config.CURSOR_API_KEY", "test-key"):
        with patch("localagent.models.router.config.CURSOR_MODEL", "composer-2.5"):
            with patch("localagent.models.router.config.CURSOR_CWD", "/tmp"):
                with patch("cursor_sdk.Agent.prompt", return_value=fake_result) as prompt:
                    reply = router._chat_cursor(
                        [ChatMessage(role="user", content="hi")],
                        temperature=0.1,
                    )
    assert reply == "hello from cursor"
    prompt.assert_called_once()


def test_format_provider_hint():
    router = ModelRouter()
    assert router.format_provider_hint("auto") == "auto(ollama→openrouter→cursor)"
    assert router.format_provider_hint("openrouter") == "openrouter(ollama→cursor)"


def test_format_last_source():
    router = ModelRouter()
    assert router.format_last_source() is None
    router.last_provider = "openrouter"
    router.last_model = "anthropic/claude-sonnet-4"
    assert router.format_last_source() == "openrouter/anthropic/claude-sonnet-4"
    router.last_model = None
    assert router.format_last_source() == "openrouter"
