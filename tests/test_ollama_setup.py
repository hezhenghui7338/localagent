"""Tests for Ollama bootstrap helpers."""

from __future__ import annotations

from localagent.ollama_setup import (
    OllamaSetupResult,
    ensure_ollama_ready,
    has_model,
    pick_available_completion_model,
)


def test_ensure_ollama_ready_skips(monkeypatch):
    monkeypatch.setenv("LA_SKIP_OLLAMA_SETUP", "1")
    result = ensure_ollama_ready(model="qwen3.5:4b")
    assert result.skipped is True
    assert isinstance(result, OllamaSetupResult)


def test_has_model_matches_prefix(monkeypatch):
    monkeypatch.setattr(
        "localagent.ollama_setup.list_local_model_names",
        lambda base_url=None: ["qwen3.5:4b", "llama3.2:3b"],
    )
    assert has_model("qwen3.5:4b") is True
    assert has_model("missing") is False


def test_pick_prefers_running_model(monkeypatch):
    monkeypatch.setattr(
        "localagent.ollama_setup.list_local_models",
        lambda base_url=None: [
            {"name": "llama3.2:3b", "capabilities": ["completion"]},
            {"name": "mistral:7b", "capabilities": ["completion"]},
            {"name": "bge-m3:latest", "capabilities": ["embedding"]},
        ],
    )
    monkeypatch.setattr(
        "localagent.ollama_setup.list_running_completion_model_names",
        lambda base_url=None: ["mistral:7b"],
    )
    assert pick_available_completion_model("qwen3.5:4b") == "mistral:7b"


def test_pick_uses_preferred_when_installed(monkeypatch):
    monkeypatch.setattr(
        "localagent.ollama_setup.list_local_models",
        lambda base_url=None: [
            {"name": "llama3.2:3b", "capabilities": ["completion"]},
            {"name": "qwen3.5:4b", "capabilities": ["completion"]},
        ],
    )
    monkeypatch.setattr(
        "localagent.ollama_setup.list_running_completion_model_names",
        lambda base_url=None: ["llama3.2:3b"],
    )
    assert pick_available_completion_model("qwen3.5:4b") == "qwen3.5:4b"


def test_ensure_ollama_ready_declines_install(monkeypatch):
    monkeypatch.delenv("LA_SKIP_OLLAMA_SETUP", raising=False)
    monkeypatch.setattr("localagent.ollama_setup.is_ollama_installed", lambda: False)
    monkeypatch.setattr("localagent.ollama_setup.prompt_yes_no", lambda *a, **k: False)

    result = ensure_ollama_ready(model="qwen3.5:4b", prompt=True)
    assert result.declined is True
    assert result.skipped is True
    assert result.installed is False
    assert "跳过" in result.message


def test_ensure_ollama_ready_adopts_existing_model(monkeypatch):
    monkeypatch.delenv("LA_SKIP_OLLAMA_SETUP", raising=False)
    monkeypatch.setattr("localagent.ollama_setup.is_ollama_installed", lambda: True)
    monkeypatch.setattr(
        "localagent.ollama_setup.is_ollama_reachable",
        lambda base_url=None, timeout=2.0: True,
    )
    monkeypatch.setattr(
        "localagent.ollama_setup.pick_available_completion_model",
        lambda preferred=None, base_url=None: "llama3.2:3b",
    )
    monkeypatch.setattr(
        "localagent.ollama_setup._persist_ollama_model",
        lambda model: True,
    )

    pulled: list[str] = []
    monkeypatch.setattr(
        "localagent.ollama_setup.pull_model",
        lambda model, log=None: pulled.append(model),
    )

    result = ensure_ollama_ready(model="qwen3.5:4b", prompt=True)
    assert result.model_ready is True
    assert result.adopted_existing is True
    assert result.model == "llama3.2:3b"
    assert pulled == []
    assert "llama3.2:3b" in result.message


def test_ensure_ollama_ready_installs_when_user_accepts(monkeypatch):
    calls: list[str] = []
    installed = {"ok": False}

    monkeypatch.delenv("LA_SKIP_OLLAMA_SETUP", raising=False)

    def _installed():
        return installed["ok"]

    def _install(log=None):
        calls.append("install")
        installed["ok"] = True

    monkeypatch.setattr("localagent.ollama_setup.is_ollama_installed", _installed)
    monkeypatch.setattr("localagent.ollama_setup.install_ollama", _install)
    monkeypatch.setattr("localagent.ollama_setup.prompt_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(
        "localagent.ollama_setup.is_ollama_reachable",
        lambda base_url=None, timeout=2.0: True,
    )
    monkeypatch.setattr(
        "localagent.ollama_setup.pick_available_completion_model",
        lambda preferred=None, base_url=None: preferred if "pull" in calls else None,
    )
    monkeypatch.setattr(
        "localagent.ollama_setup.has_model",
        lambda model, base_url=None: "pull" in calls,
    )
    monkeypatch.setattr(
        "localagent.ollama_setup.pull_model",
        lambda model, log=None: calls.append("pull"),
    )

    result = ensure_ollama_ready(model="qwen3.5:4b", prompt=True)
    assert calls == ["install", "pull"]
    assert result.installed_now is True
    assert result.pulled_now is True
    assert result.model_ready is True


def test_ensure_ollama_ready_assume_yes_skips_prompt(monkeypatch):
    calls: list[str] = []
    installed = {"ok": False}

    monkeypatch.delenv("LA_SKIP_OLLAMA_SETUP", raising=False)

    def _installed():
        return installed["ok"]

    def _install(log=None):
        calls.append("install")
        installed["ok"] = True

    def _fail_prompt(*_a, **_k):
        raise AssertionError("should not prompt when assume_yes=True")

    monkeypatch.setattr("localagent.ollama_setup.is_ollama_installed", _installed)
    monkeypatch.setattr("localagent.ollama_setup.install_ollama", _install)
    monkeypatch.setattr("localagent.ollama_setup.prompt_yes_no", _fail_prompt)
    monkeypatch.setattr(
        "localagent.ollama_setup.is_ollama_reachable",
        lambda base_url=None, timeout=2.0: True,
    )
    monkeypatch.setattr(
        "localagent.ollama_setup.pick_available_completion_model",
        lambda preferred=None, base_url=None: "qwen3.5:4b",
    )

    result = ensure_ollama_ready(model="qwen3.5:4b", assume_yes=True)
    assert calls == ["install"]
    assert result.model_ready is True
