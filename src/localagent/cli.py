"""LA CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from localagent import config
from localagent.chat_repl import run_chat
from localagent.ingest.add_file import add_file, add_file_background, restart_background_task
from localagent.ingest.sync_file import sync_files
from localagent.ingest.progress import ConsoleProgressReporter
from localagent.ingest.tasks import TaskStatus, format_task_line, get_task_store
from localagent.memory.chatgpt_import import import_chatgpt_dir, import_chatgpt_file
from localagent.memory.hindsight_client import get_memory_backend
from localagent.memory.rememorize import rememorize_chat
from localagent.memory.reset import rebuild_memory, reset_memory
from localagent.memory.scoped_recall import scoped_recall
from localagent.memory.store import get_memory_store
from localagent.tools import search_knowledge, search_memory
from localagent.ui.console import emit


def _print_ingest_result(result) -> None:
    if result.status.value == "failed":
        print(f"  ! {result.filename}: {result.error}")
        return
    print(
        f"  {result.tag} {result.filename}: "
        f"facts={result.memory_fact_count}, chunks={result.knowledge_chunk_count}"
    )


def cmd_chat(args: argparse.Namespace) -> int:
    try:
        provider = config.normalize_provider_choice(args.provider)
    except ValueError as exc:
        print(f"[chat] {exc}")
        return 1
    if args.cwd:
        _apply_workspace_cwd(args.cwd)
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
    interactive = True if args.interactive else None
    if args.directory:
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
            print("[import-chatgpt] 请指定导出文件路径，或使用 --dir")
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
        hits = scoped_recall(args.query, max_results=args.top_k)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="LA",
        description="LocalAgent — 本地 AI 个人助手",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="使用 LA <command> -h 查看某个命令的完整说明。",
    )
    sub = parser.add_subparsers(
        dest="cmd",
        required=True,
        metavar="<command>",
        title="命令",
        description="主要参数与选项（括号内为可选）：",
    )

    p_chat = sub.add_parser(
        "chat",
        help="[--session-id ID] [-p auto|ollama|openrouter|cursor]  交互式对话",
        description="启动交互式对话 REPL",
    )
    p_chat.add_argument("--session-id", help="恢复指定对话档案 id")
    p_chat.add_argument(
        "--provider",
        "-p",
        default="auto",
        help="模型路径: auto（默认）, ollama, openrouter, cursor",
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
        help="[path] [--dir DIR] [--force] [--interactive]  导入 ChatGPT 导出",
        description=(
            "导入 ChatGPT 数据导出并写入本地记忆。"
            "支持 conversations.json（从对话提取）与 memory.json（已保存记忆，1:1 导入）。"
        ),
    )
    p_import.add_argument("path", nargs="?", help="导出 JSON 文件（conversations.json 或 memory.json）")
    p_import.add_argument(
        "--dir",
        dest="directory",
        help="批量导入目录下全部 *.json（默认 data/chatGPTdata/）",
    )
    p_import.add_argument("--force", action="store_true", help="重新导入已处理过的对话/记忆")
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

    return parser


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

    config.ensure_data_dirs()
    get_task_store().reconcile_stale()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n[LA] 已中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
