"""LA CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from localagent import config
from localagent.chat_repl import run_chat
from localagent.ingest.add_file import add_file, add_file_background, restart_background_task
from localagent.ingest.sync_file import sync_files
from localagent.ingest.progress import ConsoleProgressReporter
from localagent.ingest.tasks import TaskStatus, format_task_line, get_task_store
from localagent.memory.chatgpt_import import import_chatgpt_dir, import_chatgpt_file, import_chatgpt_files
from localagent.memory.hindsight_client import describe_memory_backend, get_memory_backend
from localagent.memory.query import list_memory_tags, query_memories
from localagent.memory.rememorize import rememorize_chat
from localagent.memory.reset import rebuild_memory, reset_memory
from localagent.memory.store import get_memory_store
from localagent.tools import query_memories_tool, reflect_memory, search_knowledge, search_memory
from localagent.ui.console import emit


def _print_ingest_result(result) -> None:
    if result.status.value == "failed":
        print(f"  ! {result.filename}: {result.error}")
        return
    print(
        f"  {result.tag} {result.filename}: "
        f"facts={result.memory_fact_count}, chunks={result.knowledge_chunk_count}"
    )


def _ensure_ollama_for_chat() -> None:
    """Offer optional Ollama install/pull before entering chat (user can decline)."""
    from localagent.ollama_setup import ensure_ollama_ready

    result = ensure_ollama_ready(prompt=True)
    if result.declined or result.skipped:
        if result.message:
            print(f"[setup] {result.message}")
        return
    if result.installed_now or result.pulled_now:
        print(f"[setup] {result.message}")
    elif not result.model_ready:
        print(f"[setup] 警告: {result.message}")


def cmd_setup(args: argparse.Namespace) -> int:
    from localagent.ollama_setup import ensure_ollama_ready

    result = ensure_ollama_ready(
        prompt=not getattr(args, "yes", False),
        assume_yes=bool(getattr(args, "yes", False)),
    )
    print(f"[setup] {result.message}")
    if result.declined or result.skipped:
        return 0
    if not result.installed or not result.model_ready:
        return 1
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    try:
        provider = config.normalize_provider_choice(args.provider)
    except ValueError as exc:
        print(f"[chat] {exc}")
        return 1
    if args.cwd:
        _apply_workspace_cwd(args.cwd)
    if provider in ("auto", "ollama"):
        _ensure_ollama_for_chat()
    return run_chat(session_id=args.session_id, provider=provider)


def cmd_add(args: argparse.Namespace) -> int:
    backend = get_memory_backend()
    emit("add", "写入记忆…")
    fact_id = backend.retain(
        args.text,
        metadata={"source": "manual_add", "source_file": "LA add", "section_heading": ""},
    )
    if not fact_id:
        print("[add] 内容太短或无价值，未写入")
        return 1
    print(f"[add] 已写入记忆 (id={fact_id[:8]}...)")
    fact = get_memory_store().get(fact_id)
    if fact:
        title = fact.metadata.get("title") or fact.text[:30]
        tags = fact.metadata.get("tags") or []
        tag_hint = f" · {'/'.join(tags)}" if tags else ""
        print(f"      「{title}」{tag_hint}")
    return 0


def _format_file_size(path: str | Path) -> str:
    try:
        size = Path(path).stat().st_size
    except OSError:
        return "unknown"
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def cmd_add_file(args: argparse.Namespace) -> int:
    source = Path(args.path).expanduser().resolve()
    try:
        if args.background:
            print(f"[add-file] 源文件: {source} ({_format_file_size(source)})")
            target, task, pid = add_file_background(args.path)
            print(f"[add-file] 软链: {target}")
            print(f"[add-file] 后台任务 {task.id} (pid={pid})")
            if task.log_path:
                print(f"[add-file] 日志: {task.log_path}")
            print(f"→ LA tasks {task.id}       查看进度")
            print(f"→ LA tasks logs {task.id}  查看输出")
            return 0

        print(f"[add-file] 源文件: {source} ({_format_file_size(source)})")
        reporter = ConsoleProgressReporter(prefix="add-file")
        target, result = add_file(args.path, reporter=reporter)
    except KeyboardInterrupt:
        print("\n[add-file] 已中断")
        return 130
    except (FileNotFoundError, ValueError, FileExistsError) as exc:
        print(f"[add-file] error: {exc}")
        return 1

    print(f"[add-file] 软链: {target}")
    _print_ingest_result(result)
    if result.status.value == "failed":
        return 1
    print("[add-file] done")
    return 0


def _print_task_detail(task) -> None:
    print(f"[tasks] {task.id}")
    print(f"  status: {task.status.value}")
    print(f"  file: {task.filename}")
    print(f"  source: {task.source_path}")
    print(f"  symlink: {task.target_path}")
    if task.pid:
        print(f"  pid: {task.pid}")
    if task.log_path:
        print(f"  log: {task.log_path}")
    if task.progress_total > 0:
        print(f"  progress: {task.phase} {task.progress_current}/{task.progress_total}")
    elif task.phase:
        print(f"  phase: {task.phase}")
    if task.message:
        print(f"  message: {task.message}")
    if task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
        print(
            f"  result: {task.result_status} "
            f"facts={task.memory_fact_count} chunks={task.knowledge_chunk_count}"
        )
    if task.status == TaskStatus.FAILED and task.error:
        print(f"  error: {task.error}")
    print(f"  created: {task.created_at}")
    print(f"  updated: {task.updated_at}")
    if task.status in (TaskStatus.RUNNING, TaskStatus.PAUSED, TaskStatus.QUEUED):
        print("  actions: LA tasks pause|delete|logs", task.id)
    elif task.status in (TaskStatus.FAILED, TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.CANCELLED):
        print("  actions: LA tasks restart|delete|logs", task.id)


def _parse_tasks_positional(positional: list[str]) -> tuple[str, str | None]:
    actions = {"delete", "pause", "resume", "restart", "logs", "show", "list"}
    if not positional:
        return "list", None
    if positional[0].startswith("t-"):
        if len(positional) == 1:
            return "show", positional[0]
        raise ValueError(f"未知参数: {' '.join(positional)}")
    if positional[0] in actions:
        if len(positional) < 2 and positional[0] != "list":
            raise ValueError(f"请指定任务 ID，例如: LA tasks {positional[0]} t-abc12345")
        return positional[0], positional[1] if len(positional) > 1 else None
    raise ValueError(
        f"未知子命令: {positional[0]}；可用: delete pause resume restart logs，或直接 LA tasks <task_id>"
    )


def cmd_tasks(args: argparse.Namespace) -> int:
    store = get_task_store()
    try:
        action, task_id = _parse_tasks_positional(args.positional)
    except ValueError as exc:
        print(f"[tasks] {exc}")
        return 1

    if action == "list":
        tasks = store.list_tasks(limit=args.limit)
        active = [t for t in tasks if t.status in (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.PAUSED)]
        if not active:
            print("[tasks] 无进行中的任务")
        else:
            print(f"[tasks] 进行中 {len(active)} 项:")
            for task in active:
                print(format_task_line(task))

        recent = [t for t in tasks if t.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.PAUSED)]
        if recent:
            print(f"[tasks] 最近完成 {min(len(recent), args.limit)} 项:")
            for task in recent[: args.limit]:
                print(format_task_line(task))
        elif not active:
            print("[tasks] 暂无历史任务")
        print("[tasks] 管理: LA tasks delete|pause|resume|restart|logs <task_id>")
        return 0

    if task_id is None:
        print("[tasks] 缺少任务 ID")
        return 1

    if action == "show":
        task = store.get(task_id)
        if task is None:
            print(f"[tasks] 未找到任务: {task_id}")
            return 1
        _print_task_detail(task)
        return 0

    if action == "delete":
        task = store.delete(task_id)
        if task is None:
            print(f"[tasks] 未找到任务: {task_id}")
            return 1
        print(f"[tasks] 已删除 {task_id} ({task.filename})")
        return 0

    if action == "pause":
        try:
            task = store.pause(task_id)
        except ValueError as exc:
            print(f"[tasks] {exc}")
            return 1
        if task is None:
            print(f"[tasks] 未找到任务: {task_id}")
            return 1
        print(f"[tasks] 已暂停 {task_id} (pid={task.pid})")
        return 0

    if action == "resume":
        try:
            task = store.resume(task_id)
        except ValueError as exc:
            print(f"[tasks] {exc}")
            return 1
        if task is None:
            print(f"[tasks] 未找到任务: {task_id}")
            return 1
        print(f"[tasks] 已恢复 {task_id} (pid={task.pid})")
        return 0

    if action == "restart":
        try:
            task, pid = restart_background_task(task_id)
        except ValueError as exc:
            print(f"[tasks] {exc}")
            return 1
        print(f"[tasks] 已重启 {task_id} (pid={pid})")
        if task.log_path:
            print(f"  log: {task.log_path}")
        return 0

    if action == "logs":
        task = store.get(task_id, reconcile=False)
        if task is None:
            print(f"[tasks] 未找到任务: {task_id}")
            return 1
        text = store.get_log_text(task_id, tail=args.tail)
        if not text:
            print(f"[tasks] 任务 {task_id} 暂无日志")
            if task.log_path:
                print(f"  log: {task.log_path}")
            return 0
        print(f"[tasks] 日志 {task_id} (最近 {args.tail} 行):")
        print(text)
        return 0

    print(f"[tasks] 未知操作: {action}")
    return 1


def cmd_sync_file(args: argparse.Namespace) -> int:
    emit("sync-file", f"扫描 {config.KB_DIR}/ …")
    reporter = ConsoleProgressReporter(prefix="sync-file")
    summary = sync_files(force=args.force, reporter=reporter)
    if not summary.results:
        print(f"[sync-file] no supported files in {config.KB_DIR}/")
        return 0

    for result in summary.results:
        _print_ingest_result(result)

    print(f"[sync-file] {summary.format_summary()}")
    return 1 if summary.failed_count else 0


def cmd_reset_memory(args: argparse.Namespace) -> int:
    reporter = ConsoleProgressReporter(prefix="reset-memory")
    stats = reset_memory(clear_knowledge=not args.keep_knowledge, reporter=reporter)
    print("[reset-memory] cleared:")
    print(f"  memory facts removed: {stats['memory_facts_removed']}")
    print(f"  sync_index entries removed: {stats['sync_index_entries_removed']}")
    if stats["clear_knowledge"]:
        print(f"  knowledge chunks removed: {stats['knowledge_chunks_removed']}")
    else:
        print("  knowledge index kept (--keep-knowledge)")
    print("[reset-memory] done (kb/ symlinks and conversations preserved)")
    return 0


def cmd_rebuild_memory(args: argparse.Namespace) -> int:
    reporter = ConsoleProgressReporter(prefix="rebuild-memory")
    reset_stats, summary = rebuild_memory(reporter=reporter)
    print("[rebuild-memory] reset:")
    print(f"  memory facts removed: {reset_stats['memory_facts_removed']}")
    print(f"  sync_index entries removed: {reset_stats['sync_index_entries_removed']}")
    print(f"  knowledge chunks removed: {reset_stats['knowledge_chunks_removed']}")
    for result in summary.results:
        _print_ingest_result(result)
    print(f"[rebuild-memory] {summary.format_summary()}")
    return 1 if summary.failed_count else 0


def cmd_rememorize_chat(args: argparse.Namespace) -> int:
    reporter = ConsoleProgressReporter(prefix="rememorize-chat")
    interactive = True if args.interactive else None
    ids = rememorize_chat(
        session_id=args.session,
        reporter=reporter,
        interactive=interactive,
    )
    if not ids:
        print("[rememorize-chat] 未提取到新记忆")
        return 0
    print(f"[rememorize-chat] 已保存 {len(ids)} 条记忆")
    return 0


def cmd_import_chatgpt(args: argparse.Namespace) -> int:
    reporter = ConsoleProgressReporter(prefix="import-chatgpt")
    interactive = args.interactive
    if args.files and args.path:
        print("[import-chatgpt] 不能同时指定 path 与 --file")
        return 1
    if args.files:
        summary = import_chatgpt_files(
            [Path(path) for path in args.files],
            force=args.force,
            include_disabled=args.include_disabled,
            reporter=reporter,
            interactive=interactive,
        )
    elif args.directory:
        summary = import_chatgpt_dir(
            Path(args.directory),
            force=args.force,
            include_disabled=args.include_disabled,
            reporter=reporter,
            interactive=interactive,
        )
    elif args.path:
        summary = import_chatgpt_file(
            Path(args.path),
            force=args.force,
            include_disabled=args.include_disabled,
            reporter=reporter,
            interactive=interactive,
        )
    else:
        default_dir = config.CHATGPT_DATA_DIR
        if default_dir.is_dir() and any(default_dir.glob("*.json")):
            emit("import-chatgpt", f"使用默认目录 {default_dir}")
            summary = import_chatgpt_dir(
                default_dir,
                force=args.force,
                include_disabled=args.include_disabled,
                reporter=reporter,
                interactive=interactive,
            )
        else:
            print("[import-chatgpt] 请指定导出文件路径，或使用 --file / --dir")
            print("  对话历史: conversations.json")
            print("  已保存记忆: memory.json / memories.json")
            return 1

    for err in summary.errors:
        print(f"[import-chatgpt] ! {err}")

    print(f"[import-chatgpt] {summary.format_summary()}")
    if summary.saved_count:
        print(f"→ 已写入 {summary.saved_count} 条记忆")
    elif summary.imported == 0 and not summary.errors:
        print("[import-chatgpt] 未提取到新的记忆")
    return 1 if summary.errors and summary.files_processed == 0 else 0


def cmd_forget(args: argparse.Namespace) -> int:
    backend = get_memory_backend()
    fact = get_memory_store().get(args.id)
    if fact is None:
        print(f"[forget] 未找到记忆: {args.id}")
        return 1
    if not args.yes:
        preview = fact.text[:120] + ("…" if len(fact.text) > 120 else "")
        try:
            answer = input(f"删除记忆 {fact.id[:8]}… 「{preview}」？[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if answer not in ("y", "yes"):
            print("[forget] 已取消")
            return 0
    if backend.delete(fact.id):
        print(f"[forget] 已删除 {fact.id[:8]}…")
        return 0
    print(f"[forget] 删除失败: {fact.id}")
    return 1


def cmd_search(args: argparse.Namespace) -> int:
    if args.knowledge:
        emit("search", f"检索知识库: {args.query}")
        print(search_knowledge(args.query, top_k=args.top_k))
    else:
        emit("search", f"检索记忆: {args.query}")
        backend = get_memory_backend()
        hits = backend.recall(args.query, max_results=args.top_k)
        result = search_memory(
            args.query,
            top_k=args.top_k,
            show_ids=bool(hits),
            fallback=True,
            verbose=args.verbose,
        )
        print(result)
        if hits:
            print("→ LA forget <id>  删除某条记忆")
    return 0


def cmd_memory_status(_args: argparse.Namespace) -> int:
    info = describe_memory_backend()
    print("[memory-status] Warm 层记忆引擎诊断")
    print(f"  当前后端:     {info['active_backend']} ({info.get('backend_class', '?')})")
    print(f"  配置偏好:     {info['preference']} (LA_MEMORY_BACKEND)")
    print(f"  Python:       {info['python_version']}")
    print(f"  Hindsight:    {'已安装' if info['hindsight_installed'] else '未安装'}")
    if info["hindsight_installed"]:
        llm_ok = info.get("hindsight_llm_available", False)
        mode = info.get("hindsight_extraction_mode", "?")
        print(f"  Retain 模式:  {mode} (LA_HINDSIGHT_EXTRACTION_MODE)")
        if mode == "chunks":
            print(f"  Retain LLM:   不需要（chunks 模式直接分块入库）")
        else:
            print(f"  Retain LLM:   {'可用' if llm_ok else '不可用'} ({info.get('hindsight_llm_provider', '?')}/{info.get('hindsight_llm_model', '?')})")
        configured = info.get("ollama_model_configured")
        resolved = info.get("hindsight_llm_model")
        if configured and resolved and configured != resolved:
            print(f"  ⚠ Ollama 模型: 配置 {configured} → 实际使用 {resolved}")
        print(f"  Retain 降级:  {'开启' if info.get('retain_json_fallback') else '关闭'} (LA_HINDSIGHT_RETAIN_JSON_FALLBACK)")
    if not info["python_ok_for_hindsight"]:
        print("  ⚠ Python 3.11+ 才能安装 hindsight-all")
    print(f"  记忆条数:     {info['memory_count']}")
    print(f"  Bank ID:      {info['bank_id']}")
    print(f"  本地索引:     {info['store_file']}")
    if info.get("error"):
        print(f"  错误:         {info['error']}")
    if info["active_backend"] == "json" and info["preference"] == "auto":
        print("\n提示: 安装 Hindsight 后可获得 4 路并行 recall + reflect + consolidation")
        print("  pip install 'la-localagent[hindsight]'  # 需要 Python 3.11+")
    return 0


def cmd_reflect(args: argparse.Namespace) -> int:
    emit("reflect", f"推理记忆: {args.query}")
    print(reflect_memory(args.query))
    return 0


def cmd_memories(args: argparse.Namespace) -> int:
    tags = [part.strip() for part in (args.tag or []) if part.strip()]
    sort = args.sort if args.sort in ("newest", "oldest", "relevance") else "newest"

    if args.list_tags:
        ranked = list_memory_tags(limit=args.limit)
        if not ranked:
            print("记忆库中暂无标签。")
            return 0
        print(f"共 {len(ranked)} 个标签：")
        for tag, count in ranked:
            print(f"  #{tag}  ({count})")
        return 0

    if args.json:
        hits = query_memories(
            query=args.query or "",
            tags=tags or None,
            since=args.since,
            until=args.until,
            sort=sort,  # type: ignore[arg-type]
            limit=args.limit,
        )
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return 0

    emit("memories", "查询记忆库…")
    result = query_memories_tool(
        query=args.query or "",
        tags=tags or None,
        since=args.since,
        until=args.until,
        sort=sort,
        limit=args.limit,
        show_ids=True,
        verbose=args.verbose,
    )
    print(result)
    if get_memory_backend().count():
        print("→ LA forget <id>  删除某条记忆")
    return 0


def _apply_workspace_cwd(cwd: str | None) -> None:
    if not cwd:
        return
    import os

    os.environ["LA_WORKSPACE"] = str(Path(cwd).expanduser().resolve())


def cmd_workspace(args: argparse.Namespace) -> int:
    _apply_workspace_cwd(args.cwd)
    from localagent.workspace.context import format_workspace_summary, resolve_workspace, scan_todos

    root = resolve_workspace()
    if args.todos_only:
        todos = scan_todos(root, limit=args.limit)
        print(f"[workspace] 待办 ({root})")
        if not todos:
            print("  未扫描到 TODO/FIXME 或未勾选的 checkbox")
            return 0
        for item in todos:
            print(f"  [{item['kind']}] {item['path']}:{item['line']}  {item['text']}")
        print(f"[workspace] 共 {len(todos)} 条")
        return 0

    print(format_workspace_summary(days=args.days, workspace=root))
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    _apply_workspace_cwd(args.cwd)
    from localagent.audit.report import print_audit_summary, write_report
    from localagent.audit.usage import parse_since

    if args.since:
        try:
            parse_since(args.since)
        except ValueError as exc:
            print(f"[audit] {exc}")
            return 1

    if args.report:
        out = Path(args.report).expanduser()
        write_report(out, since=args.since, workspace_days=args.days)
        print(f"[audit] 报告已写入 {out}")
        return 0

    print(print_audit_summary(since=args.since, workspace_days=args.days))
    return 0


def _print_config_ensure_result(result) -> None:
    if result.config_path:
        print(f"[config] 配置文件: {result.config_path}")
    else:
        print("[config] 配置文件: 未找到（使用内置默认）")
    print(f"[config] 环境文件: {result.env_path}")
    if result.has_changes:
        print("[config] 已重新加载，变更如下:")
        for line in result.change_lines():
            print(f"  · {line}")
    else:
        print("[config] 配置已是最新，无变更")
    if result.priority_after:
        print(f"[config] 生效优先级: {'→'.join(result.priority_after)}")


def _print_simple_config_result(result) -> None:
    print(f"[config] 环境文件: {result.env_path}")
    if result.config_path:
        print(f"[config] 模型配置: {result.config_path}")
    print("[config] 已写入:")
    for line in result.change_lines():
        print(f"  · {line}")
    print("[config] 立即生效于当前进程；新开终端也会读取上述文件")


def _has_simple_config_flags(args: argparse.Namespace) -> bool:
    return any(
        getattr(args, name, None) is not None
        for name in (
            "provider",
            "base_url",
            "model",
            "api_key",
            "timeout",
            "tavily_api_key",
            "openrouter_api_key",
            "cursor_api_key",
            "minimax_api_key",
        )
    )


def _add_simple_config_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", help="模型路径，如 ollama / openrouter / cursor")
    parser.add_argument(
        "--base_url",
        "--base-url",
        dest="base_url",
        help="API base URL",
    )
    parser.add_argument("--model", help="模型名称，如 qwen3.5:4b")
    parser.add_argument(
        "--api_key",
        "--api-key",
        dest="api_key",
        help="该 provider 的 API Key",
    )
    parser.add_argument("--timeout", type=float, help="请求超时秒数")
    parser.add_argument(
        "--TAVILY_API_KEY",
        "--tavily-api-key",
        dest="tavily_api_key",
        help="Tavily 联网搜索 Key（可为空字符串）",
    )
    parser.add_argument(
        "--OPENROUTER_API_KEY",
        "--openrouter-api-key",
        dest="openrouter_api_key",
        help="OpenRouter API Key",
    )
    parser.add_argument(
        "--CURSOR_API_KEY",
        "--cursor-api-key",
        dest="cursor_api_key",
        help="Cursor API Key",
    )
    parser.add_argument(
        "--MINIMAX_API_KEY",
        "--minimax-api-key",
        dest="minimax_api_key",
        help="MiniMax API Key",
    )


def _config_list(env_path) -> int:
    from localagent import env_config

    print(f"[config] 环境文件: {env_path}")
    config_file = env_config.resolve_model_servers_file(env_path)
    inline = env_config.read_env_value(env_path, env_config.LA_MODEL_SERVERS_KEY)
    if config_file and config_file.is_file():
        print(f"[config] 模型配置: {config_file}")
    elif inline:
        print("[config] 模型配置: .env 内 LA_MODEL_SERVERS（建议迁移到 config/model_servers.yaml）")
    else:
        print("[config] 模型配置: 内置默认（首次运行会自动创建 config/model_servers.yaml）")
    priority_override = env_config.read_priority_override(env_path)
    file_order = [s.provider for s in env_config.read_model_servers(env_path)]
    mem_order = [s.provider for s in config.MODEL_SERVERS]
    if file_order != mem_order:
        print(
            "[config] 警告: 磁盘配置与内存不一致，请保存 YAML 后执行 LA config init"
        )
        print(f"[config] 磁盘顺序: {'→'.join(file_order)}")
        print(f"[config] 内存顺序: {'→'.join(mem_order)}")
    effective = list(config.MODEL_PROVIDER_PRIORITY)
    print(f"[config] 生效优先级: {'→'.join(effective)}")
    if priority_override:
        print(f"[config] LA_MODEL_PROVIDER_PRIORITY 覆盖: {priority_override}")
    else:
        print("[config] 未设置 LA_MODEL_PROVIDER_PRIORITY，按配置文件列表顺序")
    print()
    for index, server in enumerate(config.MODEL_SERVERS, start=1):
        item = env_config.ServerStatus(server=server, index=index)
        status = "已配置" if server.is_configured else "未配置"
        model = server.model or "-"
        base = server.base_url or "-"
        print(
            f"  {item.index}. {server.provider:<12} model={model:<24} "
            f"key={item.masked_key:<16} ({status})"
        )
        if base != "-":
            print(f"      base_url={base}  timeout={server.timeout}")
    print()
    for alias, env_var in env_config.STANDALONE_KEYS.items():
        value = env_config.read_env_value(env_path, env_var)
        status = "已配置" if value else "未配置"
        print(f"  {alias:<12} {env_var:<28} {env_config.mask_secret(value):<16} ({status})")
    print()
    print("快速配置:")
    print('  la config --provider ollama --base_url "http://localhost:11434" --model qwen3.5:4b')
    print('  la config --TAVILY_API_KEY "tvly-..."')
    print("  la config my.json          # 见 la config-example")
    return 0


def cmd_config_example(_args: argparse.Namespace) -> int:
    from localagent import env_config

    try:
        print(env_config.config_example_text(), end="")
    except FileNotFoundError as exc:
        print(f"[config-example] {exc}")
        return 1
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    from localagent import env_config

    env_path = env_config.resolve_env_file()
    env_config.ensure_config(env_path=env_path)

    config_cmd = getattr(args, "config_cmd", None)

    # Flat mode: la config --provider ... / la config set --provider ...
    if config_cmd in (None, "set") and _has_simple_config_flags(args):
        try:
            result = env_config.apply_config_flags(
                provider=getattr(args, "provider", None),
                base_url=getattr(args, "base_url", None),
                model=getattr(args, "model", None),
                api_key=getattr(args, "api_key", None),
                timeout=getattr(args, "timeout", None),
                tavily_api_key=getattr(args, "tavily_api_key", None),
                openrouter_api_key=getattr(args, "openrouter_api_key", None),
                cursor_api_key=getattr(args, "cursor_api_key", None),
                minimax_api_key=getattr(args, "minimax_api_key", None),
                env_path=env_path,
            )
        except (ValueError, FileNotFoundError) as exc:
            print(f"[config] {exc}")
            return 1
        _print_simple_config_result(result)
        return 0

    if config_cmd == "apply" or (config_cmd is None and getattr(args, "config_file", None)):
        path = getattr(args, "config_file", None) or getattr(args, "apply_path", None)
        if not path:
            print("[config] 请指定 JSON 文件，例如: la config my.json")
            return 1
        try:
            result = env_config.apply_config_file(path, env_path=env_path)
        except (ValueError, FileNotFoundError) as exc:
            print(f"[config] {exc}")
            return 1
        _print_simple_config_result(result)
        return 0

    if config_cmd == "set":
        print(
            "[config] 用法: la config --provider ollama --base_url "
            '"http://localhost:11434" --model qwen3.5:4b [--TAVILY_API_KEY ...]'
        )
        print("[config] 或: la config my.json   （模板: la config-example）")
        return 1

    if config_cmd in (None, "list"):
        return _config_list(env_path)

    if args.config_cmd == "add":
        try:
            if args.json:
                server = env_config.parse_server_json(args.json)
            elif args.provider and args.model:
                from localagent.model_servers import ModelServer

                server = ModelServer(
                    provider=args.provider,
                    base_url=args.base_url or "",
                    api_key=args.api_key or "",
                    model=args.model,
                    timeout=args.timeout if args.timeout is not None else 120.0,
                )
            else:
                raise ValueError("请提供 JSON 参数，或使用 --provider --model [--base-url --api-key]")
            config_path, was_update = env_config.add_model_server(server, env_path=env_path)
        except ValueError as exc:
            print(f"[config] {exc}")
            return 1
        action = "已更新" if was_update else "已添加"
        print(f"[config] {action} {server.provider} → {config_path}")
        print(f"[config] 当前顺序: {'→'.join(s.provider for s in env_config.read_model_servers(env_path))}")
        print("[config] 重新打开终端或重启 LA 进程后生效")
        return 0

    if args.config_cmd == "init":
        try:
            result = env_config.init_model_servers_config(
                env_path=env_path,
                force=getattr(args, "force", False),
            )
        except FileNotFoundError as exc:
            print(f"[config] {exc}")
            return 1
        _print_config_ensure_result(result)
        return 0

    if args.config_cmd == "remove":
        try:
            config_path, existed = env_config.remove_model_server(args.provider, env_path=env_path)
        except ValueError as exc:
            print(f"[config] {exc}")
            return 1
        if existed:
            print(f"[config] 已删除 {args.provider} → {config_path}")
        else:
            print(f"[config] 未找到 provider {args.provider!r}")
            return 1
        print(f"[config] 当前顺序: {'→'.join(s.provider for s in env_config.read_model_servers(env_path))}")
        print("[config] 重新打开终端或重启 LA 进程后生效")
        return 0

    if args.config_cmd == "set-key":
        try:
            value = args.value
            if value in (None, "-"):
                value = env_config.read_key_from_stdin()
            if args.provider in env_config.STANDALONE_KEYS:
                dotenv_path, _ = env_config.set_standalone_key(args.provider, value, path=env_path)
                env_var = env_config.STANDALONE_KEYS[args.provider]
                print(f"[config] 已更新 {args.provider} ({env_var}) → {dotenv_path}")
            else:
                config_path, _ = env_config.set_server_api_key(args.provider, value, env_path=env_path)
                print(f"[config] 已更新 {args.provider} api_key → {config_path}")
            print(f"[config] key={env_config.mask_secret(value.strip())}")
        except ValueError as exc:
            print(f"[config] {exc}")
            return 1
        print("[config] 重新打开终端或重启 LA 进程后生效")
        return 0

    print("[config] 未知子命令")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="LA",
        description="LocalAgent — 本地 AI 个人助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "直接运行 LA（无子命令）等价于 LA chat，进入对话模式。\n"
            "进入对话后可用 /<command> 执行相同命令（输入 /help；: 为兼容别名）。\n"
            "使用 LA <command> -h 查看某个命令的完整说明。"
        ),
    )
    sub = parser.add_subparsers(
        dest="cmd",
        required=False,
        metavar="<command>",
        title="命令",
        description="主要参数与选项（括号内为可选）；省略时默认 chat：",
    )

    p_chat = sub.add_parser(
        "chat",
        help=f"[--session-id ID] [-p auto|{'|'.join(config.VALID_PROVIDERS)}]  交互式对话",
        description="启动交互式对话 REPL",
    )
    p_chat.add_argument("--session-id", help="恢复指定对话档案 id")
    p_chat.add_argument(
        "--provider",
        "-p",
        default="auto",
        help=f"模型路径: auto（默认）, {', '.join(config.VALID_PROVIDERS)}",
    )
    p_chat.add_argument(
        "--cwd",
        help="工作区根目录（等同 LA_WORKSPACE，用于 git/文件/todo 上下文）",
    )
    p_chat.set_defaults(func=cmd_chat)

    p_add = sub.add_parser("add", help="<text>  直接写入一条记忆", description="直接写入记忆")
    p_add.add_argument("text", help="记忆文本")
    p_add.set_defaults(func=cmd_add)

    p_add_file = sub.add_parser(
        "add-file",
        help="[-b] <path>  软链到 kb/ 并索引",
        description="将文件软链到 kb/ 并建立索引",
    )
    p_add_file.add_argument("path", help="源文件路径")
    p_add_file.add_argument(
        "--background",
        "-b",
        action="store_true",
        help="创建软链后在后台索引",
    )
    p_add_file.set_defaults(func=cmd_add_file)

    p_tasks = sub.add_parser(
        "tasks",
        help=(
            "[--limit N] [--tail N] "
            "[list | <task_id> | delete|pause|resume|restart|logs <task_id>]  "
            "查看/管理后台索引任务"
        ),
        description="查看和管理后台索引任务",
    )
    p_tasks.add_argument(
        "positional",
        nargs="*",
        metavar="[action] [task_id]",
        help="list | <task_id> | <action> <task_id>（delete/pause/resume/restart/logs）",
    )
    p_tasks.add_argument("--limit", type=int, default=10, help="最近任务显示条数（默认 10）")
    p_tasks.add_argument("--tail", type=int, default=50, help="logs 操作输出的行数（默认 50）")
    p_tasks.set_defaults(func=cmd_tasks)

    p_sync = sub.add_parser(
        "sync-file",
        help="[--force]  扫描并索引 data/kb/ 下全部文档",
        description="扫描并索引 data/kb/ 下全部文档",
    )
    p_sync.add_argument("--force", action="store_true", help="强制重新索引全部文件")
    p_sync.set_defaults(func=cmd_sync_file)

    p_reset = sub.add_parser(
        "reset-memory",
        help="[--keep-knowledge]  清空记忆与 sync_index",
        description="清空记忆与 sync_index",
    )
    p_reset.add_argument("--keep-knowledge", action="store_true", help="保留知识库索引")
    p_reset.set_defaults(func=cmd_reset_memory)

    p_mem_status = sub.add_parser(
        "memory-status",
        help="诊断 Warm 层记忆后端（Hindsight / JSON）",
        description="显示当前记忆引擎、Python 版本、Hindsight 安装状态与记忆条数",
    )
    p_mem_status.set_defaults(func=cmd_memory_status)

    sub.add_parser(
        "rebuild-memory",
        help="清空记忆后强制重建 kb/ 索引",
        description="清空记忆后执行 sync-file --force",
    ).set_defaults(func=cmd_rebuild_memory)

    p_forget = sub.add_parser(
        "forget",
        help="<id> [--yes]  删除一条记忆",
        description="删除一条记忆（先用 LA search 查看 id）",
    )
    p_forget.add_argument("id", help="记忆 id（支持前缀匹配）")
    p_forget.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    p_forget.set_defaults(func=cmd_forget)

    p_remem = sub.add_parser(
        "rememorize-chat",
        help="[--session ID] [--interactive]  从对话档案重新提取记忆",
        description="从对话档案重新提取记忆",
    )
    p_remem.add_argument("--session", dest="session", help="指定 session id")
    p_remem.add_argument(
        "--interactive",
        action="store_true",
        help="逐条确认是否保存（默认自动保存）",
    )
    p_remem.set_defaults(func=cmd_rememorize_chat)

    p_import = sub.add_parser(
        "import-chatgpt",
        help="[path] [--file PATH ...] [--dir DIR] [--force]  导入 ChatGPT 导出",
        description=(
            "导入 ChatGPT 数据导出并写入本地记忆。"
            "支持 conversations.json（从对话提取）与 memory.json（已保存记忆，1:1 导入）。"
            "默认跳过已导入内容；加 --force 可强制重新加载指定文件内的记忆。"
        ),
    )
    p_import.add_argument("path", nargs="?", help="导出 JSON 文件（conversations.json 或 memory.json）")
    p_import.add_argument(
        "--file",
        dest="files",
        nargs="+",
        metavar="PATH",
        help="指定一个或多个导出 JSON 文件（可与 --force 联用强制重载）",
    )
    p_import.add_argument(
        "--dir",
        dest="directory",
        help="批量导入目录下全部 *.json（默认 data/chatGPTdata/）",
    )
    p_import.add_argument("--force", action="store_true", help="强制重新导入已处理过的对话/记忆")
    p_import.add_argument(
        "--include-disabled",
        action="store_true",
        help="同时导入 ChatGPT 中已关闭（enabled=false）的记忆",
    )
    p_import.add_argument(
        "--interactive",
        action="store_true",
        help="逐条确认是否保存（默认自动保存）",
    )
    p_import.set_defaults(func=cmd_import_chatgpt)

    p_search = sub.add_parser(
        "search",
        help="<query> [--knowledge] [--top-k N] [--verbose]  搜索记忆或知识库",
        description="搜索记忆或知识库",
    )
    p_search.add_argument("query", help="搜索关键词")
    p_search.add_argument("--knowledge", action="store_true", help="搜索知识库原文")
    p_search.add_argument("--top-k", type=int, default=5, help="返回条数（默认 5）")
    p_search.add_argument("--verbose", action="store_true", help="显示记忆锚点等详情")
    p_search.set_defaults(func=cmd_search)

    p_reflect = sub.add_parser(
        "reflect",
        help="<query>  跨记忆推理（Hindsight reflect）",
        description="对多条记忆进行推理综合，处理矛盾、歧义或需要归纳的问题",
    )
    p_reflect.add_argument("query", help="需要推理的问题")
    p_reflect.set_defaults(func=cmd_reflect)

    p_memories = sub.add_parser(
        "memories",
        help="[query] [--tag TAG] [--since DATE] [--sort newest|oldest|relevance]  浏览/查询记忆",
        description="浏览或查询记忆库：标签过滤、时间范围、排序、语义匹配",
    )
    p_memories.add_argument("query", nargs="?", default="", help="可选，语义搜索关键词")
    p_memories.add_argument(
        "--tag",
        action="append",
        dest="tag",
        metavar="TAG",
        help="按标签过滤（可多次指定）",
    )
    p_memories.add_argument("--since", help="起始日期，如 2024-01-01")
    p_memories.add_argument("--until", help="结束日期，如 2024-12-31")
    p_memories.add_argument(
        "--sort",
        choices=("newest", "oldest", "relevance"),
        default="newest",
        help="排序方式（默认 newest；有 query 时可用 relevance）",
    )
    p_memories.add_argument("--limit", type=int, default=20, help="返回条数（默认 20）")
    p_memories.add_argument("--verbose", action="store_true", help="显示评分细节")
    p_memories.add_argument("--json", action="store_true", help="以 JSON 输出")
    p_memories.add_argument(
        "--list-tags",
        action="store_true",
        help="列出所有记忆标签及数量",
    )
    p_memories.set_defaults(func=cmd_memories)

    p_workspace = sub.add_parser(
        "workspace",
        help="[--days N] [--cwd PATH] [--todos-only]  工作区/git/待办快照",
        description="查看工作区最近变更、Git 状态与待办项",
    )
    p_workspace.add_argument("--days", type=int, default=7, help="最近 N 天内的文件变更（默认 7）")
    p_workspace.add_argument("--cwd", help="工作区根目录")
    p_workspace.add_argument("--todos-only", action="store_true", help="仅列出待办项")
    p_workspace.add_argument("--limit", type=int, default=80, help="待办扫描上限（默认 80）")
    p_workspace.set_defaults(func=cmd_workspace)

    p_audit = sub.add_parser(
        "audit",
        help="[--since 7d] [--report PATH] [--cwd PATH]  审计摘要与报告",
        description="Token/费用、文件安全、记忆健康审计",
    )
    p_audit.add_argument("--since", help="统计起始，如 7d、24h、30m")
    p_audit.add_argument("--report", help="导出 Markdown 报告到指定路径")
    p_audit.add_argument("--days", type=int, default=7, help="报告中工作区快照天数（默认 7）")
    p_audit.add_argument("--cwd", help="工作区根目录")
    p_audit.set_defaults(func=cmd_audit)

    p_config = sub.add_parser(
        "config",
        help="[--provider …] | <file.json> | init|list|add|remove|set-key  快速配置 / 管理模型",
        description=(
            "快速写入模型与 API Key。\n"
            "  la config --provider ollama --base_url http://localhost:11434 --model qwen3.5:4b\n"
            "  la config --TAVILY_API_KEY tvly-...\n"
            "  la config my.json\n"
            "  la config-example\n"
            "亦支持 init / list / add / remove / set-key 子命令。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    def _add_simple_config_flags(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--provider", help="模型路径，如 ollama / openrouter / cursor")
        parser.add_argument(
            "--base_url",
            "--base-url",
            dest="base_url",
            help="API base URL",
        )
        parser.add_argument("--model", help="模型名称，如 qwen3.5:4b")
        parser.add_argument(
            "--api_key",
            "--api-key",
            dest="api_key",
            help="该 provider 的 API Key",
        )
        parser.add_argument("--timeout", type=float, help="请求超时秒数")
        parser.add_argument(
            "--TAVILY_API_KEY",
            "--tavily-api-key",
            dest="tavily_api_key",
            help="Tavily 联网搜索 Key（可为空字符串）",
        )
        parser.add_argument(
            "--OPENROUTER_API_KEY",
            "--openrouter-api-key",
            dest="openrouter_api_key",
            help="OpenRouter API Key",
        )
        parser.add_argument(
            "--CURSOR_API_KEY",
            "--cursor-api-key",
            dest="cursor_api_key",
            help="Cursor API Key",
        )
        parser.add_argument(
            "--MINIMAX_API_KEY",
            "--minimax-api-key",
            dest="minimax_api_key",
            help="MiniMax API Key",
        )

    _add_simple_config_flags(p_config)
    config_sub = p_config.add_subparsers(
        dest="config_cmd",
        required=False,
        metavar="<action>",
        title="操作",
    )
    p_config_init = config_sub.add_parser(
        "init",
        help="初始化或重新加载 config/model_servers.yaml",
    )
    p_config_init.add_argument("--force", action="store_true", help="用模板覆盖已有配置文件")
    p_config_init.set_defaults(func=cmd_config)
    p_config_list = config_sub.add_parser("list", help="列出模型服务与独立 Key（脱敏）")
    p_config_list.set_defaults(func=cmd_config)

    p_config_set = config_sub.add_parser(
        "set",
        help="极简写入：--provider / --base_url / --model / --TAVILY_API_KEY …",
    )
    _add_simple_config_flags(p_config_set)
    p_config_set.set_defaults(func=cmd_config)

    p_config_apply = config_sub.add_parser(
        "apply",
        help="<file.json>  从 JSON 文件加载配置",
    )
    p_config_apply.add_argument("config_file", help="JSON 配置文件路径")
    p_config_apply.set_defaults(func=cmd_config)

    p_config_add = config_sub.add_parser(
        "add",
        help="添加/更新一条模型服务（JSON 或 --provider 参数）",
    )
    p_config_add.add_argument("json", nargs="?", help='JSON 对象，如 \'{"provider":"aiping",...}\'')
    p_config_add.add_argument("--provider", help="provider 名称（与 --model 等配合使用）")
    p_config_add.add_argument("--base-url", dest="base_url", help="OpenAI 兼容 API base URL")
    p_config_add.add_argument("--api-key", dest="api_key", help="API Key")
    p_config_add.add_argument("--model", help="模型名称")
    p_config_add.add_argument("--timeout", type=float, help="请求超时秒数（默认 120）")
    p_config_add.set_defaults(func=cmd_config)

    p_config_remove = config_sub.add_parser("remove", help="<provider>  从列表删除一条模型服务")
    p_config_remove.add_argument("provider", help="provider 名称，如 minimax / aiping")
    p_config_remove.set_defaults(func=cmd_config)

    p_config_set_key = config_sub.add_parser(
        "set-key",
        help="<provider> [key]  仅更新 api_key（key 省略或 - 时从 stdin 读取）",
    )
    p_config_set_key.add_argument(
        "provider",
        help="LA_MODEL_SERVERS 中的 provider，或 tavily / hindsight",
    )
    p_config_set_key.add_argument(
        "value",
        nargs="?",
        help="API Key；省略或传 - 时从 stdin 读取",
    )
    p_config_set_key.set_defaults(func=cmd_config)
    p_config.set_defaults(func=cmd_config)

    p_config_example = sub.add_parser(
        "config-example",
        help="打印 config.example.json（复制后改写再用 la config <file>）",
        description="输出极简配置模板 JSON",
    )
    p_config_example.set_defaults(func=cmd_config_example)

    p_setup = sub.add_parser(
        "setup",
        help="[--yes]  询问后安装 Ollama 并拉取 qwen3.5:4b（可跳过）",
        description=(
            "检查本机 Ollama；未安装时询问是否本地安装，"
            "缺少默认模型时询问是否拉取。加 -y 跳过确认。"
        ),
    )
    p_setup.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="无需确认，直接安装/拉取",
    )
    p_setup.set_defaults(func=cmd_setup)

    return parser


_CONFIG_SUBCOMMANDS = frozenset(
    {"init", "list", "add", "remove", "set-key", "set", "apply", "-h", "--help"}
)


def _normalize_config_argv(argv: list[str]) -> list[str]:
    """Rewrite ``la config <file.json>`` / ``la config --flags`` into subcommands."""
    if not argv or argv[0] != "config" or len(argv) < 2:
        return argv
    second = argv[1]
    if second in _CONFIG_SUBCOMMANDS:
        return argv
    if second.startswith("-"):
        return ["config", "set", *argv[1:]]
    # Treat as JSON config file path
    return ["config", "apply", second, *argv[2:]]



def _dispatch_complete(argv: list[str]) -> int | None:
    if not argv:
        return None
    if argv[0] == "complete":
        from localagent.completion import run_complete

        return run_complete(argv[1:])
    if argv[0] == "complete-init":
        from localagent.completion import run_complete_init

        return run_complete_init(argv[1:])
    if argv[0] == "complete-install":
        from localagent.completion import bash_completion_script, zsh_completion_script

        shell = (argv[1] if len(argv) > 1 else "zsh").lower()
        if shell in ("zsh", "bash"):
            print(zsh_completion_script() if shell == "zsh" else bash_completion_script())
            return 0
        print(f"[complete-install] 未知 shell: {shell}（可用: zsh, bash）")
        return 1
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    complete_rc = _dispatch_complete(argv)
    if complete_rc is not None:
        return complete_rc

    # LA ≡ LA chat：无子命令时进入对话模式
    if not argv:
        argv = ["chat"]

    argv = _normalize_config_argv(argv)

    from localagent import env_config
    from localagent.session_commands import dispatch_cli_argv

    env_config.ensure_config()
    config.ensure_data_dirs()
    get_task_store().reconcile_stale()
    try:
        return dispatch_cli_argv(argv, allow_chat=True)
    except KeyboardInterrupt:
        from localagent.models.router import shutdown_cursor_sdk

        shutdown_cursor_sdk()
        print("\n[LA] 已中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
