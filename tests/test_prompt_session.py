"""Tests for prompt_toolkit REPL input adapters."""

from __future__ import annotations

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from localagent.ui.prompt_session import (
    SessionSlashCompleter,
    _token_before_cursor,
    clear_history,
    get_repl_session,
)


def test_token_before_cursor_whitespace_delimited():
    assert _token_before_cursor("/prov") == ("/prov", 0)
    assert _token_before_cursor("/provider oll") == ("oll", 10)
    assert _token_before_cursor("/provider ") == ("", 10)
    assert _token_before_cursor("") == ("", 0)


def test_slash_completer_expands_command_prefix(monkeypatch):
    monkeypatch.setattr(
        "localagent.completion.suggest_session_slash_completions",
        lambda line, text="": ["/provider"] if text.startswith("/prov") else [],
    )
    completer = SessionSlashCompleter()
    hits = list(
        completer.get_completions(
            Document("/prov", cursor_position=5),
            CompleteEvent(),
        )
    )
    assert len(hits) == 1
    assert hits[0].text == "/provider"
    assert hits[0].start_position == -5


def test_slash_completer_provider_arg(monkeypatch):
    monkeypatch.setattr(
        "localagent.completion.suggest_session_slash_completions",
        lambda line, text="": ["ollama"] if text.startswith("oll") else [],
    )
    completer = SessionSlashCompleter()
    hits = list(
        completer.get_completions(
            Document("/provider oll", cursor_position=13),
            CompleteEvent(),
        )
    )
    assert [h.text for h in hits] == ["ollama"]
    assert hits[0].start_position == -3


def test_clear_history_resets_session_history():
    clear_history()
    session = get_repl_session()
    session.history.append_string("first")
    assert list(session.history.get_strings()) == ["first"]
    clear_history()
    assert list(get_repl_session().history.get_strings()) == []
