"""Tests for terminal UI helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from localagent import __version__
from localagent.ui.banner import WelcomeInfo, render_welcome
from localagent.ui.console import ActivityIndicator, emit, spinner


def test_emit(capsys):
    emit("test", "hello")
    assert capsys.readouterr().out == "[test] hello\n"


def test_spinner_non_tty(capsys):
    with spinner("sync", "working"):
        pass
    out = capsys.readouterr().out
    assert "[sync] working" in out


def test_activity_indicator_update(capsys):
    with ActivityIndicator("chat", "思考中…") as activity:
        activity.update("调用工具: search_memory")
    out = capsys.readouterr().out
    assert "[chat] 思考中…" in out
    assert "[chat] 调用工具: search_memory" in out
    assert "\r" not in out
    assert "\x1b[2K" not in out


def test_activity_indicator_streaming(capsys):
    with ActivityIndicator("chat", "思考中…") as activity:
        activity.update("生成回复…")
        activity.begin_streaming()
        print("streamed", end="", flush=True)
    out = capsys.readouterr().out
    assert "streamed" in out
    assert "\r" not in out
    assert "\x1b[2K" not in out


def test_activity_indicator_exit(capsys):
    with ActivityIndicator("chat", "思考中…") as activity:
        activity.update("调用工具: search_memory")
    out = capsys.readouterr().out
    assert "[chat] ✓" in out
    assert out.endswith("\n")
    assert "\r" not in out


def test_render_welcome_shows_project_basics():
    info = WelcomeInfo(
        version=__version__,
        provider_line="qwen3.5:4b · auto(ollama→openrouter)",
        cwd_display="~/code/LocalAgent",
        session_id="s-test123",
        memory_count=12,
        kb_count=3,
        git_line="main · 干净",
    )
    out = render_welcome(info, width=88, color=False)
    assert f"LocalAgent v{__version__}" in out
    assert "LOCAL" in out and "AGENT" in out
    assert "Your AI. Your Data. Your Mac." in out
    assert "qwen3.5:4b" in out
    assert "~/code/LocalAgent" in out
    assert "入门提示" in out
    assert "项目状态" in out
    assert "记忆 12 · kb 3" in out
    assert "main · 干净" in out
    assert "session s-test123" in out
    assert "/provider" in out
    assert "/model" in out
    assert "/help" in out
    assert "Tab" in out
    assert "╮" in out
    assert "│" in out


def test_cli_bare_la_defaults_to_chat():
    from localagent.cli import main

    with patch("localagent.cli.run_chat", return_value=0) as mock_chat:
        with patch("localagent.cli._ensure_ollama_for_chat"):
            with patch("localagent.env_config.ensure_config"):
                with patch("localagent.cli.get_task_store") as mock_store:
                    mock_store.return_value.reconcile_stale = MagicMock()
                    rc = main([])
    assert rc == 0
    mock_chat.assert_called_once()
    kwargs = mock_chat.call_args.kwargs
    assert kwargs.get("provider") == "auto"
    assert kwargs.get("session_id") is None


def test_chat_repl_prints_welcome(capsys, monkeypatch, tmp_path: Path):
    from localagent.chat_repl import ChatREPL

    inputs = iter([":q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    router = MagicMock()
    router.format_provider_hint.return_value = "auto(ollama)"
    router.format_model_hint.return_value = "qwen3.5:4b"
    router.provider_status.return_value = {"ollama": True}
    router._ollama_slow = False
    # banner late-imports from models.router; chat_repl binds at module import time
    with patch("localagent.models.router.get_model_router", return_value=router):
        with patch("localagent.chat_repl.get_model_router", return_value=router):
            ChatREPL(session_id="s-welcome", provider="auto").run()

    out = capsys.readouterr().out
    assert "LocalAgent v" in out
    assert "项目状态" in out
    assert "s-welcome" in out
