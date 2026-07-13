"""Tests for LA shell tab completion."""

from __future__ import annotations

from localagent.cli import build_parser, main
from localagent.completion import (
    install_repl_readline_completer,
    suggest_completions,
    suggest_session_slash_completions,
)
from localagent.session_commands import list_slash_command_names


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


def test_list_slash_command_names_excludes_chat():
    names = list_slash_command_names()
    assert "chat" not in names
    assert "help" in names
    assert "h" in names
    assert "provider" in names
    assert "model" in names
    assert "deepsearch" in names
    assert "q" in names
    assert "add" in names
    assert "add-file" in names
    assert "search" in names


def test_session_slash_tab_lists_all_on_slash():
    hits = suggest_session_slash_completions("/", text="/")
    assert "/help" in hits
    assert "/add" in hits
    assert "/provider" in hits
    assert "/model" in hits
    assert "/deepsearch" in hits
    assert "/q" in hits
    assert "/chat" not in hits
    assert all(h.startswith("/") for h in hits)


def test_session_slash_tab_prefix_filter():
    hits = suggest_session_slash_completions("/he", text="/he")
    assert hits == ["/help"]


def test_session_slash_tab_colon_prefix():
    hits = suggest_session_slash_completions(":", text=":")
    assert ":help" in hits
    assert ":provider" in hits
    assert all(h.startswith(":") for h in hits)


def test_session_slash_tab_ignores_plain_chat():
    assert suggest_session_slash_completions("你好", text="你好") == []


def test_session_slash_tab_provider_values_after_space():
    hits = suggest_session_slash_completions("/provider ", text="")
    assert "auto" in hits
    assert "ollama" in hits
    assert all(not h.startswith("/") for h in hits)

    assert suggest_session_slash_completions("/provider oll", text="oll") == ["ollama"]
    assert "auto" in suggest_session_slash_completions("/p ", text="")


def test_session_slash_tab_provider_expands_on_exact_command():
    hits = suggest_session_slash_completions("/provider", text="/provider")
    assert any(h.startswith("/provider ") for h in hits)
    assert any(h.endswith(" ollama") for h in hits)
    assert any(h.endswith(" auto") for h in hits)


def test_session_slash_tab_model_values(monkeypatch):
    from localagent.session_commands import set_repl_provider

    set_repl_provider("ollama")
    monkeypatch.setattr(
        "localagent.completion._session_model_choices",
        lambda: ["qwen3.5:4b", "llama3.2:3b", "anthropic/claude-sonnet-4"],
    )
    # Bare Tab must not dump the full catalog.
    assert suggest_session_slash_completions("/model ", text="") == []
    assert suggest_session_slash_completions("/model lla", text="lla") == ["llama3.2:3b"]
    assert suggest_session_slash_completions("/model claude", text="claude") == [
        "anthropic/claude-sonnet-4"
    ]
    assert suggest_session_slash_completions("/model", text="/model") == ["/model"]
    # /m is not a model alias (ambiguous with memories)
    assert "/m" not in suggest_session_slash_completions("/m", text="/m")
    hits_mem = suggest_session_slash_completions("/mem", text="/mem")
    assert "/mem" in hits_mem or "/memories" in hits_mem


def test_install_repl_readline_completer():
    # Should not raise; returns False only when readline is unavailable.
    result = install_repl_readline_completer()
    assert result in (True, False)


def test_complete_chat_provider_flags():
    hits = suggest_completions(["LA", "chat", "--"], build_parser())
    assert "--provider" in hits
    assert "--session-id" in hits


def test_complete_chat_provider_values():
    hits = suggest_completions(["LA", "chat", "--provider", "oll"], build_parser())
    assert hits == ["ollama"]


def test_complete_memories_flags():
    hits = suggest_completions(["LA", "memories", "-"], build_parser())
    assert "--sort" in hits
    assert "--tag" in hits
    assert "--list-tags" in hits


def test_complete_memories_sort_values():
    hits = suggest_completions(["LA", "memories", "--sort", ""], build_parser())
    assert hits == ["newest", "oldest", "relevance"]
    assert suggest_completions(["LA", "memories", "--sort", "re"], build_parser()) == [
        "relevance"
    ]


def test_complete_memories_tag_values(monkeypatch):
    monkeypatch.setattr(
        "localagent.completion._memory_tags",
        lambda limit=50: ["偏好", "家庭", "工作"],
    )
    hits = suggest_completions(["LA", "memories", "--tag", ""], build_parser())
    assert hits == ["偏好", "家庭", "工作"]
    assert suggest_completions(["LA", "memories", "--tag", "家"], build_parser()) == ["家庭"]


def test_session_slash_tab_memories_options():
    hits = suggest_session_slash_completions("/memories ", text="")
    assert "--sort" in hits
    assert "--tag" in hits
    assert suggest_session_slash_completions("/memories --sort ", text="") == [
        "newest",
        "oldest",
        "relevance",
    ]
    assert suggest_session_slash_completions("/mem --sort re", text="re") == ["relevance"]


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
