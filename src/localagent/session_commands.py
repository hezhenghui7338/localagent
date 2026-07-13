"""Session slash commands (/…) shared with outer CLI dispatch.

Inside the chat REPL, lines starting with ``/`` (Claude Code style) or ``:``
(legacy alias) are routed here instead of the agent. Outer ``LA <cmd>`` still
uses the same ``dispatch_cli_argv`` path.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from localagent import config

# Session-only names (not argparse subcommands)
_EXIT_NAMES = frozenset({"q", "quit", "exit"})
_HELP_NAMES = frozenset({"help", "h"})
_PROVIDER_NAMES = frozenset({"provider", "p"})
_MODEL_NAMES = frozenset({"model"})
_DEEPSEARCH_NAME = "deepsearch"
_MODEL_PAGE_SIZE = 10
_MODEL_PAGE_NEXT = frozenset({"next", ">"})
_MODEL_PAGE_PREV = frozenset({"prev", "<"})

# Short aliases → canonical session/CLI name.
# Avoid bare ``/m``: it collides mentally with both model and memories.
_ALIASES: dict[str, str] = {
    "q": "q",
    "quit": "quit",
    "exit": "exit",
    "h": "help",
    "help": "help",
    "p": "provider",
    "provider": "provider",
    "model": "model",
    "mem": "memories",
    "memories": "memories",
    "deepsearch": "deepsearch",
}

# Last known REPL provider (for Tab completion of /model)
_repl_provider: str = "auto"


@dataclass
class _ModelBrowseState:
    provider: str
    models: list[str]
    page: int  # 0-based
    current: str


_model_browse: _ModelBrowseState | None = None


def set_repl_provider(provider: str) -> None:
    """Remember the chat REPL provider for slash-command completion."""
    global _repl_provider
    try:
        _repl_provider = config.normalize_provider_choice(provider)
    except ValueError:
        _repl_provider = "auto"


def get_repl_provider() -> str:
    return _repl_provider


def reset_model_browse() -> None:
    """Clear paginated /model browse state (tests)."""
    global _model_browse
    _model_browse = None


def _model_page_count(total: int) -> int:
    if total <= 0:
        return 1
    return (total + _MODEL_PAGE_SIZE - 1) // _MODEL_PAGE_SIZE


def _clamp_model_page(page: int, total: int) -> int:
    return max(0, min(page, _model_page_count(total) - 1))


def _sync_model_browse(
    provider: str,
    models: list[str],
    current: str,
    *,
    page: int | None = None,
    reset_page: bool = False,
) -> _ModelBrowseState:
    global _model_browse
    if reset_page or _model_browse is None or _model_browse.provider != provider:
        target = 0 if page is None else page
    elif page is not None:
        target = page
    else:
        target = _model_browse.page
    target = _clamp_model_page(target, len(models))
    _model_browse = _ModelBrowseState(
        provider=provider,
        models=list(models),
        page=target,
        current=current,
    )
    return _model_browse


def _page_slice(models: list[str], page: int) -> list[str]:
    start = page * _MODEL_PAGE_SIZE
    return models[start : start + _MODEL_PAGE_SIZE]


@dataclass
class SessionCommandContext:
    """Mutable REPL state visible to session command handlers."""

    session_id: str
    provider: str
    history: list[dict[str, str]] = field(default_factory=list)


@dataclass
class DispatchResult:
    handled: bool = True
    should_exit: bool = False
    exit_code: int = 0
    provider: str | None = None


def is_session_command(line: str) -> bool:
    """True when the line is a slash or legacy colon meta-command."""
    s = line.lstrip()
    return bool(s) and s[0] in ("/", ":")


def list_slash_command_names() -> list[str]:
    """Sorted session slash command names (no leading ``/``).

    Includes outer CLI subcommands (except ``chat``) plus session-only
    names and aliases (``help``, ``h``, ``provider``, ``q``, …).
    """
    from localagent.cli import build_parser
    from localagent.completion import subparser_names

    names = set(subparser_names(build_parser()))
    names.discard("chat")
    names.update(_ALIASES)
    return sorted(names)


def normalize_session_argv(line: str) -> list[str]:
    """Strip ``/`` or ``:`` prefix and split like a shell command line."""
    s = line.strip()
    if not s:
        return []
    if s[0] in ("/", ":"):
        s = s[1:].lstrip()
    if not s:
        return []
    try:
        parts = shlex.split(s)
    except ValueError:
        # Unclosed quote — fall back to simple split so the user sees argparse help
        parts = s.split()
    if not parts:
        return []
    head = parts[0].lower()
    canonical = _ALIASES.get(head, head)
    return [canonical, *parts[1:]]


def print_session_help() -> None:
    """Print outer CLI help plus session-only slash commands."""
    from localagent.cli import build_parser

    parser = build_parser()
    print(parser.format_help().rstrip())
    print()
    print("会话内命令（进入 LA / LA chat 后，以 / 开头；: 为兼容别名）：")
    print("  /help, /h              显示本帮助")
    print("  /provider, /p [name]   查看或切换模型路径")
    print("  /model [name|N]        查看/翻页/切换当前路径模型（写入配置）")
    print("                          翻页: next|prev|page N；序号为本页 1–10")
    print("  /memories, /mem [q]    查询记忆库（语义搜索 / 标签）")
    print("  /deepsearch <主题>     多步联网深度研究")
    print("  /q, /quit, /exit       退出对话")
    print()
    print("外层 LA <command> 与会话内 /<command> 等价（/chat 除外）。")


def dispatch_cli_argv(argv: list[str], *, allow_chat: bool = True) -> int:
    """Parse and run a CLI argv list (no program name).

    When ``allow_chat`` is False (session use), ``chat`` is rejected to avoid
    nested REPLs.
    """
    from localagent.cli import _normalize_config_argv, build_parser

    if not argv:
        if allow_chat:
            argv = ["chat"]
        else:
            print("[LA] 缺少命令。输入 /help 查看可用命令。")
            return 1

    argv = _normalize_config_argv(argv)

    if not allow_chat and argv[0] == "chat":
        print("[LA] 已在对话中，无需 /chat。输入问题开始聊天，或 /help 查看命令。")
        return 1

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        return int(code) if isinstance(code, int) else 1

    if not getattr(args, "cmd", None):
        if allow_chat:
            args = parser.parse_args(["chat"])
        else:
            print("[LA] 缺少命令。输入 /help 查看可用命令。")
            return 1

    return int(args.func(args))


def _handle_provider(argv: list[str], ctx: SessionCommandContext) -> DispatchResult:
    from localagent.models.router import get_model_router

    router = get_model_router()
    if len(argv) < 2:
        status = router.provider_status()
        print(f"当前路径: {router.format_provider_hint(ctx.provider)}")
        for name in config.MODEL_PROVIDER_PRIORITY:
            server = config.get_model_server(name)
            model = (
                router.format_model_hint(name)
                if name == "ollama"
                else (server.model if server else "?")
            )
            mark = "✓" if status.get(name) else "✗"
            print(f"  {name:<12} {mark}  {model}")
        providers = "|".join(config.VALID_PROVIDERS)
        print(f"用法: /provider auto|{providers}")
        return DispatchResult(provider=ctx.provider)

    try:
        ctx.provider = config.normalize_provider_choice(argv[1])
    except ValueError as exc:
        print(f"[provider] {exc}")
        return DispatchResult(exit_code=1, provider=ctx.provider)

    set_repl_provider(ctx.provider)
    print(f"[provider] 已切换为 {router.format_provider_hint(ctx.provider)}")
    return DispatchResult(provider=ctx.provider)


def _print_model_page(state: _ModelBrowseState) -> None:
    total = len(state.models)
    if not state.models:
        print("未获取到可用模型列表（可仍用 /model <名称> 直接设置）。")
        print("用法: /model <名称>")
        return

    pages = _model_page_count(total)
    page_items = _page_slice(state.models, state.page)
    print(f"可用模型 ({total}) 第 {state.page + 1}/{pages} 页：")
    for index, name in enumerate(page_items, start=1):
        mark = "  ←" if name == state.current else ""
        print(f"  {index}. {name}{mark}")
    if pages > 1:
        print("翻页: /model next|prev|page N")
    print(f"选择: /model <1-{len(page_items)}> 或完整名称")


def _apply_model_choice(effective: str, selected: str) -> DispatchResult:
    from localagent import env_config
    from localagent.models.router import get_model_router

    try:
        config_path, _ = env_config.set_server_model(effective, selected)
    except ValueError as exc:
        print(f"[model] {exc}")
        return DispatchResult(exit_code=1)

    get_model_router().clear_model_cache()
    if _model_browse is not None and _model_browse.provider == effective:
        _model_browse.current = selected
    print(f"[model] 已将 {effective} 默认模型设为 {selected}")
    print(f"[model] 已写入 {config_path}（下次启动默认使用）")
    return DispatchResult()


def _handle_model(argv: list[str], ctx: SessionCommandContext) -> DispatchResult:
    from localagent.models.router import get_model_router

    router = get_model_router()
    effective = router.resolve_effective_provider(ctx.provider)
    current = router.format_model_hint(effective)
    models = router.list_provider_models(effective)

    if len(argv) < 2:
        if ctx.provider == config.DEFAULT_MODEL_PROVIDER:
            print(f"当前路径: auto → {effective}")
        else:
            print(f"当前路径: {effective}")
        print(f"当前模型: {current or '(未配置)'}")
        state = _sync_model_browse(effective, models, current, reset_page=True)
        _print_model_page(state)
        return DispatchResult()

    raw = argv[1].strip()
    key = raw.lower()

    # Pagination controls
    if key in _MODEL_PAGE_NEXT or key in _MODEL_PAGE_PREV or key == "page":
        state = _sync_model_browse(effective, models, current)
        if not state.models:
            print("[model] 无可用模型列表，无法翻页。可直接 /model <名称>")
            return DispatchResult(exit_code=1)
        if key == "page":
            if len(argv) < 3 or not argv[2].strip().isdigit():
                print(f"用法: /model page <1-{_model_page_count(len(state.models))}>")
                return DispatchResult(exit_code=1)
            target = int(argv[2].strip()) - 1
            state = _sync_model_browse(effective, models, current, page=target)
        elif key in _MODEL_PAGE_NEXT:
            state = _sync_model_browse(effective, models, current, page=state.page + 1)
        else:
            state = _sync_model_browse(effective, models, current, page=state.page - 1)
        if ctx.provider == config.DEFAULT_MODEL_PROVIDER:
            print(f"当前路径: auto → {effective}")
        else:
            print(f"当前路径: {effective}")
        print(f"当前模型: {current or '(未配置)'}")
        _print_model_page(state)
        return DispatchResult()

    # Page-local index (1..page_size on the current page)
    if raw.isdigit():
        state = _sync_model_browse(effective, models, current)
        page_items = _page_slice(state.models, state.page)
        index = int(raw)
        if index < 1 or index > len(page_items):
            print(f"[model] 序号无效，本页请输入 1–{len(page_items) or 0}（先 /model 或 /model next 翻页）")
            return DispatchResult(exit_code=1)
        return _apply_model_choice(effective, page_items[index - 1])

    selected = raw
    if models and selected not in models:
        print(f"[model] 提示: {selected!r} 不在当前列表中，仍将写入配置")
    return _apply_model_choice(effective, selected)


def _handle_deepsearch(argv: list[str], ctx: SessionCommandContext) -> DispatchResult:
    from localagent.persist.conversations import append_message
    from localagent.tools import deep_search
    from localagent.ui.console import ActivityIndicator

    topic = " ".join(argv[1:]).strip()
    if not topic:
        print("用法: /deepsearch <主题>")
        return DispatchResult(exit_code=1)

    user_line = f"/deepsearch {topic}"
    append_message(ctx.session_id, "user", user_line)
    with ActivityIndicator("deepsearch", f"研究中: {topic}") as activity:
        try:
            report = deep_search(topic, on_status=activity.update)
        except KeyboardInterrupt:
            print("\n[chat] deepsearch 已取消")
            return DispatchResult(exit_code=130)
        except Exception as exc:
            report = f"[deepsearch 失败] {exc}"
    print(report)
    append_message(ctx.session_id, "assistant", report, tool="deepsearch")
    ctx.history.append({"role": "user", "content": user_line})
    ctx.history.append({"role": "assistant", "content": report})
    return DispatchResult()


def dispatch_session_line(line: str, ctx: SessionCommandContext) -> DispatchResult:
    """Dispatch a ``/`` or ``:`` line inside the chat REPL."""
    argv = normalize_session_argv(line)
    if not argv:
        print("[LA] 空命令。输入 /help 查看可用命令。")
        return DispatchResult(exit_code=1)

    cmd = argv[0]
    if cmd in _EXIT_NAMES:
        return DispatchResult(should_exit=True)

    if cmd in _HELP_NAMES:
        print_session_help()
        return DispatchResult()

    if cmd == "m":
        print(
            "[LA] /m 已弃用（易与 model / memories 混淆）。"
            "切换模型用 /model，查询记忆用 /memories 或 /mem。"
        )
        return DispatchResult(exit_code=1)

    if cmd in _PROVIDER_NAMES:
        return _handle_provider(argv, ctx)

    if cmd in _MODEL_NAMES:
        return _handle_model(argv, ctx)

    if cmd == _DEEPSEARCH_NAME:
        return _handle_deepsearch(argv, ctx)

    try:
        rc = dispatch_cli_argv(argv, allow_chat=False)
    except KeyboardInterrupt:
        print("\n[LA] 已中断")
        return DispatchResult(exit_code=130)
    except Exception as exc:
        print(f"[LA] 命令失败: {exc}")
        return DispatchResult(exit_code=1)

    return DispatchResult(exit_code=rc)


def is_meta_user_content(content: str) -> bool:
    """True if a persisted user message is a session meta-command (skip memory extract)."""
    s = (content or "").lstrip()
    return bool(s) and s[0] in ("/", ":")
