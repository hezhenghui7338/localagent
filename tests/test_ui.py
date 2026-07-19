"""Tests for terminal UI helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from localagent import __version__
from localagent.ui.banner import WelcomeInfo, collect_welcome_info, format_web_search_hint, render_welcome
from localagent.ui.console import ActivityIndicator, emit, read_repl_line, spinner


def test_emit(capsys):
    emit("test", "hello")
    assert capsys.readouterr().out == "[test] hello\n"


def test_read_repl_line_passes_prompt_to_input(monkeypatch):
    """Non-TTY fallback: prompt must go through input() so backspace cannot erase ``>``."""
    seen: list[str] = []

    def fake_input(prompt: str = "") -> str:
        seen.append(prompt)
        return "hello"

    monkeypatch.setattr("localagent.ui.console.use_prompt_toolkit_repl", lambda: False)
    monkeypatch.setattr("builtins.input", fake_input)
    assert read_repl_line("> ") == "hello"
    assert seen == ["> "]


def test_read_repl_line_uses_prompt_toolkit_on_tty(monkeypatch):
    monkeypatch.setattr("localagent.ui.console.use_prompt_toolkit_repl", lambda: True)

    def fake_read(prompt: str = "> ") -> str:
        assert prompt == "> "
        return "中文"

    monkeypatch.setattr("localagent.ui.prompt_session.read_line_prompt_toolkit", fake_read)
    assert read_repl_line("> ") == "中文"


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


def test_render_welcome_shows_project_basics(monkeypatch):
    from localagent.i18n import reset_lang_cache

    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    info = WelcomeInfo(
        version=__version__,
        provider_line="qwen3.5:4b · auto(ollama→openrouter)",
        web_search_line="联网 · ddgs（免费）",
        cwd_display="~/code/LocalAgent",
        session_id="s-test123",
        layer_lines=(
            "Hot · 已配置 · 3偏好",
            "Warm · 12事实 · pending 1",
            "Cold · kb3 · 对话块12 · ChatGPT0",
            "Aware · 今日4",
            "la status 查看明细",
        ),
    )
    out = render_welcome(info, width=88, color=False)
    assert f"LocalAgent v{__version__}" in out
    assert "LOCAL" in out and "AGENT" in out
    assert "Local First. Memory Forever. Actions Automated." in out
    assert "qwen3.5:4b" in out
    assert "联网 · ddgs（免费）" in out
    assert "~/code/LocalAgent" in out
    assert "入门提示" in out
    assert "/status 查看数据层" in out
    assert "数据层" in out
    assert "Hot · 已配置" in out
    assert "Warm · 12事实" in out
    assert "Cold · kb3" in out
    assert "Aware · 今日4" in out
    assert "session s-test123" in out
    assert "/provider" in out
    assert "/model" in out
    assert "/help" in out
    assert "Tab" in out
    assert "╮" in out
    assert "│" in out


def test_format_web_search_hint_tavily_when_key_set(monkeypatch):
    from localagent.i18n import reset_lang_cache

    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "auto")
    monkeypatch.setattr("localagent.config.TAVILY_API_KEY", "tvly-x")
    monkeypatch.setattr("localagent.config.SEARXNG_URL", "")
    assert format_web_search_hint() == "联网 · Tavily"


def test_format_web_search_hint_ddgs_without_key(monkeypatch):
    from localagent.i18n import reset_lang_cache

    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "auto")
    monkeypatch.setattr("localagent.config.TAVILY_API_KEY", "")
    monkeypatch.setattr("localagent.config.SEARXNG_URL", "")
    assert format_web_search_hint() == "联网 · ddgs（免费）"


def test_collect_welcome_info_includes_web_search(monkeypatch, tmp_path: Path):
    from localagent.i18n import reset_lang_cache

    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "auto")
    monkeypatch.setattr("localagent.config.TAVILY_API_KEY", "tvly-x")
    monkeypatch.setattr("localagent.config.SEARXNG_URL", "")
    router = MagicMock()
    router.format_provider_hint.return_value = "auto(ollama)"
    router.format_model_hint.return_value = "qwen3.5:4b"
    with patch("localagent.models.router.get_model_router", return_value=router):
        with patch(
            "localagent.ui.banner._layer_lines",
            return_value=("Hot · 未配置", "la status 查看明细"),
        ):
            info = collect_welcome_info(provider="auto", session_id="s1", cwd=tmp_path)
    assert info.web_search_line == "联网 · Tavily"
    assert info.layer_lines[0].startswith("Hot")


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
    from localagent.i18n import reset_lang_cache

    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    inputs = iter([":q"])
    monkeypatch.setattr("localagent.chat_repl.read_repl_line", lambda _prompt="> ": next(inputs))
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
    assert "数据层" in out
    assert "s-welcome" in out


def test_activity_indicator_call_sites_have_two_args():
    """Guard against ActivityIndicator/spinner(message-only) regressions."""
    import ast

    root = Path(__file__).resolve().parents[1] / "src" / "localagent"
    bad: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name not in ("ActivityIndicator", "spinner"):
                continue
            pos = len(node.args)
            kw = {k.arg for k in node.keywords if k.arg}
            if pos >= 2:
                continue
            if pos == 0 and {"prefix", "message"} <= kw:
                continue
            if pos == 1 and "message" in kw:
                continue
            if pos == 1 and "prefix" in kw:
                continue
            rel = path.relative_to(root.parent.parent)
            bad.append(f"{rel}:{node.lineno} {name}(...)" )
    assert not bad, "ActivityIndicator/spinner need (prefix, message):\n" + "\n".join(bad)
