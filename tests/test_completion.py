"""Tests for LA shell tab completion."""

from __future__ import annotations

from localagent.cli import build_parser, main
from localagent.completion import suggest_completions


def test_complete_subcommand_prefix_add():
    hits = suggest_completions(["LA", "add"], build_parser())
    assert "add" in hits
    assert "add-file" in hits
    assert "approve" not in hits


def test_complete_all_subcommands_from_empty():
    hits = suggest_completions(["LA"], build_parser())
    assert "chat" in hits
    assert "add-file" in hits
    assert "sync-file" in hits


def test_complete_chat_provider_flags():
    hits = suggest_completions(["LA", "chat", "--"], build_parser())
    assert "--provider" in hits
    assert "--session-id" in hits


def test_complete_chat_provider_values():
    hits = suggest_completions(["LA", "chat", "--provider", "oll"], build_parser())
    assert hits == ["ollama"]


def test_complete_tasks_actions():
    hits = suggest_completions(["LA", "tasks", "pa"], build_parser())
    assert "pause" in hits


def test_complete_cli_entry():
    rc = main(["complete", "--", "LA", "add"])
    assert rc == 0


def test_complete_install_zsh(capsys):
    rc = main(["complete-install", "zsh"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "compdef _la LA la" in out
    assert "compinit -C" in out
    assert "autoload -Uz compinit" in out


def test_complete_init_writes_zshrc(tmp_path, monkeypatch):
    zshrc = tmp_path / ".zshrc"
    monkeypatch.setattr("localagent.completion.Path.home", lambda: tmp_path)
    monkeypatch.setattr("localagent.completion._install_venv_activate_hook", lambda: [])

    rc = main(["complete-init", "zsh"])
    assert rc == 0
    text = zshrc.read_text(encoding="utf-8")
    assert "# >>> LA CLI completion >>>" in text
    assert "compdef _la LA la" in text
