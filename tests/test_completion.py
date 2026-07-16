"""Tests for LA shell tab completion."""

from __future__ import annotations

from localagent.cli import build_parser, main
from localagent.completion import (
    install_repl_readline_completer,
    suggest_completions,
    suggest_session_slash_completions,
)
from localagent.session_commands import list_slash_command_names


def test_complete_subcommand_prefix_memory():
    hits = suggest_completions(["LA", "mem"], build_parser())
    assert "memory" in hits
    assert "approve" not in hits


def test_complete_all_subcommands_from_empty():
    hits = suggest_completions(["LA"], build_parser())
    assert "chat" in hits
    assert "memory" in hits
    assert "rag" in hits
    assert "reflect" in hits
    assert "websearch" in hits
    assert "tasks" in hits
    assert "add-file" not in hits
    assert "sync-file" not in hits


def test_complete_memory_actions():
    hits = suggest_completions(["LA", "memory", ""], build_parser())
    assert "add" in hits
    assert "ingest" in hits
    assert "query" in hits
    assert "search" in hits
    assert "reflect" in hits
    assert "pending" in hits
    assert "approve" in hits


def test_complete_rag_actions():
    hits = suggest_completions(["LA", "rag", ""], build_parser())
    assert "add" in hits
    assert "ingest" in hits
    assert "search" in hits
    assert "rebuild" in hits


def test_complete_memory_ingest_sources():
    hits = suggest_completions(["LA", "memory", "ingest", ""], build_parser())
    assert set(hits) == {"chat", "chatgpt", "all"}


def test_list_slash_command_names_excludes_chat():
    names = list_slash_command_names()
    assert "chat" not in names
    assert "help" in names
    assert "h" in names
    assert "provider" in names
    assert "model" in names
    assert "deepsearch" in names
    assert "websearch" in names
    assert "q" in names
    assert "memory" in names
    assert "rag" in names
    assert "mem" not in names
    # Shortcuts stay typeable but are not top-level Tab candidates
    assert "add" not in names
    assert "add-file" not in names
    assert "forget" not in names
    assert "search" not in names
    assert "reflect" in names


def test_session_slash_tab_lists_all_on_slash():
    hits = suggest_session_slash_completions("/", text="/")
    assert "/help" in hits
    assert "/memory" in hits
    assert "/rag" in hits
    assert "/reflect" in hits
    assert "/websearch" in hits
    assert "/provider" in hits
    assert "/model" in hits
    assert "/deepsearch" in hits
    assert "/q" in hits
    assert "/chat" not in hits
    assert "/add" not in hits
    assert "/add-file" not in hits
    assert "/forget" not in hits
    assert "/search" not in hits
    assert all(h.startswith("/") for h in hits)


def test_session_slash_tab_memory_rag_subcommands():
    mem = suggest_session_slash_completions("/memory ", text="")
    assert "add" in mem
    assert "forget" in mem
    assert "search" in mem
    assert "reflect" in mem
    assert "pending" in mem
    rag = suggest_session_slash_completions("/rag ", text="")
    assert "add" in rag


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
    # /m is not a model alias (ambiguous with memory)
    assert "/m" not in suggest_session_slash_completions("/m", text="/m")
    assert suggest_session_slash_completions("/mem", text="/mem") == ["/memory"]
    assert suggest_session_slash_completions("/memory", text="/memory") == ["/memory"]
    assert "/memories" not in suggest_session_slash_completions("/mem", text="/mem")


def test_install_repl_readline_completer():
    # Should not raise; returns False only when readline is unavailable.
    result = install_repl_readline_completer()
    assert result in (True, False)


def test_complete_audit_report_flag():
    hits = suggest_completions(["LA", "audit", "--rep"], build_parser())
    assert hits == ["--report"]
    assert "--report" in suggest_completions(["LA", "audit", "--"], build_parser())
    assert "--report" in suggest_completions(["LA", "audit", ""], build_parser())


def test_complete_workspace_and_logs_flags():
    assert "--days" in suggest_completions(["LA", "workspace", "--"], build_parser())
    assert "--level" in suggest_completions(["LA", "logs", "--"], build_parser())


def test_complete_config_actions_include_set_apply():
    hits = suggest_completions(["LA", "config", ""], build_parser())
    assert "set" in hits
    assert "apply" in hits
    assert "set-key" in hits
    assert suggest_completions(["LA", "config", "se"], build_parser()) == ["set", "set-key"]
    set_flags = suggest_completions(["LA", "config", "set", "--"], build_parser())
    assert "--provider" in set_flags
    assert "--model" in set_flags
    init_flags = suggest_completions(["LA", "config", "init", "--"], build_parser())
    assert "--force" in init_flags
    assert "--provider" not in init_flags


def test_complete_nested_memory_query_after_sort_value():
    hits = suggest_completions(["LA", "memory", "query", "--sort", "newest", "--"], build_parser())
    assert "--tag" in hits


def test_session_slash_tab_audit_report():
    assert suggest_session_slash_completions("/audit --rep", text="--rep") == ["--report"]
    # libedit may split on ``-`` so readline ``text`` is only the trailing fragment
    assert suggest_session_slash_completions("/audit --rep", text="rep") == ["report"]
    assert "--report" in suggest_session_slash_completions("/audit ", text="")
    assert "--report" in suggest_session_slash_completions("/audit --", text="--")


def test_session_slash_tab_config_nested():
    hits = suggest_session_slash_completions("/config ", text="")
    assert "set" in hits
    assert "apply" in hits
    assert "--provider" in suggest_session_slash_completions("/config set --", text="--")


def test_complete_chat_provider_flags():
    hits = suggest_completions(["LA", "chat", "--"], build_parser())
    assert "--provider" in hits
    assert "--session-id" in hits


def test_complete_chat_provider_values():
    hits = suggest_completions(["LA", "chat", "--provider", "oll"], build_parser())
    assert hits == ["ollama"]


def test_complete_memory_query_flags():
    hits = suggest_completions(["LA", "memory", "query", "-"], build_parser())
    assert "--sort" in hits
    assert "--tag" in hits
    assert "--list-tags" in hits


def test_complete_memory_query_sort_values():
    hits = suggest_completions(["LA", "memory", "query", "--sort", ""], build_parser())
    assert hits == ["newest", "oldest", "relevance"]
    assert suggest_completions(["LA", "memory", "query", "--sort", "re"], build_parser()) == [
        "relevance"
    ]


def test_complete_memory_query_tag_values(monkeypatch):
    monkeypatch.setattr(
        "localagent.completion._memory_tags",
        lambda limit=50: ["偏好", "家庭", "工作"],
    )
    hits = suggest_completions(["LA", "memory", "query", "--tag", ""], build_parser())
    assert hits == ["偏好", "家庭", "工作"]
    assert suggest_completions(["LA", "memory", "query", "--tag", "家"], build_parser()) == ["家庭"]


def test_session_slash_tab_memory_query_options():
    hits = suggest_session_slash_completions("/memory query ", text="")
    assert "--sort" in hits
    assert "--tag" in hits
    assert suggest_session_slash_completions("/memory query --sort ", text="") == [
        "newest",
        "oldest",
        "relevance",
    ]
    assert suggest_session_slash_completions("/memory query --sort re", text="re") == ["relevance"]


def test_complete_tasks_actions():
    hits = suggest_completions(["LA", "tasks", "pa"], build_parser())
    assert "pause" in hits


def test_complete_cli_entry():
    rc = main(["complete", "--", "LA", "mem"])
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


def test_venv_activate_hook_patches_activate(tmp_path, monkeypatch):
    from localagent.completion import _install_venv_activate_hook

    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    activate = venv / "bin" / "activate"
    activate.write_text("# fake activate\nVIRTUAL_ENV=...\nexport VIRTUAL_ENV\n", encoding="utf-8")
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    monkeypatch.setattr("localagent.completion.config.PROJECT_ROOT", tmp_path / "no-project")

    hooks = _install_venv_activate_hook()
    assert (venv / "activate.d" / "la-completion.zsh").is_file()
    assert (venv / "activate.d" / "la-completion.bash").is_file()
    assert activate in hooks
    text = activate.read_text(encoding="utf-8")
    assert "# >>> LA CLI completion >>>" in text
    assert 'activate.d/la-completion.zsh' in text

    # Idempotent
    hooks2 = _install_venv_activate_hook()
    assert activate in hooks2
    assert activate.read_text(encoding="utf-8") == text


def test_ensure_shell_completion_silent(tmp_path, monkeypatch, capsys):
    from localagent.completion import ensure_shell_completion

    monkeypatch.setattr("localagent.completion.Path.home", lambda: tmp_path)
    monkeypatch.setattr("localagent.completion._install_venv_activate_hook", lambda: [])

    ensure_shell_completion(shell="zsh")
    out = capsys.readouterr().out
    assert out == ""
    assert "compdef _la LA la" in (tmp_path / ".zshrc").read_text(encoding="utf-8")
