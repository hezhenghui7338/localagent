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
# Flags whose values are filesystem paths (Tab → file completion).
_PATH_OPTION_FLAGS = frozenset(
    {
        "--report",
        "--cwd",
        "--file",
        "--dir",
        "--path",
    }
)
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
        paths = sorted(
            list(conv_dir.glob("s-*.json")) + list(conv_dir.glob("s-*.jsonl")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        seen: set[str] = set()
        ids: list[str] = []
        for path in paths:
            if path.stem in seen:
                continue
            seen.add(path.stem)
            ids.append(path.stem)
            if len(ids) >= limit:
                break
        return ids
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


def _is_flag_token(token: str) -> bool:
    return token.startswith("-") and token != "-"


def _option_takes_value(parser: argparse.ArgumentParser, flag: str) -> bool:
    action = _find_option_action(parser, flag)
    if action is None:
        return False
    if isinstance(
        action,
        (argparse._StoreTrueAction, argparse._StoreFalseAction, argparse._HelpAction, argparse._VersionAction),
    ):
        return False
    if action.nargs == 0:
        return False
    return True


def _completing_option(args: list[str], current: str, parser: argparse.ArgumentParser) -> list[str]:
    flags = _option_strings(parser)
    if current.startswith("-"):
        return _prefix_match(flags, current)

    if not args:
        return _prefix_match(flags, current)

    prev = args[-1]
    if not _is_flag_token(prev):
        return _prefix_match(flags, current)

    if prev in ("--provider", "-p"):
        return _prefix_match(list(_CHAT_PROVIDERS), current)
    if prev in ("--session-id", "--session"):
        return _prefix_match(_session_ids(), current)
    if prev == "--tag":
        return _prefix_match(_memory_tags(), current)
    if prev in _PATH_OPTION_FLAGS:
        return _expand_path(current)

    action = _find_option_action(parser, prev)
    if action is not None:
        if action.choices is not None:
            return _prefix_match([str(c) for c in action.choices], current)
        if not _option_takes_value(parser, prev):
            return _prefix_match(flags, current)
        # Value-taking flag without fixed choices (--since, --limit, …)
        return []

    return _prefix_match(flags, current)


def _wants_option_completion(tokens: list[str], current: str, parser: argparse.ArgumentParser) -> bool:
    """True when the cursor is on a flag or the value of a value-taking flag."""
    if current.startswith("-"):
        return True
    if not tokens:
        return False
    prev = tokens[-1]
    if not _is_flag_token(prev):
        return False
    return _option_takes_value(parser, prev)


def _complete_parser(parser: argparse.ArgumentParser, tokens: list[str], current: str) -> list[str]:
    """Walk nested argparse subparsers; at each level complete subcommands or options."""
    subs = _get_subparsers(parser)

    # Descend into a known subcommand before offering this level's flags.
    if subs and tokens and tokens[0] in subs:
        return _complete_parser(subs[tokens[0]], tokens[1:], current)

    if _wants_option_completion(tokens, current, parser):
        return _completing_option(tokens, current, parser)

    if subs:
        names = sorted(subs)
        if current.startswith("-"):
            return _prefix_match(_option_strings(parser), current)
        hits = _prefix_match(names, current)
        if hits:
            return hits
        return _prefix_match(_option_strings(parser), current)

    return _completing_option(tokens, current, parser)


def _complete_tasks(parser: argparse.ArgumentParser, tokens: list[str], current: str) -> list[str]:
    if _wants_option_completion(tokens, current, parser) or current.startswith("-"):
        return _completing_option(tokens, current, parser)
    if not tokens:
        return _prefix_match(list(_TASK_ACTIONS) + _task_ids(), current)
    if tokens[0] in _TASK_ACTIONS and len(tokens) == 1:
        return _prefix_match(_task_ids(), current)
    if tokens[0].startswith("t-"):
        return []
    return _prefix_match(list(_TASK_ACTIONS) + _task_ids(), current)


def _complete_memory(parser: argparse.ArgumentParser, tokens: list[str], current: str) -> list[str]:
    mem_subs = _get_subparsers(parser)
    mem_names = sorted(mem_subs)
    if not tokens:
        return _prefix_match(mem_names, current)

    mem_cmd = tokens[0]
    mem_tail = tokens[1:]
    if mem_cmd not in mem_subs:
        return _prefix_match(mem_names, current)

    mem_parser = mem_subs[mem_cmd]
    if _wants_option_completion(mem_tail, current, mem_parser) or current.startswith("-"):
        return _completing_option(mem_tail, current, mem_parser)
    if mem_cmd == "forget" and not mem_tail:
        return _prefix_match(_memory_ids(), current)
    if mem_cmd == "ingest":
        sources = ["chat", "chatgpt", "all"]
        if not mem_tail:
            return _prefix_match(sources, current)
        if mem_tail[-1] in ("--file", "--dir"):
            return _expand_path(current)
        if mem_tail[0] == "chatgpt" and len(mem_tail) == 1 and not current.startswith("-"):
            return _expand_path(current)
        return _completing_option(mem_tail, current, mem_parser)
    if mem_cmd == "reset" and not mem_tail:
        return _prefix_match(["chat", "chatgpt", "all"], current)
    if mem_cmd == "graph":
        actions = ["stats", "rebuild", "neo4j", "query"]
        if not mem_tail:
            return _prefix_match(actions, current)
        if mem_tail[0] == "neo4j" and len(mem_tail) == 1:
            return _prefix_match(["stats", "rebuild"], current)
        return _completing_option(mem_tail, current, mem_parser)
    if mem_cmd in ("search", "query") and not mem_tail:
        return _completing_option([], current, mem_parser)
    return _completing_option(mem_tail, current, mem_parser)


def _complete_rag(parser: argparse.ArgumentParser, tokens: list[str], current: str) -> list[str]:
    rag_subs = _get_subparsers(parser)
    rag_names = sorted(rag_subs)
    if not tokens:
        return _prefix_match(rag_names, current)

    rag_cmd = tokens[0]
    rag_tail = tokens[1:]
    if rag_cmd not in rag_subs:
        return _prefix_match(rag_names, current)

    rag_parser = rag_subs[rag_cmd]
    if _wants_option_completion(rag_tail, current, rag_parser) or current.startswith("-"):
        return _completing_option(rag_tail, current, rag_parser)
    if rag_cmd == "add":
        return _expand_path(current)
    return _completing_option(rag_tail, current, rag_parser)


def _complete_config(parser: argparse.ArgumentParser, tokens: list[str], current: str) -> list[str]:
    """``config`` has both top-level flags and nested actions."""
    subs = _get_subparsers(parser)
    if tokens and tokens[0] in subs:
        return _complete_parser(parser, tokens, current)
    if current.startswith("-") or _wants_option_completion(tokens, current, parser):
        return _completing_option(tokens, current, parser)
    if not tokens:
        names = sorted(subs)
        hits = _prefix_match(names, current)
        if hits or current:
            return hits
        return names
    return _complete_parser(parser, tokens, current)


def suggest_completions(words: list[str], parser: argparse.ArgumentParser | None = None) -> list[str]:
    """Return completion candidates for a partial LA command line.

    ``words`` is the tokenized line including the program name, with the last
    element the token currently being completed (may be ``""`` after a space).
    """
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
    # Completed tokens after the program name (exclude the current partial word).
    argv = words[1:-1]

    if not argv:
        return _prefix_match(commands, current)

    cmd = argv[0]
    tail = argv[1:]

    if cmd not in subparsers:
        return _prefix_match(commands, current)

    sub = subparsers[cmd]
    if cmd == "tasks":
        return _complete_tasks(sub, tail, current)
    if cmd == "memory":
        return _complete_memory(sub, tail, current)
    if cmd == "rag":
        return _complete_rag(sub, tail, current)
    if cmd == "config":
        return _complete_config(sub, tail, current)
    return _complete_parser(sub, tail, current)


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


def _adapt_readline_matches(hits: list[str], *, text: str, token: str) -> list[str]:
    """Map full-token hits to replacements for readline's ``text``.

    macOS libedit defaults treat ``-`` as a word break, so typing ``/audit --rep``
    may yield ``text='rep'`` while the real token is ``--rep``. Returning
    ``--report`` would then corrupt the line; return ``report`` instead.
    """
    if not hits:
        return []
    if not text:
        return hits
    if not token or token == text:
        prefixed = [h for h in hits if h.startswith(text)]
        return prefixed if prefixed else hits
    if token.endswith(text) and len(token) > len(text):
        kept = token[: -len(text)]
        out: list[str] = []
        for hit in hits:
            if hit.startswith(token):
                out.append(hit[len(kept) :])
            elif hit.startswith(text):
                out.append(hit)
        return out
    prefixed = [h for h in hits if h.startswith(text)]
    return prefixed if prefixed else hits


def _session_arg_completions(cmd: str, completed: list[str], current: str) -> list[str]:
    """Complete arguments after a session slash command name.

    ``completed`` are finished tokens after the command name; ``current`` is the
    partial token under the cursor (``""`` after a trailing space).
    """
    if cmd == "provider":
        needle = current.lower()
        return [c for c in _session_provider_choices() if c.startswith(needle)]
    if cmd == "model":
        # Avoid dumping hundreds of models on bare Tab (readline "Display all N?").
        # Require a filter prefix; then match by prefix or substring.
        needle = current.strip()
        if not needle:
            return []
        models = _session_model_choices()
        exact = [m for m in models if m.startswith(needle)]
        if exact:
            return exact[:50]
        return [m for m in models if needle.lower() in m.lower()][:50]

    # Reuse outer CLI completion for subcommands exposed as slash commands
    # (e.g. ``/memory query --sort`` → newest|oldest|relevance).
    from localagent.cli import build_parser

    parser = build_parser()
    if cmd not in _get_subparsers(parser):
        return []
    return suggest_completions(["LA", cmd, *completed, current], parser)


def suggest_session_slash_completions(line: str, text: str = "") -> list[str]:
    """Tab-completion candidates for a chat REPL line starting with ``/`` or ``:``.

    Completes command names, and for ``/provider`` / ``/p`` also completes
    configured provider paths (``auto``, ``ollama``, ``cursor``, …). For
    ``/model`` completes models only when a filter prefix is typed. For CLI
    subcommands like ``/memory``, reuses shell option/value completion.
    """
    stripped = line.lstrip()
    if not stripped or stripped[0] not in ("/", ":"):
        return []

    prefix = stripped[0]
    rest = stripped[1:]

    from localagent.session_commands import list_slash_command_names

    # Past the command name → complete args from the line tokens (not readline
    # delims), then adapt hits so they correctly replace readline ``text``.
    if rest and any(ch.isspace() for ch in rest):
        parts = rest.split()
        if not parts:
            return []
        cmd = parts[0].lower()
        trailing_space = rest[-1].isspace()
        if trailing_space:
            completed = parts[1:]
            current = ""
        else:
            completed = parts[1:-1]
            current = parts[-1] if len(parts) > 1 else ""

        if cmd in ("p", "provider"):
            cmd = "provider"
        elif cmd == "model":
            cmd = "model"
        elif cmd in ("add", "search", "forget"):
            hits = _session_arg_completions("memory", [cmd, *completed], current)
            return _adapt_readline_matches(hits, text=text, token=current)
        hits = _session_arg_completions(cmd, completed, current)
        return _adapt_readline_matches(hits, text=text, token=current)

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

    # Exact command name: do not also offer longer prefixes.
    # Ambiguous Tab listing on macOS libedit often corrupts the line (ghost ``>``).
    if needle and needle in hits:
        return _filter_prefix([f"{prefix}{needle}"], text)

    candidates = [f"{prefix}{name}" for name in hits]
    return _filter_prefix(candidates, text)


def install_repl_readline_completer() -> bool:
    """Install readline Tab completion for session slash commands. Returns True if installed."""
    try:
        import readline
    except ImportError:
        return False

    # Keep ``/``, ``:``, ``-``, ``.`` inside the completion word so flags like
    # ``--report`` and model ids like ``qwen3.5:4b`` stay one token.
    delims = readline.get_completer_delims()
    for ch in "/:-.":
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


_ACTIVATE_START = "# >>> LA CLI completion >>>"
_ACTIVATE_END = "# <<< LA CLI completion <<<"
_ACTIVATE_SOURCE_SNIPPET = f"""{_ACTIVATE_START}
if [ -n "${{ZSH_VERSION:-}}" ]; then
  if [ -f "$VIRTUAL_ENV/activate.d/la-completion.zsh" ]; then
    # shellcheck disable=SC1091
    . "$VIRTUAL_ENV/activate.d/la-completion.zsh"
  fi
elif [ -n "${{BASH_VERSION:-}}" ]; then
  if [ -f "$VIRTUAL_ENV/activate.d/la-completion.bash" ]; then
    # shellcheck disable=SC1091
    . "$VIRTUAL_ENV/activate.d/la-completion.bash"
  fi
fi
{_ACTIVATE_END}
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


def _write_if_changed(path: Path, content: str) -> bool:
    """Write ``content`` when missing or different. Returns True if written."""
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _upsert_marked_block(existing: str, *, start: str, end: str, block: str) -> str:
    if start in existing and end in existing:
        before, rest = existing.split(start, 1)
        _, after = rest.split(end, 1)
        return before + block + after.lstrip("\n")
    suffix = "" if existing.endswith("\n") or not existing else "\n"
    return existing + suffix + block


def _patch_venv_activate(venv_dir: Path) -> Path | None:
    """Ensure ``bin/activate`` sources activate.d completion scripts on ``source activate``."""
    activate = venv_dir / "bin" / "activate"
    if not activate.is_file():
        return None
    existing = activate.read_text(encoding="utf-8")
    updated = _upsert_marked_block(
        existing,
        start=_ACTIVATE_START,
        end=_ACTIVATE_END,
        block=_ACTIVATE_SOURCE_SNIPPET,
    )
    if updated != existing:
        activate.write_text(updated, encoding="utf-8")
    return activate


def _install_venv_activate_hook() -> list[Path]:
    """Install completion scripts + activate sourcing so ``source .venv/bin/activate`` loads them."""
    installed: list[Path] = []
    zsh_script = zsh_completion_script()
    bash_script = bash_completion_script()
    for venv_dir in _find_venv_dirs():
        activate_d = venv_dir / "activate.d"
        activate_d.mkdir(parents=True, exist_ok=True)
        for name, script in (
            ("la-completion.zsh", zsh_script),
            ("la-completion.bash", bash_script),
        ):
            target = activate_d / name
            _write_if_changed(target, script)
            installed.append(target)
        patched = _patch_venv_activate(venv_dir)
        if patched is not None:
            installed.append(patched)
    return installed


def install_shell_completion(*, shell: str | None = None) -> tuple[list[Path], Path | None]:
    """Install zsh/bash completion into ~/.zshrc|~/.bashrc and venv activate hooks."""
    shell_name = (shell or Path(os.environ.get("SHELL", "zsh")).name).lower()
    if shell_name not in ("zsh", "bash"):
        shell_name = "zsh"

    rc_name = ".zshrc" if shell_name == "zsh" else ".bashrc"
    rc_path = Path.home() / rc_name
    block_body = zsh_completion_script() if shell_name == "zsh" else bash_completion_script()
    block = f"{_ZSHRC_START}\n{block_body}\n{_ZSHRC_END}\n"

    existing = rc_path.read_text(encoding="utf-8") if rc_path.exists() else ""
    updated = _upsert_marked_block(
        existing,
        start=_ZSHRC_START,
        end=_ZSHRC_END,
        block=block,
    )
    _write_if_changed(rc_path, updated)
    venv_hooks = _install_venv_activate_hook()
    return venv_hooks, rc_path


def ensure_shell_completion(*, shell: str | None = None) -> None:
    """Idempotently install shell completion (quiet). Safe to call on every LA startup."""
    try:
        install_shell_completion(shell=shell)
    except OSError:
        # Home / venv may be read-only (CI, sandboxed shells); never block the CLI.
        return


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
    print("[complete-init] 重新 source 虚拟环境或执行: source", rc_path)
    print("[complete-init] 然后试: LA memory<Tab>  应出现 memory 子命令")
    return 0
