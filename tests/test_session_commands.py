"""Tests for session slash commands and shared CLI dispatch."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from localagent.agent.runtime import AgentResult
from localagent.chat_repl import ChatREPL
from localagent.memory.conversation_extract import ExtractedMemory
from localagent.persist.conversations import load_conversation
from localagent.session_commands import (
    SessionCommandContext,
    dispatch_cli_argv,
    dispatch_session_line,
    is_meta_user_content,
    is_session_command,
    normalize_session_argv,
)


def test_is_session_command_slash_and_colon():
    assert is_session_command("/help")
    assert is_session_command(":provider ollama")
    assert is_session_command("  /search foo")
    assert not is_session_command("search foo")
    assert not is_session_command("你好")


def test_normalize_session_argv_aliases_and_quotes():
    assert normalize_session_argv('/add "hello world"') == ["ingest", "text", "hello world"]
    assert normalize_session_argv(":p ollama") == ["provider", "ollama"]
    assert normalize_session_argv("/q") == ["q"]
    assert normalize_session_argv("/h") == ["help"]
    assert normalize_session_argv("/model qwen3.5:4b") == ["model", "qwen3.5:4b"]
    assert normalize_session_argv("/memory query foo") == ["memory", "query", "foo"]
    assert normalize_session_argv('/reflect "我最近状态怎么样?"') == [
        "memory",
        "reflect",
        "我最近状态怎么样?",
    ]
    assert normalize_session_argv('/websearch "今天深圳天气"') == [
        "websearch",
        "今天深圳天气",
    ]
    assert normalize_session_argv("/deepsearch 主题 A") == ["deepsearch", "主题", "A"]


def test_is_meta_user_content():
    assert is_meta_user_content("/deepsearch foo")
    assert is_meta_user_content(":provider ollama")
    assert not is_meta_user_content("普通对话")


def test_dispatch_rejects_chat_in_session(capsys):
    rc = dispatch_cli_argv(["chat"], allow_chat=False)
    assert rc == 1
    assert "无需 /chat" in capsys.readouterr().out


def test_dispatch_session_unknown_goes_to_argparse(capsys):
    ctx = SessionCommandContext(session_id="s-x", provider="auto")
    result = dispatch_session_line("/definitely-not-a-command", ctx)
    assert result.handled
    assert result.exit_code != 0
    out = capsys.readouterr().out + capsys.readouterr().err
    # argparse writes to stderr typically
    assert result.exit_code == 2 or "error" in out.lower() or "invalid" in out.lower() or out != ""


def test_dispatch_session_help(capsys):
    ctx = SessionCommandContext(session_id="s-help", provider="auto")
    result = dispatch_session_line("/help", ctx)
    assert result.exit_code == 0
    out = capsys.readouterr().out
    assert "add" in out
    assert "memory" in out
    assert "/provider" in out
    assert "/model" in out
    assert "/memory" in out
    assert "无参显示 status" in out
    assert "/rag" in out
    assert "/mem" not in out.replace("/memory", "")
    assert "/memories" not in out
    assert "/deepsearch" in out
    assert "/websearch" in out
    assert "/m [" not in out and "/model, /m" not in out


def test_dispatch_session_bare_memory_and_rag(capsys):
    ctx = SessionCommandContext(session_id="s-bare", provider="auto")
    mem = dispatch_session_line("/memory", ctx)
    assert mem.exit_code == 0
    out = capsys.readouterr().out
    assert "[memory status]" in out
    assert "来源分布" in out

    rag = dispatch_session_line("/rag", ctx)
    assert rag.exit_code == 0
    out = capsys.readouterr().out
    assert "[rag status]" in out
    assert "kb 目录" in out


def test_dispatch_session_model_list_and_set(monkeypatch, capsys, tmp_path):
    from localagent import env_config
    from localagent.models.router import ModelRouter
    from localagent.session_commands import reset_model_browse

    reset_model_browse()
    yaml_path = tmp_path / "model_servers.yaml"
    calls: list[tuple[str, str]] = []

    def fake_set(provider: str, model: str, *, env_path=None):
        calls.append((provider, model))
        return yaml_path, True

    monkeypatch.setattr(env_config, "set_server_model", fake_set)

    router = ModelRouter()
    monkeypatch.setattr("localagent.models.router.get_model_router", lambda: router)
    monkeypatch.setattr(router, "resolve_effective_provider", lambda choice: "ollama")
    monkeypatch.setattr(router, "format_model_hint", lambda provider: "qwen3.5:4b")
    monkeypatch.setattr(
        router,
        "list_provider_models",
        lambda provider: ["qwen3.5:4b", "llama3.2:3b"],
    )
    monkeypatch.setattr(router, "clear_model_cache", lambda: None)

    ctx = SessionCommandContext(session_id="s-model", provider="ollama")
    listed = dispatch_session_line("/model", ctx)
    assert listed.exit_code == 0
    out = capsys.readouterr().out
    assert "第 1/1 页" in out
    assert "qwen3.5:4b" in out
    assert "llama3.2:3b" in out

    set_by_name = dispatch_session_line("/model llama3.2:3b", ctx)
    assert set_by_name.exit_code == 0
    assert calls[-1] == ("ollama", "llama3.2:3b")

    set_by_index = dispatch_session_line("/model 1", ctx)
    assert set_by_index.exit_code == 0
    assert calls[-1] == ("ollama", "qwen3.5:4b")
    assert "已写入" in capsys.readouterr().out


def test_dispatch_session_model_pagination(monkeypatch, capsys):
    from localagent.models.router import ModelRouter
    from localagent.session_commands import reset_model_browse

    reset_model_browse()
    models = [f"model-{i:02d}" for i in range(1, 26)]  # 25 → 3 pages of 10
    router = ModelRouter()
    monkeypatch.setattr("localagent.models.router.get_model_router", lambda: router)
    monkeypatch.setattr(router, "resolve_effective_provider", lambda choice: "openrouter")
    monkeypatch.setattr(router, "format_model_hint", lambda provider: "model-01")
    monkeypatch.setattr(router, "list_provider_models", lambda provider: models)
    monkeypatch.setattr(router, "clear_model_cache", lambda: None)

    ctx = SessionCommandContext(session_id="s-page", provider="openrouter")
    assert dispatch_session_line("/model", ctx).exit_code == 0
    out = capsys.readouterr().out
    assert "第 1/3 页" in out
    assert "model-01" in out
    assert "model-10" in out
    assert "model-11" not in out
    assert "/model next|prev|page N" in out

    assert dispatch_session_line("/model next", ctx).exit_code == 0
    out = capsys.readouterr().out
    assert "第 2/3 页" in out
    assert "model-11" in out
    assert "model-20" in out

    assert dispatch_session_line("/model page 3", ctx).exit_code == 0
    out = capsys.readouterr().out
    assert "第 3/3 页" in out
    assert "model-21" in out
    assert "model-25" in out

    assert dispatch_session_line("/model prev", ctx).exit_code == 0
    assert "第 2/3 页" in capsys.readouterr().out

    from localagent import env_config

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        env_config,
        "set_server_model",
        lambda provider, model, *, env_path=None: (calls.append((provider, model)) or ("/tmp/x", True)),
    )
    # Page 2 local index 1 → model-11
    assert dispatch_session_line("/model 1", ctx).exit_code == 0
    assert calls[-1] == ("openrouter", "model-11")


def test_dispatch_session_rejects_ambiguous_m(capsys):
    ctx = SessionCommandContext(session_id="s-m", provider="ollama")
    result = dispatch_session_line("/m b", ctx)
    assert result.exit_code == 1
    out = capsys.readouterr().out
    assert "/m 已弃用" in out
    assert "/model" in out
    assert "/memory query" in out
    assert "/mem" not in out.replace("/memory", "")


def test_dispatch_session_websearch(monkeypatch, capsys):
    ctx = SessionCommandContext(session_id="s-web", provider="auto")
    with patch("localagent.cli.web_search", return_value="摘要: 最新 AI 进展\n- [匹配] news.example") as search:
        result = dispatch_session_line('/websearch "最新 AI 进展"', ctx)
    assert result.exit_code == 0
    search.assert_called_once()
    out = capsys.readouterr().out
    assert "websearch" in out
    assert "最新 AI 进展" in out


def test_dispatch_session_exit():
    ctx = SessionCommandContext(session_id="s-exit", provider="auto")
    assert dispatch_session_line("/q", ctx).should_exit
    assert dispatch_session_line(":quit", ctx).should_exit
    assert dispatch_session_line("/exit", ctx).should_exit


def test_chat_slash_search_does_not_call_agent(monkeypatch, isolated_data, capsys):
    inputs = iter(['/search "不存在的查询词xyz"', "/q"])
    monkeypatch.setattr("localagent.chat_repl.read_repl_line", lambda _p="> ": next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    with patch("localagent.chat_repl.run_agent_turn") as mock_turn:
        ChatREPL(session_id="s-slash-search").run()

    mock_turn.assert_not_called()
    out = capsys.readouterr().out
    # search command prints something even when empty
    assert "search" in out.lower() or "记忆" in out or "相关" in out or "找到" in out or "未" in out


def test_chat_slash_add_does_not_call_agent(monkeypatch, isolated_data):
    inputs = iter(['/add "slash 写入一条测试记忆"', "/q"])
    monkeypatch.setattr("localagent.chat_repl.read_repl_line", lambda _p="> ": next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    from localagent.memory.store import get_memory_store

    before = get_memory_store().count()
    with patch("localagent.chat_repl.run_agent_turn") as mock_turn:
        ChatREPL(session_id="s-slash-add").run()

    mock_turn.assert_not_called()
    assert get_memory_store().count() == before + 1
    texts = [f.text for f in get_memory_store().all_facts()]
    assert any("slash 写入一条测试记忆" in t for t in texts)


def test_chat_slash_provider_and_quit(monkeypatch):
    inputs = iter(["/provider ollama", "你好", "/q"])
    monkeypatch.setattr("localagent.chat_repl.read_repl_line", lambda _p="> ": next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    with patch("localagent.chat_repl.run_agent_turn") as mock_turn:
        mock_turn.return_value = AgentResult(response="ok")
        ChatREPL(session_id="s-slash-provider").run()

    mock_turn.assert_called_once()
    assert mock_turn.call_args.kwargs["provider"] == "ollama"


def test_chat_slash_deepsearch(monkeypatch):
    inputs = iter(["/deepsearch Hindsight", "/q"])
    monkeypatch.setattr("localagent.chat_repl.read_repl_line", lambda _p="> ": next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    with patch("localagent.tools.deep_search", return_value="深度研究报告"):
        ChatREPL(session_id="s-slash-deep").run()

    messages = load_conversation("s-slash-deep")
    assert len(messages) == 2
    assert messages[0]["content"].startswith("/deepsearch")
    assert messages[1].get("tool") == "deepsearch"


def test_chat_colon_deepsearch_still_works(monkeypatch):
    """Legacy :deepsearch remains a compatible alias."""
    inputs = iter([":deepsearch Hindsight 记忆引擎", ":q"])
    monkeypatch.setattr("localagent.chat_repl.read_repl_line", lambda _p="> ": next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    with patch("localagent.tools.deep_search", return_value="深度研究报告"):
        ChatREPL(session_id="s-deep-colon").run()

    messages = load_conversation("s-deep-colon")
    assert len(messages) == 2
    assert "deepsearch" in messages[0]["content"]
    assert messages[1].get("tool") == "deepsearch"


def test_extract_skips_slash_commands(isolated_data):
    from localagent.memory.exit_extract import extract_session_memories
    from localagent.persist.conversations import append_message

    isolated_data["router"].extract_memories.return_value = [
        ExtractedMemory(text="不应提取"),
    ]
    session_id = "s-slash-cmd-only"
    append_message(session_id, "user", "/deepsearch foo")
    append_message(session_id, "assistant", "report")
    assert extract_session_memories(session_id, interactive=False) == []


def test_outer_cli_still_dispatches_add(isolated_data, capsys):
    with patch("localagent.cli.get_task_store") as mock_store:
        mock_store.return_value.reconcile_stale = MagicMock()
        with patch("localagent.env_config.ensure_config"):
            from localagent.cli import main

            rc = main(["ingest", "text", "outer channel memory"])
    assert rc == 0
