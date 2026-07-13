"""Shell tab-completion for the LA CLI."""

from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

from localagent import config

_FILE_SENTINEL = "__LA_FILE__"
_TASK_ACTIONS = ("delete", "pause", "resume", "restart", "logs", "list", "show")
_CHAT_PROVIDERS = ("auto",) + config.VALID_PROVIDERS
_ZSHRC_START = "# >>> LA CLI completion >>>"
_ZSHRC_END = "# <<< LA CLI completion <<<"


def _prefix_match(candidates: list[str], prefix: str) -> list[str]:
    if not prefix:
        return candidates
    return [c for c in candidates if c.startswith(prefix)]


def _get_subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def subparser_names(parser: argparse.ArgumentParser | None = None) -> list[str]:
    """Return sorted top-level CLI subcommand names."""
    if parser is None:
        from localagent.cli import build_parser

        parser = build_parser()
    return sorted(_get_subparsers(parser))


def _option_strings(parser: argparse.ArgumentParser) -> list[str]:
    flags: list[str] = []
    for action in parser._actions:
        flags.extend(action.option_strings)
    return sorted(set(flags))


def _task_ids(limit: int = 30) -> list[str]:
    try:
        from localagent.ingest.tasks import get_task_store

        tasks = get_task_store().list_tasks(limit=limit, reconcile=False)
        return [t.id for t in tasks]
    except Exception:
        return []


def _session_ids(limit: int = 30) -> list[str]:
    try:
        conv_dir = config.CONVERSATIONS_DIR
        if not conv_dir.is_dir():
            return []
        paths = sorted(conv_dir.glob("s-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.stem for p in paths[:limit]]
    except OSError:
        return []


def _memory_ids(limit: int = 30) -> list[str]:
    try:
        from localagent.memory.store import get_memory_store
        from localagent.memory.temporal import memory_effective_time

        facts = get_memory_store().all_facts()
        facts.sort(
            key=lambda fact: memory_effective_time(metadata=fact.metadata, created_at=fact.created_at),
            reverse=True,
        )
        return [fact.id for fact in facts[:limit]]
    except Exception:
        return []


def _memory_tags(limit: int = 50) -> list[str]:
    try:
        from localagent.memory.query import list_memory_tags

        return [tag for tag, _count in list_memory_tags(limit=limit)]
    except Exception:
        return []


def _expand_path(prefix: str) -> list[str]:
    if not prefix:
        return [_FILE_SENTINEL]
    expanded = os.path.expanduser(prefix)
    matches = glob.glob(expanded + "*")
    if not matches:
        return [_FILE_SENTINEL]
    out: list[str] = []
    for match in sorted(matches):
        if os.path.isdir(match):
            out.append(match + os.sep)
        else:
            out.append(match)
    return out or [_FILE_SENTINEL]


def _find_option_action(
    parser: argparse.ArgumentParser, flag: str
) -> argparse.Action | None:
    for action in parser._actions:
        if flag in action.option_strings:
            return action
    return None


def _completing_option(args: list[str], current: str, parser: argparse.ArgumentParser) -> list[str]:
    flags = _option_strings(parser)
    if current.startswith("-"):
        return _prefix_match(flags, current)

    if not args:
        return _prefix_match(flags, current)

    prev = args[-1]
    if not prev.startswith("-"):
        return _prefix_match(flags, current)

    if prev in ("--provider", "-p"):
        return _prefix_match(list(_CHAT_PROVIDERS), current)
    if prev in ("--session-id", "--session"):
        return _prefix_match(_session_ids(), current)
    if prev == "--tag":
        return _prefix_match(_memory_tags(), current)

    action = _find_option_action(parser, prev)
    if action is not None:
        if action.choices is not None:
            return _prefix_match([str(c) for c in action.choices], current)
        if isinstance(
            action,
            (argparse._StoreTrueAction, argparse._StoreFalseAction, argparse._HelpAction),
        ):
            return _prefix_match(flags, current)
        # Value-taking flag without fixed choices (--since, --limit, …)
        return []

    return _prefix_match(flags, current)


def suggest_completions(words: list[str], parser: argparse.ArgumentParser | None = None) -> list[str]:
    """Return completion candidates for a partial LA command line."""
    if parser is None:
        from localagent.cli import build_parser

        parser = build_parser()

    if not words:
        return sorted(_get_subparsers(parser))

    subparsers = _get_subparsers(parser)
    commands = sorted(subparsers)

    if len(words) == 1:
        return commands

    current = words[-1]
    context = words[:-1]
    args = context[1:] if len(context) > 1 else []

    if not args:
        return _prefix_match(commands, current)

    cmd = args[0]
    tail = args[1:]

    if cmd not in subparsers:
        return _prefix_match(commands, current)

    sub = subparsers[cmd]

    if current.startswith("-") or (tail and tail[-1].startswith("-")):
        return _completing_option(tail, current, sub)

    if cmd == "tasks":
        if not tail:
            actions = list(_TASK_ACTIONS) + _task_ids()
            return _prefix_match(actions, current)
        if tail[0] in _TASK_ACTIONS and len(tail) == 1:
            return _prefix_match(_task_ids(), current)
        if tail[0].startswith("t-"):
            return []
        return _prefix_match(list(_TASK_ACTIONS) + _task_ids(), current)

    if cmd == "add-file":
        return _expand_path(current)

    if cmd == "import-chatgpt":
        if current.startswith("-"):
            return _completing_option(tail, current, sub)
        if not tail or tail[-1] in ("--file", "--dir"):
            return _expand_path(current)
        if tail[-1].startswith("--"):
            return _completing_option(tail, current, sub)
        return _expand_path(current)

    if cmd == "forget" and not tail:
        return _memory_ids()

    if cmd == "chat" and not tail:
        return _completing_option([], current, sub)

    if cmd == "search" and not tail:
        return _completing_option([], current, sub)

    if cmd in ("rememorize-chat", "sync-file", "reset-memory", "rebuild-memory"):
        return _completing_option(tail, current, sub)

    if cmd == "config":
        if not tail:
            return _prefix_match(["init", "list", "add", "remove", "set-key"], current)
        if tail[0] == "remove" and len(tail) == 1:
            return []
        if tail[0] == "set-key" and len(tail) == 1:
            return []
        if tail[0] == "add" and len(tail) == 1:
            return []

    return _completing_option(tail, current, sub)


def run_complete(argv: list[str]) -> int:
    """Entry for ``LA complete -- WORDS...``."""
    if not argv or argv[0] != "--":
        return 1
    words = argv[1:]
    for item in suggest_completions(words):
        print(item)
    return 0


def _session_provider_choices() -> list[str]:
    """``auto`` plus providers from the loaded model-servers config."""
    return ["auto", *config.VALID_PROVIDERS]


def _session_model_choices() -> list[str]:
    """Model IDs for the current REPL provider (best-effort; empty on failure)."""
    from localagent.models.router import get_model_router
    from localagent.session_commands import get_repl_provider

    router = get_model_router()
    provider = router.resolve_effective_provider(get_repl_provider())
    try:
        return router.list_provider_models(provider)
    except Exception:
        return []


def _filter_prefix(candidates: list[str], text: str) -> list[str]:
    if not text:
        return candidates
    return [c for c in candidates if c.startswith(text)]


def _session_arg_completions(cmd: str, argv: list[str], text: str) -> list[str]:
    """Complete arguments after a session slash command name.

    ``argv`` is tokens after the command name (may include the current word).
    ``text`` is the readline current word being completed.
    """
    if cmd == "provider":
        needle = text.lower()
        return [c for c in _session_provider_choices() if c.startswith(needle)]
    if cmd == "model":
        # Avoid dumping hundreds of models on bare Tab (readline "Display all N?").
        # Require a filter prefix; then match by prefix or substring.
        needle = text.strip()
        if not needle:
            return []
        models = _session_model_choices()
        exact = [m for m in models if m.startswith(needle)]
        if exact:
            return exact[:50]
        return [m for m in models if needle.lower() in m.lower()][:50]

    # Reuse outer CLI completion for subcommands exposed as slash commands
    # (e.g. ``/memories --sort`` → newest|oldest|relevance).
    from localagent.cli import build_parser

    parser = build_parser()
    if cmd not in _get_subparsers(parser):
        return []

    completed = list(argv)
    if text and completed and completed[-1] == text:
        completed = completed[:-1]
    return suggest_completions(["LA", cmd, *completed, text], parser)


def suggest_session_slash_completions(line: str, text: str = "") -> list[str]:
    """Tab-completion candidates for a chat REPL line starting with ``/`` or ``:``.

    Completes command names, and for ``/provider`` / ``/p`` also completes
    configured provider paths (``auto``, ``ollama``, ``cursor``, …). For
    ``/model`` completes models only when a filter prefix is typed. For CLI
    subcommands like ``/memories``, reuses shell option/value completion.
    """
    stripped = line.lstrip()
    if not stripped or stripped[0] not in ("/", ":"):
        return []

    prefix = stripped[0]
    rest = stripped[1:]

    from localagent.session_commands import list_slash_command_names

    # Past the command name → complete args (readline ``text`` is the current word)
    if rest and any(ch.isspace() for ch in rest):
        parts = rest.split()
        if not parts:
            return []
        cmd = parts[0].lower()
        if cmd in ("p", "provider"):
            cmd = "provider"
        elif cmd == "model":
            cmd = "model"
        elif cmd in ("mem", "memories"):
            cmd = "memories"
        return _session_arg_completions(cmd, parts[1:], text)

    needle = rest.lower()
    hits = [name for name in list_slash_command_names() if name.startswith(needle)]

    # Fully typed ``/provider`` or ``/p``: offer ``/provider ollama`` style so Tab
    # can insert a space and list configured providers.
    if needle in ("provider", "p") and needle in hits:
        canonical = "provider" if needle == "provider" else needle
        expanded = [f"{prefix}{canonical} {c}" for c in _session_provider_choices()]
        return _filter_prefix(expanded, text)

    # Do not expand ``/model`` into hundreds of ``/model <id>`` candidates.
    if needle == "model" and needle in hits:
        return _filter_prefix([f"{prefix}{needle}"], text)

    candidates = [f"{prefix}{name}" for name in hits]
    return _filter_prefix(candidates, text)


def install_repl_readline_completer() -> bool:
    """Install readline Tab completion for session slash commands. Returns True if installed."""
    try:
        import readline
    except ImportError:
        return False

    # Keep ``/`` and ``:`` inside the completion word (``/help``, not ``help``).
    delims = readline.get_completer_delims()
    for ch in "/:":
        delims = delims.replace(ch, "")
    readline.set_completer_delims(delims)

    matches: list[str] = []

    def completer(text: str, state: int) -> str | None:
        nonlocal matches
        if state == 0:
            line = readline.get_line_buffer()
            matches = suggest_session_slash_completions(line, text)
        if state < len(matches):
            return matches[state]
        return None

    readline.set_completer(completer)

    doc = getattr(readline, "__doc__", "") or ""
    if "libedit" in doc:
        # macOS / libedit
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")
        readline.parse_and_bind("set show-all-if-ambiguous on")
    return True


def zsh_completion_script() -> str:
    return r"""if [[ -o interactive ]]; then
  autoload -Uz compinit
  compinit -C
  autoload -Uz compdef

  _la() {
    local -a suggestions
    local cmd="${words[1]:-LA}"
    if ! command -v "$cmd" >/dev/null 2>&1; then
      cmd=la
      command -v "$cmd" >/dev/null 2>&1 || return
    fi
    suggestions=("${(@f)$("$cmd" complete -- "${words[@]}" 2>/dev/null)}")
    if (( ${#suggestions} == 1 )) && [[ ${suggestions[1]} == __LA_FILE__ ]]; then
      _files
      return
    fi
    if (( ${#suggestions} )); then
      compadd -a suggestions
    fi
  }

  compdef _la LA la
fi
"""


def bash_completion_script() -> str:
    return r"""if [[ $- == *i* ]]; then
  _la_completion() {
    local cur prev words cword
    _init_completion || return
    local cmd="${COMP_WORDS[0]:-LA}"
    local -a suggestions
    mapfile -t suggestions < <("$cmd" complete -- "${COMP_WORDS[@]}" 2>/dev/null)
    if ((${#suggestions[@]} == 1)) && [[ ${suggestions[0]} == __LA_FILE__ ]]; then
      compopt -o filenames
      COMPREPLY=()
      _filedir
      return
    fi
    if ((${#suggestions[@]})); then
      COMPREPLY=("${suggestions[@]}")
    fi
  }

  complete -o default -F _la_completion LA la 2>/dev/null
fi
"""


def _find_venv_dirs() -> list[Path]:
    candidates: list[Path] = []
    if venv := os.environ.get("VIRTUAL_ENV"):
        candidates.append(Path(venv))
    project_venv = config.PROJECT_ROOT / ".venv"
    if project_venv.is_dir():
        candidates.append(project_venv)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _install_venv_activate_hook() -> list[Path]:
    installed: list[Path] = []
    script = zsh_completion_script()
    for venv_dir in _find_venv_dirs():
        activate_d = venv_dir / "activate.d"
        activate_d.mkdir(parents=True, exist_ok=True)
        target = activate_d / "la-completion.zsh"
        target.write_text(script, encoding="utf-8")
        installed.append(target)
    return installed


def install_shell_completion(*, shell: str | None = None) -> tuple[list[Path], Path | None]:
    """Install zsh/bash completion into ~/.zshrc|~/.bashrc and venv activate.d hooks."""
    shell_name = (shell or Path(os.environ.get("SHELL", "zsh")).name).lower()
    if shell_name not in ("zsh", "bash"):
        shell_name = "zsh"

    rc_name = ".zshrc" if shell_name == "zsh" else ".bashrc"
    rc_path = Path.home() / rc_name
    block_body = zsh_completion_script() if shell_name == "zsh" else bash_completion_script()
    block = f"{_ZSHRC_START}\n{block_body}\n{_ZSHRC_END}\n"

    existing = rc_path.read_text(encoding="utf-8") if rc_path.exists() else ""
    if _ZSHRC_START in existing and _ZSHRC_END in existing:
        before, rest = existing.split(_ZSHRC_START, 1)
        _, after = rest.split(_ZSHRC_END, 1)
        updated = before + block + after.lstrip("\n")
    else:
        suffix = "" if existing.endswith("\n") or not existing else "\n"
        updated = existing + suffix + block

    rc_path.write_text(updated, encoding="utf-8")
    venv_hooks = _install_venv_activate_hook()
    return venv_hooks, rc_path


def run_complete_init(argv: list[str]) -> int:
    shell = argv[0] if argv else None
    try:
        venv_hooks, rc_path = install_shell_completion(shell=shell)
    except OSError as exc:
        print(f"[complete-init] 安装失败: {exc}")
        return 1

    print(f"[complete-init] 已写入 {rc_path}")
    if venv_hooks:
        print("[complete-init] 已安装 venv 激活钩子:")
        for hook in venv_hooks:
            print(f"  {hook}")
    print("[complete-init] 请执行: source", rc_path, "  或重新打开终端")
    print("[complete-init] 然后试: LA add<Tab>  应出现 add / add-file")
    return 0
