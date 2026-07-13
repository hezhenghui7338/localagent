"""Tests for silent background memory extraction during chat."""

from __future__ import annotations

from unittest.mock import patch

from localagent.agent.intent_clarification import IntentAssessment
from localagent.agent.runtime import AgentResult
from localagent.chat_repl import ChatREPL
from localagent.memory.exit_extract import extract_session_memories, schedule_session_memory_extract
from localagent.memory.store import get_memory_store
from localagent.persist.conversations import append_message, load_conversation


def test_chat_shows_response_provider(capsys, monkeypatch):
    inputs = iter(["你好", ":q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    with patch("localagent.chat_repl.run_agent_turn") as mock_turn:
        mock_turn.return_value = AgentResult(response="你好，我是 LocalAgent")
        with patch("localagent.chat_repl.get_model_router") as mock_get_router:
            router = mock_get_router.return_value
            router.format_last_source.return_value = "openrouter/anthropic/claude-sonnet-4"
            router._ollama_slow = False
            ChatREPL(session_id="s-via").run()

    output = capsys.readouterr().out
    assert "[via openrouter/anthropic/claude-sonnet-4]" in output


def test_chat_shows_error_for_empty_response(capsys, monkeypatch):
    inputs = iter(["你好", ":q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    with patch("localagent.chat_repl.run_agent_turn") as mock_turn:
        mock_turn.return_value = AgentResult(response="   ")
        with patch("localagent.chat_repl.get_model_router") as mock_get_router:
            router = mock_get_router.return_value
            router.format_last_source.return_value = "ollama/qwen3.5:4b"
            router._ollama_slow = False
            ChatREPL(session_id="s-empty-resp").run()

    output = capsys.readouterr().out
    assert "模型返回了空内容" in output
    assert "[via ollama/qwen3.5:4b]" in output


def test_chat_persists_conversation_to_jsonl(monkeypatch):
    """PRD §4: chat 对话持久化到 data/conversations/*.jsonl."""
    inputs = iter(["你好", ":q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    with patch("localagent.chat_repl.run_agent_turn") as mock_turn:
        mock_turn.return_value = AgentResult(response="你好，我是 LocalAgent")
        repl = ChatREPL(session_id="s-persist")
        repl.run()

    messages = load_conversation("s-persist")
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "你好"
    assert messages[1]["role"] == "assistant"
    assert "LocalAgent" in messages[1]["content"]


def test_chat_exit_schedules_background_extract(isolated_data, monkeypatch):
    """对话退出时在后台提取记忆，不阻塞 REPL."""
    isolated_data["router"].extract_facts.return_value = [
        "2026年7月决定使用 Hindsight 作为记忆引擎",
    ]

    inputs = iter(["我决定用 Hindsight", ":q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    def sync_extract(session_id: str) -> None:
        extract_session_memories(session_id, interactive=False)

    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        sync_extract,
    )

    before = get_memory_store().count()
    with patch("localagent.chat_repl.run_agent_turn") as mock_turn:
        mock_turn.return_value = AgentResult(response="好的，了解了")
        ChatREPL(session_id="s-extract").run()

    assert get_memory_store().count() == before + 1


def test_chat_exit_extract_runs_in_background(monkeypatch):
    """退出时不等待记忆提取完成."""
    inputs = iter([":q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    scheduled: list[str] = []

    def capture(session_id: str) -> None:
        scheduled.append(session_id)

    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        capture,
    )

    ChatREPL(session_id="s-bg").run()
    assert scheduled == ["s-bg"]


def test_chat_skips_extraction_for_empty_session(monkeypatch):
    inputs = iter([":q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))

    before = get_memory_store().count()
    ChatREPL(session_id="s-empty").run()
    assert get_memory_store().count() == before


def test_chat_deepsearch_persisted(monkeypatch):
    inputs = iter([":deepsearch Hindsight 记忆引擎", ":q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    with patch("localagent.tools.deep_search", return_value="深度研究报告"):
        ChatREPL(session_id="s-deep").run()

    messages = load_conversation("s-deep")
    assert len(messages) == 2
    assert "deepsearch" in messages[0]["content"]
    assert messages[1].get("tool") == "deepsearch"
    assert "深度研究报告" in messages[1]["content"]


def test_chat_slash_help_and_quit(monkeypatch, capsys):
    inputs = iter(["/help", "/q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    with patch("localagent.chat_repl.run_agent_turn") as mock_turn:
        ChatREPL(session_id="s-help-quit").run()

    mock_turn.assert_not_called()
    out = capsys.readouterr().out
    assert "/provider" in out
    assert "/model" in out
    assert "add" in out


def test_chat_provider_switch_passes_to_agent(monkeypatch):
    inputs = iter([":provider ollama", "你好", ":q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    with patch("localagent.chat_repl.run_agent_turn") as mock_turn:
        mock_turn.return_value = AgentResult(response="ok")
        ChatREPL(session_id="s-provider").run()

    mock_turn.assert_called_once()
    assert mock_turn.call_args.kwargs["provider"] == "ollama"


def test_chat_single_ctrl_c_does_not_exit(monkeypatch):
    """First Ctrl+C at prompt cancels input; REPL stays alive."""
    inputs = iter(["hello", ":q"])
    calls = {"n": 0}

    def fake_input(_prompt: str) -> str:
        if calls["n"] == 0:
            calls["n"] += 1
            raise KeyboardInterrupt
        return next(inputs)

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    with patch("localagent.chat_repl.run_agent_turn") as mock_turn:
        mock_turn.return_value = AgentResult(response="ok")
        rc = ChatREPL(session_id="s-ctrlc").run()

    assert rc == 0
    messages = load_conversation("s-ctrlc")
    assert len(messages) == 2
    assert messages[0]["content"] == "hello"


def test_chat_ctrl_c_during_inference_keeps_repl(monkeypatch):
    inputs = iter(["hello", ":q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    with patch("localagent.chat_repl.run_agent_turn") as mock_turn:
        mock_turn.side_effect = KeyboardInterrupt
        ChatREPL(session_id="s-cancel").run()

    messages = load_conversation("s-cancel")
    assert messages == []


def test_chat_clarification_flow_before_agent(monkeypatch):
    """模糊请求先追问，补充后再调用 run_agent_turn。"""
    inputs = iter(["帮我改一下", "改 runtime.py 里的重复代码", ":q"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(
        "localagent.chat_repl.schedule_session_memory_extract",
        lambda _session_id: None,
    )

    assessment = IntentAssessment(
        mode="clarify",
        questions=["你想修改哪个文件？", "是要重构还是修 bug？"],
    )
    with patch("localagent.chat_repl.assess_intent", return_value=assessment):
        with patch("localagent.chat_repl.run_agent_turn") as mock_turn:
            mock_turn.return_value = AgentResult(response="已重构 runtime.py")
            ChatREPL(session_id="s-clarify").run()

    assert mock_turn.call_count == 1
    merged_input = mock_turn.call_args.args[0]
    assert "帮我改一下" in merged_input
    assert "runtime.py" in merged_input

    messages = load_conversation("s-clarify")
    assert len(messages) == 4
    assert messages[0]["content"] == "帮我改一下"
    assert "确认你的意图" in messages[1]["content"]
    assert messages[2]["content"] == "改 runtime.py 里的重复代码"
    assert "runtime.py" in messages[3]["content"]
