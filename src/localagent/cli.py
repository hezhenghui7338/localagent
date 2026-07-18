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
from localagent.memory.backend import describe_memory_backend, get_memory_backend
from localagent.memory.query import list_memory_tags, query_memories
from localagent.memory.rememorize import ingest_chat
from localagent.memory.reset import (
    rebuild_knowledge,
    reindex_memory_engine,
    reset_knowledge,
    reset_memory,
)
from localagent.memory.store import get_memory_store
from localagent.tools import (
    query_memories_tool,
    reflect_memory,
    search_knowledge,
    search_memory,
    web_search,
)
from localagent.ui.console import emit


def _cmd_news(args: argparse.Namespace) -> int:
    from localagent.news.commands import cmd_news

    return cmd_news(args)


def _print_ingest_result(result) -> None:
    if result.status.value == "failed":
        print(f"  ! {result.filename}: {result.error}")
        return
    print(
        f"  {result.tag} {result.filename}: "
        f"chunks={result.knowledge_chunk_count}"
    )


def _ensure_ollama_for_chat() -> None:
    """Offer optional Ollama install/pull before entering chat (user can decline)."""
    from localagent.ollama_setup import ensure_ollama_ready

    result = ensure_ollama_ready(prompt=True)
    if result.declined or result.skipped:
        if result.message:
            print(f"[setup] {result.message}")
        return
    if result.installed_now or result.pulled_now or result.adopted_existing:
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
    from localagent.memory.save import save_facts

    emit("memory add", "写入记忆…")
    ids = save_facts(
        [args.text],
        metadata={
            "source": "manual_add",
            "source_file": "LA memory add",
            "section_heading": "",
        },
    )
    if not ids:
        print("[memory add] 内容太短或无价值，未写入")
        return 1
    fact_id = ids[0]
    print(f"[memory add] 已写入记忆 (id={fact_id[:8]}...)")
    fact = get_memory_store().get(fact_id)
    if fact:
        title = fact.metadata.get("title") or fact.text[:30]
        tags = fact.metadata.get("tags") or []
        tag_hint = f" · {'/'.join(tags)}" if tags else ""
        print(f"      「{title}」{tag_hint}")
    return 0


def cmd_memory_pending(args: argparse.Namespace) -> int:
    from localagent.pending import list_pending, pending_count

    limit = getattr(args, "limit", None)
    items = list_pending(limit=limit)
    total = pending_count()
    if not items:
        print("[memory pending] 队列为空")
        return 0
    print(f"[memory pending] {len(items)}/{total} 条待确认：")
    for item in items:
        src = (item.metadata or {}).get("source", "")
        src_hint = f" · {src}" if src else ""
        print(f"  {item.id}  {item.text[:80]}{src_hint}")
    if limit is not None and total > len(items):
        print(f"  … 另有 {total - len(items)} 条，去掉 --limit 查看全部")
    print("  批准: LA memory approve <id>|--all")
    print("  拒绝: LA memory reject <id>|--all")
    return 0


def cmd_memory_approve(args: argparse.Namespace) -> int:
    from localagent.pending import approve_all, approve_ids, pending_count

    if getattr(args, "all", False):
        warm_ids = approve_all()
    else:
        ids = list(getattr(args, "ids", None) or [])
        if not ids:
            print("[memory approve] 请指定 id 或 --all")
            return 2
        warm_ids = approve_ids(ids)
    print(f"[memory approve] 已写入 Warm {len(warm_ids)} 条；剩余待确认 {pending_count()}")
    return 0 if warm_ids or getattr(args, "all", False) else 1


def cmd_memory_reject(args: argparse.Namespace) -> int:
    from localagent.pending import pending_count, reject_all, reject_ids

    if getattr(args, "all", False):
        n = reject_all()
    else:
        ids = list(getattr(args, "ids", None) or [])
        if not ids:
            print("[memory reject] 请指定 id 或 --all")
            return 2
        n = reject_ids(ids)
    print(f"[memory reject] 已丢弃 {n} 条；剩余待确认 {pending_count()}")
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


def cmd_summarize(args: argparse.Namespace) -> int:
    """Summarize file(s): default enters document dialogue; --no-chat is atomic only."""
    from localagent.summarize.document import (
        KEEP_HINT,
        DocumentTooLongError,
        SummarizeError,
        summarize_path,
    )
    from localagent.summarize.repl import (
        rebuild_result_from_disk,
        run_document_chat,
        should_enter_document_chat,
    )
    from localagent.summarize.sessions import (
        find_session_by_path,
        get_session,
        list_sessions,
        new_summarize_session_id,
    )

    prefix = "summarize"

    if getattr(args, "list", False):
        rows = list_sessions(limit=int(getattr(args, "limit", 20) or 20))
        if not rows:
            print(f"[{prefix}] 暂无文档对话会话")
            return 0
        print(f"{'id':<14} {'updated':<22} {'kept':<5} file")
        for row in rows:
            kept = "yes" if row.kept else "no"
            print(f"{row.id:<14} {row.updated_at:<22} {kept:<5} {row.filename}")
        print(f"[{prefix}] 续聊: la summarize <path> --resume  或  la summarize --id <id>")
        return 0

    resume_id = (getattr(args, "id", None) or "").strip()
    paths_raw = list(getattr(args, "paths", None) or [])
    if getattr(args, "path", None) and not paths_raw:
        # back-compat if parser still exposes singular path
        paths_raw = [args.path]

    no_chat = bool(getattr(args, "no_chat", False))
    do_resume = bool(getattr(args, "resume", False)) or bool(resume_id)
    heuristic = bool(getattr(args, "heuristic", False))
    keep = bool(getattr(args, "keep", False))
    provider = getattr(args, "provider", None) or "auto"
    out_path = getattr(args, "out", None)

    # Resume by session id
    if resume_id:
        record = get_session(resume_id)
        if record is None:
            print(f"[{prefix}] error: 未找到会话 {resume_id}")
            return 1
        source = Path(record.path)
        if not source.is_file():
            print(f"[{prefix}] error: 会话文件不存在: {source}")
            return 1
        return _summarize_resume_one(
            source,
            record=record,
            prefix=prefix,
            provider=provider,
            heuristic=heuristic,
            keep=keep,
        )

    if not paths_raw:
        print(f"[{prefix}] error: 请指定文件路径，或使用 --list / --id")
        return 1

    paths = [Path(p).expanduser().resolve() for p in paths_raw]
    if len(paths) > 1 and not no_chat:
        print(f"[{prefix}] error: 多文件仅支持仅速读模式，请加 --no-chat")
        return 1

    if do_resume and len(paths) == 1 and not no_chat:
        record = find_session_by_path(paths[0])
        if record is None:
            print(f"[{prefix}] 无既有会话，将新建文档对话")
        else:
            return _summarize_resume_one(
                paths[0],
                record=record,
                prefix=prefix,
                provider=provider,
                heuristic=heuristic,
                keep=keep,
            )

    results_md: list[str] = []
    failures = 0
    last_result = None
    for source in paths:
        print(f"[{prefix}] 文件: {source}")
        try:
            result = summarize_path(source, keep=keep, use_llm=not heuristic)
        except KeyboardInterrupt:
            print(f"\n[{prefix}] 已中断")
            return 130
        except (DocumentTooLongError, SummarizeError) as exc:
            print(f"[{prefix}] error: {exc}")
            failures += 1
            continue
        except Exception as exc:
            print(f"[{prefix}] error: {exc}")
            failures += 1
            continue

        last_result = result
        block = result.markdown.rstrip()
        if len(paths) > 1:
            header = f"\n---\n# {result.filename}\n\n"
            print(header.rstrip())
            results_md.append(header + block)
        else:
            results_md.append(block)
        print()
        print(block)
        print()
        meta_bits = [f"{result.char_count} 字"]
        if result.page_count is not None:
            meta_bits.append(f"{result.page_count} 页")
        meta_bits.append("LLM" if result.used_llm else "启发式")
        print(f"[{prefix}] {' · '.join(meta_bits)}")
        if result.warnings:
            for warning in result.warnings:
                print(f"[{prefix}] 注意: {warning}")
        if result.kept:
            print(f"[{prefix}] 已收藏到知识库: {result.keep_target}")
        else:
            print(f"[{prefix}] 未收藏（默认）。{KEEP_HINT}")

    if out_path and results_md:
        out = Path(out_path).expanduser().resolve()
        out.write_text("\n\n".join(results_md).rstrip() + "\n", encoding="utf-8")
        print(f"[{prefix}] 已写入: {out}")

    if failures and not last_result:
        return 1

    if should_enter_document_chat(no_chat=no_chat) and last_result is not None and len(paths) == 1:
        sid = new_summarize_session_id()
        return run_document_chat(
            last_result,
            provider=provider,
            summarize_session_id=sid,
            conversation_session_id=sid,
        )

    return 1 if failures else 0


def _summarize_resume_one(
    source: Path,
    *,
    record,
    prefix: str,
    provider: str,
    heuristic: bool,
    keep: bool,
) -> int:
    from localagent.summarize.document import summarize_path
    from localagent.summarize.repl import (
        _history_from_conversation,
        rebuild_result_from_disk,
        run_document_chat,
    )
    from localagent.summarize.sessions import file_mtime

    current_mtime = file_mtime(source)
    history = _history_from_conversation(record.conversation_session_id)
    if abs(current_mtime - float(record.mtime or 0.0)) > 1e-6:
        print(f"[{prefix}] 文件已更新，重新生成速读卡…")
        result = summarize_path(source, keep=keep or record.kept, use_llm=not heuristic)
        if record.kept and not result.kept:
            result.kept = True
            result.keep_target = Path(record.keep_target) if record.keep_target else result.keep_target
    else:
        print(f"[{prefix}] 续聊会话 {record.id} · {record.filename}")
        result = rebuild_result_from_disk(
            source,
            summary_md=record.summary_md,
            kept=bool(record.kept) or keep,
            keep_target=record.keep_target,
            page_count=record.page_count,
            char_count=record.char_count,
        )
        if keep and not result.kept:
            from localagent.ingest.add_file import add_file

            target, _ = add_file(source)
            result.kept = True
            result.keep_target = target

    print()
    print(result.markdown.rstrip())
    print()
    if result.kept:
        print(f"[{prefix}] 已收藏到知识库: {result.keep_target}")
    else:
        print(f"[{prefix}] 未收藏（默认）。会话内输入 /keep 可收藏到知识库。")

    if not history:
        history = None
    return run_document_chat(
        result,
        provider=provider,
        summarize_session_id=record.id,
        conversation_session_id=record.conversation_session_id,
        history=history,
    )


def _resolve_polish_text(args: argparse.Namespace) -> str:
    """Resolve draft text from --file, positional args, or stdin."""
    import sys

    chunks: list[str] = []
    file_path = getattr(args, "file", None)
    if file_path:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"文件不存在: {path}")
        chunks.append(path.read_text(encoding="utf-8"))
    text_parts = getattr(args, "text", None) or []
    if text_parts:
        chunks.append(" ".join(str(p) for p in text_parts).strip())
    if not chunks and not sys.stdin.isatty():
        stdin_text = sys.stdin.read()
        if stdin_text.strip():
            chunks.append(stdin_text)
    return "\n\n".join(c.strip() for c in chunks if c and c.strip()).strip()


def cmd_polish(args: argparse.Namespace) -> int:
    """One-click scene-aware text polish; copies primary rewrite to clipboard by default."""
    from localagent.ui.console import ActivityIndicator
    from localagent.writing.polish import PolishError, apply_clipboard, polish_text
    from localagent.writing.scenes import SCENE_IDS, normalize_scene

    prefix = "polish"
    try:
        draft = _resolve_polish_text(args)
    except FileNotFoundError as exc:
        print(f"[{prefix}] error: {exc}")
        return 1
    if not draft:
        print(
            f"[{prefix}] 用法: la polish [--scene email|moments|resume|biz] "
            "[--tone …] [--no-copy] [--file path] <草稿>\n"
            "       echo \"草稿\" | la polish\n"
            "会话内: /polish <草稿>"
        )
        return 1

    scene_raw = getattr(args, "scene", None)
    if scene_raw:
        scene = normalize_scene(scene_raw)
        if scene is None:
            print(f"[{prefix}] error: 未知场景 {scene_raw!r}（可用: {', '.join(SCENE_IDS)}）")
            return 1
    else:
        scene = None
    tone = (getattr(args, "tone", None) or "").strip() or None
    want_copy = not bool(getattr(args, "no_copy", False))

    with ActivityIndicator(prefix, "识别场景并改写…") as activity:
        try:
            result = polish_text(
                draft,
                scene=scene,
                tone=tone,
                on_status=activity.update,
            )
        except KeyboardInterrupt:
            print(f"\n[{prefix}] 已中断")
            return 130
        except PolishError as exc:
            print(f"[{prefix}] error: {exc}")
            return 1
        except Exception as exc:
            print(f"[{prefix}] error: {exc}")
            return 1

    print()
    print(result.format_report())
    print()
    apply_clipboard(
        result,
        enabled=want_copy,
        interactive=want_copy and sys.stdin.isatty() and sys.stdout.isatty(),
    )
    return 0


def cmd_add_file(args: argparse.Namespace) -> int:
    source = Path(args.path).expanduser().resolve()
    prefix = "rag add"
    try:
        if args.background:
            print(f"[{prefix}] 源文件: {source} ({_format_file_size(source)})")
            target, task, pid = add_file_background(args.path)
            print(f"[{prefix}] 软链: {target}")
            print(f"[{prefix}] 后台任务 {task.id} (pid={pid})")
            if task.log_path:
                print(f"[{prefix}] 日志: {task.log_path}")
            print(f"→ LA tasks {task.id}       查看进度")
            print(f"→ LA tasks logs {task.id}  查看输出")
            return 0

        print(f"[{prefix}] 源文件: {source} ({_format_file_size(source)})")
        reporter = ConsoleProgressReporter(prefix=prefix)
        target, result = add_file(args.path, reporter=reporter)
    except KeyboardInterrupt:
        print(f"\n[{prefix}] 已中断")
        return 130
    except (FileNotFoundError, ValueError, FileExistsError) as exc:
        print(f"[{prefix}] error: {exc}")
        return 1

    print(f"[{prefix}] 软链: {target}")
    _print_ingest_result(result)
    if result.status.value == "failed":
        return 1
    print(f"[{prefix}] done（仅知识库，不提取记忆）")
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
            f"chunks={task.knowledge_chunk_count}"
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


def cmd_ingest_file(args: argparse.Namespace) -> int:
    emit("rag ingest", f"扫描 {config.KB_DIR}/ …")
    reporter = ConsoleProgressReporter(prefix="rag ingest")
    summary = sync_files(force=args.force, reporter=reporter)
    if not summary.results:
        print(f"[rag ingest] no supported files in {config.KB_DIR}/")
        return 0

    for result in summary.results:
        _print_ingest_result(result)

    print(f"[rag ingest] {summary.format_summary()}")
    return 1 if summary.failed_count else 0


def cmd_rag_search(args: argparse.Namespace) -> int:
    emit("rag search", f"检索知识库: {args.query}")
    print(search_knowledge(args.query, top_k=args.top_k))
    return 0


def cmd_rag_status(_args: argparse.Namespace) -> int:
    from localagent.audit.health import collect_memory_health
    from localagent.ingest.conversation_cold import count_chunks_by_origin
    from localagent.ingest.sync_index import get_sync_index
    from localagent.knowledge.indexer import get_knowledge_indexer

    sync = get_sync_index()
    indexer = get_knowledge_indexer()
    files = sync.all_filenames()
    by_origin = count_chunks_by_origin()
    print("[rag status] Cold 知识库")
    print(f"  kb 目录:     {config.KB_DIR}")
    print(f"  已索引文件:  {len(files)}")
    print(f"  知识块数:    {indexer.count()}")
    print(
        f"  来源分布:    kb={by_origin.get('kb', 0)}  "
        f"chat={by_origin.get('chat', 0)}  "
        f"chatgpt={by_origin.get('chatgpt', 0)}  "
        f"other={by_origin.get('other', 0)}"
    )
    print(f"  sync_index:  {config.SYNC_INDEX_FILE}")

    health = collect_memory_health()
    if health.missing_kb_files:
        print(f"  未索引文件:  {len(health.missing_kb_files)}（可 LA rag ingest）")
    if health.orphan_kb_entries:
        print(f"  孤儿索引:    {len(health.orphan_kb_entries)}（sync_index 有记录但 kb/ 无文件）")
    if health.failed_tasks:
        print(f"  失败任务:    {health.failed_tasks}（可 LA tasks 查看）")

    print("\n下一步:")
    print("  LA rag add <path>     软链到 kb/ 并索引")
    print("  LA rag search <q>     检索知识库（含对话归档）")
    print("  LA rag ingest         增量扫描 data/kb/")
    print("  LA rag rebuild        重建 kb/ + chat + chatgpt Cold")
    return 0


def _ingest_index_count(path: Path) -> int:
    """Count processed entries in a chat/chatgpt ingest progress index."""
    if not path.exists():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        processed = raw.get("processed", {})
        return len(processed) if isinstance(processed, dict) else 0
    except Exception:
        return 0


def _memory_source_counts() -> dict[str, int]:
    """Count Warm facts by SOURCE_GROUPS origin (chat / chatgpt / file / other)."""
    from localagent.memory.reset import SOURCE_GROUPS

    counts = {"chat": 0, "chatgpt": 0, "file": 0, "other": 0}
    source_to_group: dict[str, str] = {}
    for group, sources in SOURCE_GROUPS.items():
        for src in sources:
            source_to_group[src] = group

    for fact in get_memory_store().all_facts():
        meta = fact.metadata or {}
        src = str(meta.get("source") or "")
        group = source_to_group.get(src, "other")
        counts[group] = counts.get(group, 0) + 1
    return counts


def _core_profile_configured() -> bool:
    from localagent.memory.core_profile import load_core_profile

    profile = load_core_profile()
    return bool(
        profile.name.strip()
        or profile.current_status.strip()
        or profile.preferences
        or profile.life_anchors
    )


def cmd_rag_reset(args: argparse.Namespace) -> int:
    reporter = ConsoleProgressReporter(prefix="rag reset")
    stats = reset_knowledge(
        clear_knowledge=not getattr(args, "keep_index", False),
        reporter=reporter,
    )
    print("[rag reset] cleared:")
    print(f"  sync_index entries removed: {stats['sync_index_entries_removed']}")
    if stats["clear_knowledge"]:
        print(f"  knowledge chunks removed: {stats['knowledge_chunks_removed']}")
        print("  (includes conversation Cold chunks from chat / chatgpt)")
    print(f"  legacy ingest memories removed: {stats['memory_facts_removed']}")
    print("[rag reset] done (kb/ symlinks preserved)")
    return 0


def cmd_rag_rebuild(_args: argparse.Namespace) -> int:
    reporter = ConsoleProgressReporter(prefix="rag rebuild")
    reset_stats, summary = rebuild_knowledge(reporter=reporter)
    print("[rag rebuild] reset:")
    print(f"  sync_index entries removed: {reset_stats['sync_index_entries_removed']}")
    print(f"  knowledge chunks removed: {reset_stats['knowledge_chunks_removed']}")
    print(f"  legacy ingest memories removed: {reset_stats['memory_facts_removed']}")
    print(
        "[rag rebuild] conversation Cold: "
        f"chat={reset_stats.get('conversation_cold_chat', 0)} "
        f"chatgpt={reset_stats.get('conversation_cold_chatgpt', 0)} "
        f"chunks={reset_stats.get('conversation_cold_chunks', 0)}"
    )
    for result in summary.results:
        _print_ingest_result(result)
    print(f"[rag rebuild] {summary.format_summary()}")
    return 1 if summary.failed_count else 0


def cmd_reset_memory(args: argparse.Namespace) -> int:
    source = getattr(args, "source", "all") or "all"
    reporter = ConsoleProgressReporter(prefix="memory reset")
    try:
        stats = reset_memory(
            clear_knowledge=False,
            source=source,
            reporter=reporter,
        )
    except ValueError as exc:
        print(f"[memory reset] {exc}")
        return 1
    print(f"[memory reset] cleared ({stats['source']}):")
    print(f"  memory facts removed: {stats['memory_facts_removed']}")
    if stats.get("sync_index_entries_removed"):
        print(f"  sync_index entries removed: {stats['sync_index_entries_removed']}")
    print("[memory reset] done（知识库请用 LA rag reset；对话档案保留）")
    return 0


def cmd_reindex_memory(_args: argparse.Namespace) -> int:
    reporter = ConsoleProgressReporter(prefix="memory reindex")
    stats = reindex_memory_engine(reporter=reporter)
    print("[memory reindex] Warm 引擎重建:")
    print(f"  backend:    {stats['backend']}")
    print(f"  reindexed:  {stats['reindexed']}")
    if stats.get("skipped"):
        print("  skipped:    yes (非 mem0 后端)")
    return 0

def cmd_ingest_chat(args: argparse.Namespace) -> int:
    reporter = ConsoleProgressReporter(prefix="memory ingest chat")
    interactive = True if args.interactive else None
    ids = ingest_chat(
        session_id=args.session,
        force=args.force,
        reporter=reporter,
        interactive=interactive,
    )
    cold_chunks = 0
    try:
        raw = json.loads(config.CHAT_INGEST_INDEX_FILE.read_text(encoding="utf-8"))
        for entry in (raw.get("processed") or {}).values():
            if isinstance(entry, dict):
                cold_chunks += int(entry.get("cold_chunk_count") or 0)
    except Exception:
        pass
    if not ids:
        print(f"[memory ingest chat] 未提取到新记忆（cold_chunks≈{cold_chunks}）")
        return 0
    print(f"[memory ingest chat] 已保存 {len(ids)} 条记忆（cold_chunks≈{cold_chunks}）")
    return 0


def cmd_ingest_chatgpt(args: argparse.Namespace) -> int:
    reporter = ConsoleProgressReporter(prefix="memory ingest chatgpt")
    interactive = args.interactive
    if args.files and args.path:
        print("[memory ingest chatgpt] 不能同时指定 path 与 --file")
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
            emit("memory ingest chatgpt", f"使用默认目录 {default_dir}")
            summary = import_chatgpt_dir(
                default_dir,
                force=args.force,
                include_disabled=args.include_disabled,
                reporter=reporter,
                interactive=interactive,
            )
        else:
            print("[memory ingest chatgpt] 请指定导出文件路径，或使用 --file / --dir")
            print("  对话历史: conversations.json")
            print("  已保存记忆: memory.json / memories.json")
            return 1

    for err in summary.errors:
        print(f"[memory ingest chatgpt] ! {err}")

    print(f"[memory ingest chatgpt] {summary.format_summary()}")
    if summary.saved_count:
        print(f"→ 已写入 {summary.saved_count} 条记忆")
    elif summary.cold_chunks and summary.imported == 0 and not summary.errors:
        print(f"[memory ingest chatgpt] 未提取到新记忆，已写入 Cold {summary.cold_chunks} chunks")
    elif summary.imported == 0 and not summary.errors:
        print("[memory ingest chatgpt] 未提取到新的记忆")
    return 1 if summary.errors and summary.files_processed == 0 else 0


def cmd_memory_ingest(args: argparse.Namespace) -> int:
    source = (args.source or "").strip().lower()
    if source == "chat":
        return cmd_ingest_chat(args)
    if source == "chatgpt":
        return cmd_ingest_chatgpt(args)
    if source == "all":
        rc = cmd_ingest_chat(args)
        chatgpt_args = argparse.Namespace(
            path=None,
            files=None,
            directory=None,
            force=args.force,
            include_disabled=getattr(args, "include_disabled", False),
            interactive=getattr(args, "interactive", False),
        )
        default_dir = config.CHATGPT_DATA_DIR
        has_chatgpt = (
            getattr(args, "path", None)
            or getattr(args, "files", None)
            or getattr(args, "directory", None)
            or (default_dir.is_dir() and any(default_dir.glob("*.json")))
        )
        chatgpt_rc = 0
        if has_chatgpt:
            chatgpt_rc = cmd_ingest_chatgpt(chatgpt_args)
        print("[memory ingest all] 文档知识库请单独运行: LA rag ingest")
        return 1 if any(code != 0 for code in (rc, chatgpt_rc)) else 0
    print(f"[memory ingest] 未知来源: {args.source}（可用: chat, chatgpt, all）")
    return 1


def cmd_forget(args: argparse.Namespace) -> int:
    backend = get_memory_backend()
    fact = get_memory_store().get(args.id)
    if fact is None:
        print(f"[memory forget] 未找到记忆: {args.id}")
        return 1
    if not args.yes:
        preview = fact.text[:120] + ("…" if len(fact.text) > 120 else "")
        try:
            answer = input(f"删除记忆 {fact.id[:8]}… 「{preview}」？[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if answer not in ("y", "yes"):
            print("[memory forget] 已取消")
            return 0
    if backend.delete(fact.id):
        print(f"[memory forget] 已删除 {fact.id[:8]}…")
        return 0
    print(f"[memory forget] 删除失败: {fact.id}")
    return 1


def cmd_search(args: argparse.Namespace) -> int:
    emit("memory search", f"检索记忆: {args.query}")
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
        print("→ LA memory forget <id>  删除某条记忆")
    return 0


def cmd_memory_graph(args: argparse.Namespace) -> int:
    """Inspect or rebuild SQLite / Neo4j memory graphs; run precise queries."""
    from localagent import config
    from localagent.memory.graph import (
        format_precise_result,
        get_memory_graph,
        get_neo4j_store,
        neo4j_available,
        neo4j_enabled,
        precise_graph_query,
        rebuild_memory_graph,
        rebuild_neo4j_graph,
    )

    action = getattr(args, "graph_action", None) or "stats"
    graph_arg = getattr(args, "graph_arg", None)

    if action == "query":
        query = (graph_arg or "").strip()
        if not query:
            print("[memory graph query] 请提供问题，例如: LA memory graph query \"提到过几次 Caroline？\"")
            return 2
        if not neo4j_enabled():
            print("[memory graph query] Neo4j 未启用（LA_NEO4J=1）")
            return 1
        emit("memory graph query", query)
        result = precise_graph_query(query, fallback_hybrid=True)
        print(format_precise_result(result, verbose=True))
        return 0 if result.ok else 1

    if action == "neo4j":
        sub = (graph_arg or "stats").strip().lower()
        if sub == "rebuild":
            emit("memory graph neo4j rebuild", "从 memory_store.json 重建 Neo4j…")
            try:
                stats = rebuild_neo4j_graph()
            except Exception as exc:
                print(f"[memory graph neo4j] 重建失败: {exc}")
                return 1
            print(
                "[memory graph neo4j] 已重建: "
                f"entities={stats['entities']} relations={stats['relations']} "
                f"mentions={stats['mentions']} facts={stats['facts']}"
            )
            print(f"  URI: {config.NEO4J_URI}")
            return 0

        print("[memory graph neo4j] 精确图查询状态")
        print(f"  启用:       {'是' if neo4j_enabled() else '否'} (LA_NEO4J)")
        print(f"  URI:        {config.NEO4J_URI}")
        print(f"  可用:       {'是' if neo4j_available() else '否'}")
        print(f"  Text2Cypher:{'开' if config.NEO4J_TEXT2CYPHER else '关'} (默认关，用模板)")
        if neo4j_enabled() and neo4j_available():
            try:
                stats = get_neo4j_store().stats()
                print(f"  entities:   {stats['entities']}")
                print(f"  relations:  {stats['relations']}")
                print(f"  mentions:   {stats['mentions']}")
                print(f"  facts:      {stats['facts']}")
            except Exception as exc:
                print(f"  统计失败:   {exc}")
        else:
            print("\n提示: 精确计数/聚合需 LA_NEO4J=1，并 pip install 'la-localagent[neo4j]'")
            print("      无 Docker 时可设 LA_NEO4J_URI=memory:// 做本地内存图实验")
            print("      重建: LA memory graph neo4j rebuild")
            print("      查询: LA memory graph query \"提到过几次 X？\"")
        return 0

    if action == "rebuild":
        emit("memory graph rebuild", "从 memory_store.json 重建关系图…")
        stats = rebuild_memory_graph()
        print(
            "[memory graph] 已重建: "
            f"entities={stats['entities']} relations={stats['relations']} "
            f"mentions={stats['mentions']} facts={stats['facts']}"
        )
        print(f"  文件: {config.MEMORY_GRAPH_FILE}")
        if neo4j_enabled():
            print("  Neo4j: 已同步重建（见 LA memory graph neo4j stats）")
        return 0

    stats = get_memory_graph().stats()
    print("[memory graph] 本地关系图状态")
    print(f"  启用:       {'是' if config.MEMORY_GRAPH else '否'} (LA_MEMORY_GRAPH)")
    print(f"  hops:       {config.MEMORY_GRAPH_HOPS}")
    print(f"  boost:      {config.MEMORY_GRAPH_BOOST}")
    print(f"  entities:   {stats['entities']}")
    print(f"  relations:  {stats['relations']}")
    print(f"  mentions:   {stats['mentions']}")
    print(f"  facts:      {stats['facts']}")
    print(f"  文件:       {config.MEMORY_GRAPH_FILE}")
    print(f"  Neo4j:      {'开' if neo4j_enabled() else '关'} (LA_NEO4J；精确计数/聚合)")
    if not config.MEMORY_GRAPH:
        print("\n提示: 关系图默认关闭（日常靠 hybrid + cross-encoder）。")
        print("      实验多跳时可设 LA_MEMORY_GRAPH=1，再执行: LA memory graph rebuild")
        print("      精确问（多少次/列出所有）用 Neo4j: LA_NEO4J=1 + neo4j rebuild/query")
        print("      说明见 README「可选 Warm 关系图」；开图会增加召回延迟。")
    return 0


def cmd_memory_status(_args: argparse.Namespace) -> int:
    from localagent.persist.conversations import list_sessions

    info = describe_memory_backend()
    print("[memory status] Warm 层记忆引擎诊断")
    print(f"  当前后端:     {info['active_backend']} ({info.get('backend_class', '?')})")
    print(f"  配置偏好:     {info['preference']} (LA_MEMORY_BACKEND)")
    print(f"  Python:       {info['python_version']}")
    print(f"  Mem0:         {'已安装' if info.get('mem0_installed') else '未安装'}")
    if info.get("mem0_installed"):
        print(f"  Infer:        {'开启' if info.get('mem0_infer') else '关闭'} (LA_MEM0_INFER)")
        print(
            f"  LLM:          {info.get('mem0_llm_provider', '?')}/{info.get('mem0_llm_model', '?')}"
        )
        print(
            f"  Embedder:     {info.get('mem0_embedder_provider', '?')}/"
            f"{info.get('mem0_embedder_model', '?')} (dims={info.get('mem0_embedder_dims', '?')})"
        )
        print(
            f"  Retain 降级:  {'开启' if info.get('retain_json_fallback') else '关闭'} "
            "(LA_MEM0_RETAIN_JSON_FALLBACK)"
        )
        print(f"  Mem0 数据:    {info.get('mem0_dir', '?')}")
    print(f"  记忆条数:     {info['memory_count']}")
    if info.get("unindexed_count"):
        print(
            f"  未入向量:     {info['unindexed_count']} "
            "（JSON 有记录但未进 Mem0/Qdrant，可 LA memory reindex）"
        )

    sources = _memory_source_counts()
    print(
        f"  来源分布:     chat={sources['chat']}  chatgpt={sources['chatgpt']}  "
        f"file={sources['file']}  other={sources['other']}"
    )
    chat_sessions = len(list_sessions())
    chat_ingested = _ingest_index_count(config.CHAT_INGEST_INDEX_FILE)
    chatgpt_imported = _ingest_index_count(config.CHATGPT_IMPORT_INDEX_FILE)
    print(f"  LA 对话档案:  {chat_sessions} 个会话（已记忆化索引 {chat_ingested}）")
    print(f"  ChatGPT 导入: 已处理 {chatgpt_imported} 条")
    try:
        from localagent.ingest.conversation_cold import count_chunks_by_origin

        cold = count_chunks_by_origin()
        print(
            f"  Cold 对话块:  chat={cold.get('chat', 0)}  chatgpt={cold.get('chatgpt', 0)}  "
            f"(LA rag search 可召回)"
        )
    except Exception:
        pass
    print(f"  Hot 画像:     {'已配置' if _core_profile_configured() else '未配置'} ({config.CORE_PROFILE_FILE})")
    print(
        f"  关系图:       {'开启' if config.MEMORY_GRAPH else '关闭'} "
        f"(LA_MEMORY_GRAPH；LA memory graph stats)"
    )

    print(f"  Profile pin:  {'LLM' if info.get('profile_pin_llm') else '正则'} (LA_PROFILE_PIN_LLM)")
    print(f"  Bank ID:      {info['bank_id']}")
    print(f"  本地索引:     {info['store_file']}")
    if info.get("error"):
        print(f"  错误:         {info['error']}")
    if info["active_backend"] == "json" and info["preference"] != "json":
        print("\n提示: Mem0 初始化失败时会回退到 JSON。检查 Ollama 嵌入模型或 LA_MEM0_EMBEDDER_*。")
    if info.get("unindexed_count"):
        print("提示: 存在未入向量索引的记忆，语义召回可能不完整。")

    print("\n下一步:")
    print("  LA memory query              浏览最近记忆")
    print("  LA memory search <q>         语义搜索")
    print("  LA memory ingest chat|chatgpt  从对话提取记忆")
    return 0


def cmd_reflect(args: argparse.Namespace) -> int:
    emit("reflect", f"综合推理: {args.query}")
    print(reflect_memory(args.query))
    return 0


def cmd_websearch(args: argparse.Namespace) -> int:
    emit("websearch", f"联网搜索: {args.query}")
    print(web_search(args.query, max_results=args.top_k))
    return 0


def cmd_consolidate(args: argparse.Namespace) -> int:
    """Run ADD/UPDATE/DELETE consolidation over recent memories (background by default)."""
    limit = max(1, int(getattr(args, "limit", 40) or 40))
    if getattr(args, "foreground", False):
        emit("memory consolidate", f"巩固近期记忆 (limit={limit})…")
        from localagent.memory.consolidate import consolidate_recent

        report = consolidate_recent(limit=limit)
        print(
            f"[memory consolidate] changed={report.changed} "
            f"+{len(report.retained_ids)} ~{len(report.updated_ids)} "
            f"-{len(report.deleted_ids)} noop={report.noop_count}"
        )
        if report.errors:
            print(f"[memory consolidate] errors: {'; '.join(report.errors[:5])}")
        return 0

    from localagent.ingest.add_file import spawn_background_task
    from localagent.ingest.tasks import get_task_store

    task = get_task_store().create_consolidate(limit=limit)
    pid = spawn_background_task(task)
    print(f"[memory consolidate] 后台任务 {task.id} (pid={pid})")
    if task.log_path:
        print(f"[memory consolidate] 日志: {task.log_path}")
    print(f"→ LA tasks {task.id}       查看进度")
    print(f"→ LA tasks logs {task.id}  查看输出")
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

    emit("memory query", "查询记忆库…")
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
        print("→ LA memory forget <id>  删除某条记忆")
    return 0


def _apply_workspace_cwd(cwd: str | None) -> None:
    if not cwd:
        return
    import os

    os.environ["LA_WORKSPACE"] = str(Path(cwd).expanduser().resolve())


def cmd_status(_args: argparse.Namespace) -> int:
    """Daily Actions surface: news / pending / workspace todos."""
    from localagent.status.daily import format_daily_actions_report

    print(format_daily_actions_report())
    return 0


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


def cmd_logs(args: argparse.Namespace) -> int:
    """Show diagnostic application logs (data/logs/localagent.log)."""
    from localagent.logging_setup import app_log_path, read_app_log

    path = app_log_path()
    if args.path:
        print(path)
        return 0

    if not path.exists():
        print("[logs] 尚无日志；运行任意 LA 命令后生成。")
        print(f"[logs] 路径: {path}")
        return 0

    text = read_app_log(tail=args.tail, level_filter=args.level)
    if not text.strip():
        level_note = f"（级别 ≥ {args.level}）" if args.level else ""
        print(f"[logs] 无匹配日志行{level_note}")
        print(f"[logs] 路径: {path}")
        return 0

    print(text)
    return 0


def _extract_debug_flag(argv: list[str]) -> tuple[list[str], bool]:
    """Pull --debug from anywhere in argv so it works before/after subcommands."""
    debug = False
    out: list[str] = []
    for arg in argv:
        if arg == "--debug":
            debug = True
        else:
            out.append(arg)
    return out, debug


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
            "openai_api_key",
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
        "--OPENAI_API_KEY",
        "--openai-api-key",
        dest="openai_api_key",
        help="OpenAI API Key",
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
                openai_api_key=getattr(args, "openai_api_key", None),
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
    from localagent import __version__

    parser = argparse.ArgumentParser(
        prog="LA",
        description=(
            "LocalAgent — Local First. Memory Forever. Actions Automated.\n"
            "本地 AI：记得住你，也能把事办完。\n\n"
            "主路径（少即是多）：\n"
            "  la / la chat     对话\n"
            "  la setup [-y]    安装/拉取本地 Ollama 模型\n"
            "  la config …      纯本地或自有 API 配置\n"
            "  la status        今日待办信号（新闻 / pending / workspace）\n\n"
            "日常能力见 memory / rag / audit；运维与实验见 tasks / logs / graph 等。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  la                  # 进入对话（等同 la chat）\n"
            "  la setup -y         # 一键装好本地模型\n"
            "  la config list      # 查看配置\n"
            "  la memory pending   # 确认待写入记忆\n"
            "  la rag add notes.md # 文档进知识库\n"
            "  la summarize doc.md # 一键总结（默认不入库）\n"
            "  la news brief       # 今日新闻简报（先 la news sync）\n"
            "  la polish \"催进度草稿\"  # 一键润色（默认复制主推）\n"
            "\n"
            "进入对话后可用 /<command>（输入 /help；: 为兼容别名）。\n"
            "使用 LA <command> -h 查看某个命令的完整说明。"
        ),
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"la-localagent {__version__}",
        help="显示版本号并退出",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="启用 DEBUG 诊断日志（同时写入文件并输出到 stderr）",
    )
    sub = parser.add_subparsers(
        dest="cmd",
        required=False,
        metavar="<command>",
        title="命令",
        description=(
            "主路径：chat · setup · config；其余为高级能力（memory / rag / audit …）。"
            "省略子命令时默认 chat："
        ),
    )

    p_status = sub.add_parser(
        "status",
        help="今日待办信号（新闻 / pending / workspace）",
        description=(
            "Daily Actions 摘要：今日新闻是否已 sync、记忆 pending 条数、"
            "workspace 待办数量。对应产品支柱 Actions Automated。"
        ),
    )
    p_status.set_defaults(func=cmd_status)

    p_chat = sub.add_parser(
        "chat",
        help=f"[--session-id ID] [-p auto|{'|'.join(config.VALID_PROVIDERS)}]  【主路径】交互式对话",
        description="启动交互式对话 REPL（主路径）",
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

    p_tasks = sub.add_parser(
        "tasks",
        help=(
            "[高级] [--limit N] [--tail N] "
            "[list | <task_id> | delete|pause|resume|restart|logs <task_id>]  "
            "后台索引任务"
        ),
        description="[高级] 查看和管理后台索引任务",
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

    p_memory = sub.add_parser(
        "memory",
        help="[status]|add|ingest|query|search|…  无参显示概览；对话记忆写入/查询/运维",
        description=(
            "Warm 记忆（仅对话来源）。无子命令时显示 status 概览。\n"
            "  LA memory\n"
            "  LA memory add \"…\"\n"
            "  LA memory ingest chat|chatgpt|all [--force]\n"
            "  LA memory query / search / consolidate / forget / status / reset / reindex\n"
            "  LA memory reflect <query>（亦可用一级命令 LA reflect）\n"
            "  LA memory graph stats|rebuild|neo4j|query\n"
            "文档知识库请用: LA rag …"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mem_sub = p_memory.add_subparsers(
        dest="memory_cmd",
        required=False,
        metavar="<action>",
        title="操作",
    )
    p_memory.set_defaults(func=cmd_memory_status)

    p_mem_add = mem_sub.add_parser("add", help="<text>  直接写入一条记忆")
    p_mem_add.add_argument("text", help="记忆文本")
    p_mem_add.set_defaults(func=cmd_add)

    p_mem_pending = mem_sub.add_parser(
        "pending",
        help="[--limit N]  列出待确认的 Warm 记忆候选",
    )
    p_mem_pending.add_argument("--limit", type=int, default=None, help="最多显示条数")
    p_mem_pending.set_defaults(func=cmd_memory_pending)

    p_mem_approve = mem_sub.add_parser(
        "approve",
        help="<id…> | --all  批准待确认记忆并写入 Warm",
    )
    p_mem_approve.add_argument("ids", nargs="*", help="pending id（可多个）")
    p_mem_approve.add_argument("--all", action="store_true", help="批准全部")
    p_mem_approve.set_defaults(func=cmd_memory_approve)

    p_mem_reject = mem_sub.add_parser(
        "reject",
        help="<id…> | --all  拒绝待确认记忆（不写入 Warm）",
    )
    p_mem_reject.add_argument("ids", nargs="*", help="pending id（可多个）")
    p_mem_reject.add_argument("--all", action="store_true", help="拒绝全部")
    p_mem_reject.set_defaults(func=cmd_memory_reject)

    p_mem_forget = mem_sub.add_parser(
        "forget",
        help="<id> [--yes]  删除一条记忆",
        description="删除一条记忆（先用 LA memory search / query 查看 id）",
    )
    p_mem_forget.add_argument("id", help="记忆 id（支持前缀匹配）")
    p_mem_forget.add_argument("--yes", "-y", action="store_true", help="跳过确认")
    p_mem_forget.set_defaults(func=cmd_forget)

    p_mem_ingest = mem_sub.add_parser(
        "ingest",
        help="<chat|chatgpt|all> [--force]  从对话提取记忆",
        description=(
            "从 LA 对话档案或 ChatGPT 导出提取 Warm 记忆。"
            "文档请用 LA rag ingest。"
        ),
    )
    p_mem_ingest.add_argument(
        "source",
        choices=("chat", "chatgpt", "all"),
        help="材料来源：chat / chatgpt / all",
    )
    p_mem_ingest.add_argument("--force", action="store_true", help="强制重新消费已处理内容")
    p_mem_ingest.add_argument("--session", help="仅处理指定对话 session id（source=chat）")
    p_mem_ingest.add_argument(
        "--interactive",
        action="store_true",
        help="逐条确认是否保存（默认自动保存；chat/chatgpt）",
    )
    p_mem_ingest.add_argument(
        "path",
        nargs="?",
        help="ChatGPT 导出 JSON（source=chatgpt）",
    )
    p_mem_ingest.add_argument(
        "--file",
        dest="files",
        nargs="+",
        metavar="PATH",
        help="一个或多个 ChatGPT 导出 JSON（source=chatgpt）",
    )
    p_mem_ingest.add_argument(
        "--dir",
        dest="directory",
        help="批量导入目录下全部 *.json（默认 data/chatGPTdata/；source=chatgpt）",
    )
    p_mem_ingest.add_argument(
        "--include-disabled",
        action="store_true",
        help="同时导入 ChatGPT 中已关闭（enabled=false）的记忆",
    )
    p_mem_ingest.set_defaults(func=cmd_memory_ingest)

    p_mem_reset = mem_sub.add_parser(
        "reset",
        help="[chat|chatgpt|all]  按来源清空 Warm 记忆",
        description="按来源清空记忆；默认 all。知识库请用 LA rag reset。",
    )
    p_mem_reset.add_argument(
        "source",
        nargs="?",
        default="all",
        choices=("chat", "chatgpt", "all"),
        help="清空范围（默认 all）",
    )
    p_mem_reset.set_defaults(func=cmd_reset_memory)

    p_mem_status = mem_sub.add_parser(
        "status",
        help="诊断 Warm 层记忆后端（Mem0 / JSON）",
    )
    p_mem_status.set_defaults(func=cmd_memory_status)

    mem_sub.add_parser(
        "reindex",
        help="从 memory_store.json 重建 Mem0 向量索引（不删事实）",
        description="保留 JSON 注册表，清空并重建 Mem0 Warm 引擎索引",
    ).set_defaults(func=cmd_reindex_memory)

    p_mem_graph = mem_sub.add_parser(
        "graph",
        help="[stats|rebuild|neo4j|query]  记忆关系图 / 精确图查询",
        description=(
            "SQLite 召回 hop 图（LA_MEMORY_GRAPH）与 Neo4j 精确查询（LA_NEO4J）。"
            "stats/rebuild 管本地图；neo4j stats|rebuild 管 Neo4j；"
            "query 对计数/聚合/多跳跑 Cypher 模板。"
        ),
    )
    p_mem_graph.add_argument(
        "graph_action",
        nargs="?",
        default="stats",
        choices=("stats", "rebuild", "neo4j", "query"),
        help="stats|rebuild|neo4j|query（默认 stats）",
    )
    p_mem_graph.add_argument(
        "graph_arg",
        nargs="?",
        default=None,
        help="neo4j 时为 stats|rebuild；query 时为问题文本",
    )
    p_mem_graph.set_defaults(func=cmd_memory_graph)

    p_mem_search = mem_sub.add_parser(
        "search",
        help="<query> [--top-k N] [--verbose]  语义搜索 Warm 记忆",
    )
    p_mem_search.add_argument("query", help="搜索关键词")
    p_mem_search.add_argument("--top-k", type=int, default=5, help="返回条数（默认 5）")
    p_mem_search.add_argument("--verbose", action="store_true", help="显示记忆锚点等详情")
    p_mem_search.set_defaults(func=cmd_search)

    p_mem_consolidate = mem_sub.add_parser(
        "consolidate",
        help="巩固近期记忆（ADD/UPDATE/DELETE，默认后台）",
        description="扫描近期记忆，合并冲突/重复；默认后台任务，可用 la tasks 查看进度",
    )
    p_mem_consolidate.add_argument(
        "--limit",
        type=int,
        default=40,
        help="扫描最近 N 条记忆（默认 40）",
    )
    p_mem_consolidate.add_argument(
        "--foreground",
        "-f",
        action="store_true",
        help="前台同步执行（默认后台）",
    )
    p_mem_consolidate.set_defaults(func=cmd_consolidate)

    p_mem_query = mem_sub.add_parser(
        "query",
        help="[query] [--tag TAG] [--since DATE] [--sort …]  条件浏览/查询记忆",
        description="浏览或查询记忆库：标签过滤、时间范围、排序、语义匹配",
    )
    p_mem_query.add_argument("query", nargs="?", default="", help="可选，语义搜索关键词")
    p_mem_query.add_argument(
        "--tag",
        action="append",
        dest="tag",
        metavar="TAG",
        help="按标签过滤（可多次指定）",
    )
    p_mem_query.add_argument("--since", help="起始日期，如 2024-01-01")
    p_mem_query.add_argument("--until", help="结束日期，如 2024-12-31")
    p_mem_query.add_argument(
        "--sort",
        choices=("newest", "oldest", "relevance"),
        default="newest",
        help="排序方式（默认 newest；有 query 时可用 relevance）",
    )
    p_mem_query.add_argument("--limit", type=int, default=20, help="返回条数（默认 20）")
    p_mem_query.add_argument("--verbose", action="store_true", help="显示评分细节")
    p_mem_query.add_argument("--json", action="store_true", help="以 JSON 输出")
    p_mem_query.add_argument(
        "--list-tags",
        action="store_true",
        help="列出所有记忆标签及数量",
    )
    p_mem_query.set_defaults(func=cmd_memories)

    p_mem_reflect = mem_sub.add_parser(
        "reflect",
        help="[高级] <query>  综合推理（记忆 → 知识库 → 归纳）",
        description=(
            "[高级] 先多跳召回长期记忆，再检索知识库，最后综合推理。\n"
            "  LA memory reflect \"我最近状态怎么样？\""
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_mem_reflect.add_argument("query", help="需要推理的问题")
    p_mem_reflect.set_defaults(func=cmd_reflect)

    p_reflect = sub.add_parser(
        "reflect",
        help="[高级] <query>  综合推理（兼容别名；推荐 LA memory reflect）",
        description=(
            "[高级] 先多跳召回长期记忆，再检索知识库，最后综合推理给出答案。\n"
            "  LA reflect \"我最近状态怎么样？\"\n"
            "  等价：LA memory reflect \"…\""
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_reflect.add_argument("query", help="需要推理的问题")
    p_reflect.set_defaults(func=cmd_reflect)

    p_websearch = sub.add_parser(
        "websearch",
        help="[高级] <query> [--top-k N]  联网搜索（亦可用会话内自动联网）",
        description=(
            "[高级] 直接联网检索并输出结果摘要与来源链接。\n"
            "默认后端 ddgs（免费）；可用 LA_WEB_SEARCH_PROVIDER / Tavily / SearXNG。\n"
            "多步深度研究请用会话内 /deepsearch。\n"
            "  LA websearch \"今天深圳天气\"\n"
            "  LA websearch \"最新 AI 进展\" --top-k 8"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_websearch.add_argument("query", help="联网搜索关键词")
    p_websearch.add_argument("--top-k", type=int, default=5, help="返回条数（默认 5）")
    p_websearch.set_defaults(func=cmd_websearch)

    p_rag = sub.add_parser(
        "rag",
        help="[status]|add|ingest|search|reset|rebuild  无参显示概览；文档知识库（Cold）",
        description=(
            "Cold 知识库：个人文档与图片（VL 文本化）仅用于 RAG 检索，不写入 Warm 记忆。"
            "支持 .md/.txt/.xlsx/.png/.jpg/.jpeg/.webp/.gif。\n"
            "无子命令时显示 status 概览。\n"
            "  LA rag\n"
            "  LA rag add [-b] <path>\n"
            "  LA rag ingest [--force]\n"
            "  LA rag search <query>\n"
            "  LA rag status | reset | rebuild"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    rag_sub = p_rag.add_subparsers(
        dest="rag_cmd",
        required=False,
        metavar="<action>",
        title="操作",
    )
    p_rag.set_defaults(func=cmd_rag_status)

    p_rag_add = rag_sub.add_parser(
        "add",
        help="[-b] <path>  软链到 kb/ 并索引（仅知识库）",
    )
    p_rag_add.add_argument("path", help="源文件路径")
    p_rag_add.add_argument(
        "--background",
        "-b",
        action="store_true",
        help="创建软链后在后台索引",
    )
    p_rag_add.set_defaults(func=cmd_add_file)

    p_rag_ingest = rag_sub.add_parser(
        "ingest",
        help="[--force]  增量扫描 data/kb/ 并建索引",
    )
    p_rag_ingest.add_argument("--force", action="store_true", help="强制全量重索引")
    p_rag_ingest.set_defaults(func=cmd_ingest_file)

    p_rag_search = rag_sub.add_parser(
        "search",
        help="<query> [--top-k N]  检索知识库原文",
    )
    p_rag_search.add_argument("query", help="搜索关键词")
    p_rag_search.add_argument("--top-k", type=int, default=5, help="返回条数（默认 5）")
    p_rag_search.set_defaults(func=cmd_rag_search)

    rag_sub.add_parser("status", help="诊断知识库索引状态").set_defaults(func=cmd_rag_status)
    rag_sub.add_parser(
        "reset",
        help="清空知识库索引（保留 kb/ 软链；并清理旧 ingest 记忆）",
    ).set_defaults(func=cmd_rag_reset)
    rag_sub.add_parser(
        "rebuild",
        help="清空后强制重扫 kb/",
    ).set_defaults(func=cmd_rag_rebuild)

    p_workspace = sub.add_parser(
        "workspace",
        help="[高级] [--days N] [--cwd PATH] [--todos-only]  工作区/git/待办快照",
        description="[高级] 查看工作区最近变更、Git 状态与待办项",
    )
    p_workspace.add_argument("--days", type=int, default=7, help="最近 N 天内的文件变更（默认 7）")
    p_workspace.add_argument("--cwd", help="工作区根目录")
    p_workspace.add_argument("--todos-only", action="store_true", help="仅列出待办项")
    p_workspace.add_argument("--limit", type=int, default=80, help="待办扫描上限（默认 80）")
    p_workspace.set_defaults(func=cmd_workspace)

    p_audit = sub.add_parser(
        "audit",
        help="[高级] [--since 7d] [--report PATH] [--cwd PATH]  审计摘要与报告",
        description="[高级] Token/费用、文件安全、记忆健康审计",
    )
    p_audit.add_argument("--since", help="统计起始，如 7d、24h、30m")
    p_audit.add_argument(
        "--report",
        help="导出报告路径（.md Markdown；.html HTML）",
    )
    p_audit.add_argument("--days", type=int, default=7, help="报告中工作区快照天数（默认 7）")
    p_audit.add_argument("--cwd", help="工作区根目录")
    p_audit.set_defaults(func=cmd_audit)

    p_logs = sub.add_parser(
        "logs",
        help="[高级] [--tail N] [--level LEVEL] [--path]  查看诊断日志",
        description=(
            "[高级] 查看本地诊断日志（data/logs/localagent.log）。\n"
            "与 LA audit（用量/护栏问责）不同：logs 用于排查运行时决策与降级。\n"
            "开发时可 LA --debug <command> 或设置 LA_LOG_LEVEL=DEBUG 盯 stderr。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_logs.add_argument(
        "--tail",
        type=int,
        default=80,
        help="显示最近 N 行（默认 80；0 表示全部）",
    )
    p_logs.add_argument(
        "--level",
        help="仅显示不低于该级别的行（如 DEBUG、INFO、WARNING）",
    )
    p_logs.add_argument(
        "--path",
        action="store_true",
        help="只打印日志文件路径",
    )
    p_logs.set_defaults(func=cmd_logs)

    p_config = sub.add_parser(
        "config",
        help="[--provider …] | <file.json> | init|list|…  【主路径】快速配置 / 管理模型",
        description=(
            "【主路径】快速写入模型与 API Key。\n"
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
            "--OPENAI_API_KEY",
            "--openai-api-key",
            dest="openai_api_key",
            help="OpenAI API Key",
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
    p_config_remove.add_argument("provider", help="provider 名称，如 openai / aiping")
    p_config_remove.set_defaults(func=cmd_config)

    p_config_set_key = config_sub.add_parser(
        "set-key",
        help="<provider> [key]  仅更新 api_key（key 省略或 - 时从 stdin 读取）",
    )
    p_config_set_key.add_argument(
        "provider",
        help="LA_MODEL_SERVERS 中的 provider，或 tavily / mem0",
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
        help="[--yes]  【主路径】安装 Ollama 并拉取 qwen3.5:4b（可跳过）",
        description=(
            "【主路径】检查本机 Ollama；未安装时询问是否本地安装，"
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

    p_summarize = sub.add_parser(
        "summarize",
        help="<path…> [--no-chat] [--keep] [--resume]  文档速读；默认进入文档对话",
        description=(
            "针对本地文档的速读与文档对话（与 la chat「和助手聊」不同）。\n"
            "  默认：打印速读卡后进入 sum> 文档对话（TTY）。\n"
            "  --no-chat：仅速读（可多文件），不进入对话。\n"
            "支持 .txt / .md / .pdf / .xlsx。\n"
            "默认不入库；会话内 /keep 或 --keep 收藏到知识库（不每次追问）。\n"
            "  la summarize --list                 # 最近文档对话\n"
            "  la summarize <path> --resume        # 续聊\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_summarize.add_argument(
        "paths",
        nargs="*",
        metavar="path",
        help="本地文件路径（多文件须加 --no-chat）",
    )
    p_summarize.add_argument(
        "--keep",
        action="store_true",
        help="速读后写入知识库（等同 LA rag add；默认不入库）",
    )
    p_summarize.add_argument(
        "--no-chat",
        action="store_true",
        help="只输出速读卡，不进入文档对话（可多文件）",
    )
    p_summarize.add_argument(
        "--out",
        metavar="FILE",
        help="将速读卡写入 Markdown 文件（常与 --no-chat 同用）",
    )
    p_summarize.add_argument(
        "--list",
        action="store_true",
        help="列出最近的文档对话会话",
    )
    p_summarize.add_argument(
        "--limit",
        type=int,
        default=20,
        help="--list 显示条数（默认 20）",
    )
    p_summarize.add_argument(
        "--resume",
        action="store_true",
        help="按路径续聊已有文档对话",
    )
    p_summarize.add_argument(
        "--id",
        dest="id",
        metavar="SESSION_ID",
        help="按会话 id 续聊",
    )
    p_summarize.add_argument(
        "--provider",
        "-p",
        default="auto",
        help=f"文档对话模型路径: auto（默认）, {', '.join(config.VALID_PROVIDERS)}",
    )
    p_summarize.add_argument(
        "--heuristic",
        action="store_true",
        help="强制使用本地启发式摘要（不调用模型；便于离线/测试）",
    )
    p_summarize.set_defaults(func=cmd_summarize)

    p_news = sub.add_parser(
        "news",
        help="新闻嗅探：sync / brief / read / schedule …",
        description=(
            "从 BestBlogs RSS 同步精选 AI 资讯，生成今日简报并支持精读。\n"
            "  la news sync              # 拉取 RSS\n"
            "  la news brief             # 今日简报（TTY 交互；--no-ui 刷屏）\n"
            "  la news read <id|url>     # 精读卡片（--keep 入库）\n"
            "  la news schedule on       # 每天 08:00 自动 sync（可 off）\n"
            "进入 la/chat 后，若早间已 sync，会提示「今日更新已准备好」。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    news_sub = p_news.add_subparsers(dest="news_action", metavar="action")

    p_news_sync = news_sub.add_parser("sync", help="从 RSS 同步最新条目")
    p_news_sync.add_argument("--url", default=None, help="覆盖默认 LA_NEWS_RSS_URL")
    p_news_sync.set_defaults(func=_cmd_news)

    p_news_brief = news_sub.add_parser(
        "brief",
        help="今日简报（TTY 下交互浏览；--no-ui 一次性输出）",
    )
    p_news_brief.add_argument("--date", default=None, help="日期 YYYY-MM-DD（默认今天）")
    p_news_brief.add_argument("--limit", type=int, default=None, help="条数上限")
    p_news_brief.add_argument(
        "--plain",
        action="store_true",
        help="强制 Markdown 链接（不要 OSC 8）；常与 --no-ui 合用",
    )
    p_news_brief.add_argument(
        "--no-ui",
        action="store_true",
        help="不进入交互浏览器，一次性打印全部简报",
    )
    p_news_brief.add_argument(
        "--provider",
        "-p",
        default="auto",
        help="精读深聊时的模型路径（默认 auto）",
    )
    p_news_brief.set_defaults(func=_cmd_news)

    p_news_skim = news_sub.add_parser("skim", help="<id|url>  速读卡片")
    p_news_skim.add_argument("target", help="文章 id 或 URL")
    p_news_skim.add_argument("--plain", action="store_true")
    p_news_skim.set_defaults(func=_cmd_news)

    p_news_read = news_sub.add_parser("read", help="<id|url> [--keep]  精读卡片")
    p_news_read.add_argument("target", help="文章 id 或 URL")
    p_news_read.add_argument("--keep", action="store_true", help="精读后写入知识库")
    p_news_read.add_argument(
        "--heuristic",
        action="store_true",
        help="强制启发式摘要（不调模型）",
    )
    p_news_read.add_argument("--plain", action="store_true")
    p_news_read.set_defaults(func=_cmd_news)

    p_news_mark = news_sub.add_parser("mark", help="<id> bookmark|skip|read")
    p_news_mark.add_argument("target", help="文章 id 或 URL")
    p_news_mark.add_argument(
        "mark_action",
        choices=["bookmark", "skip", "read"],
        help="动作",
    )
    p_news_mark.set_defaults(func=_cmd_news)

    p_news_sched = news_sub.add_parser(
        "schedule",
        help="on|off|status  配置早间自动 sync",
    )
    p_news_sched.add_argument(
        "schedule_action",
        nargs="?",
        default="status",
        choices=["on", "off", "status", "enable", "disable"],
    )
    p_news_sched.add_argument("--hour", type=int, default=None)
    p_news_sched.add_argument("--minute", type=int, default=None)
    p_news_sched.set_defaults(func=_cmd_news)

    p_news_int = news_sub.add_parser("interests", help="查看/设置兴趣标签")
    p_news_int.add_argument(
        "--set",
        dest="set_interests",
        default=None,
        help="逗号分隔覆盖 interests",
    )
    p_news_int.add_argument("--add", default=None, help="追加一个兴趣词")
    p_news_int.add_argument("--mute", default=None, help="追加 mute 关键词")
    p_news_int.set_defaults(func=_cmd_news)

    news_sub.add_parser("status", help="同步与定时状态").set_defaults(func=_cmd_news)
    news_sub.add_parser("sources", help="查看默认 RSS 源").set_defaults(func=_cmd_news)
    p_news.set_defaults(func=_cmd_news)

    p_polish = sub.add_parser(
        "polish",
        help="[--scene …] [--tone …] [--no-copy]  一键润色文案（默认复制主推到剪贴板）",
        description=(
            "一键润色：识别邮件 / 朋友圈 / 简历 / 商务对话场景与态度，"
            "给出主推 + 两个备选，并默认将主推复制到剪贴板。\n"
            "  la polish \"催一下进度的草稿\"\n"
            "  la polish --scene email --tone 更正式 --file draft.txt\n"
            "  echo \"草稿\" | la polish --no-copy\n"
            "会话内: /polish <草稿>"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_polish.add_argument(
        "text",
        nargs="*",
        help="待润色草稿（也可 --file 或 stdin）",
    )
    p_polish.add_argument(
        "--file",
        "-f",
        dest="file",
        help="从文件读取草稿",
    )
    p_polish.add_argument(
        "--scene",
        choices=["email", "moments", "resume", "biz"],
        help="强制场景（默认自动识别）",
    )
    p_polish.add_argument(
        "--tone",
        help="语气要求，如：更正式 / 更口语 / 更短",
    )
    p_polish.add_argument(
        "--no-copy",
        action="store_true",
        help="不写入剪贴板（脚本/管道场景）",
    )
    p_polish.set_defaults(func=cmd_polish)

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

    # 查版本不写配置/数据目录
    if argv and argv[0] in ("-V", "--version"):
        from localagent import __version__

        print(f"la-localagent {__version__}")
        return 0

    argv, debug = _extract_debug_flag(argv)

    # LA ≡ LA chat：无子命令时进入对话模式
    if not argv:
        argv = ["chat"]

    argv = _normalize_config_argv(argv)

    from localagent import env_config
    from localagent.completion import ensure_shell_completion
    from localagent.logging_setup import resolve_log_level, setup_logging
    from localagent.session_commands import dispatch_cli_argv

    env_config.ensure_config()
    ensure_shell_completion()
    config.ensure_data_dirs()
    setup_logging(level=resolve_log_level(debug=debug))
    get_task_store().reconcile_stale()
    try:
        return dispatch_cli_argv(argv, allow_chat=True)
    except KeyboardInterrupt:
        print("\n[LA] 已中断")
        return 130
    finally:
        from localagent.memory.backend import shutdown_memory_backend
        from localagent.models.router import shutdown_cursor_sdk

        shutdown_memory_backend()
        shutdown_cursor_sdk()


if __name__ == "__main__":
    sys.exit(main())
