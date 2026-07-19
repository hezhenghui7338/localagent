"""LA CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from localagent import config
from localagent.chat_repl import run_chat
from localagent.ingest.add_file import restart_background_task
from localagent.ingest.progress import ConsoleProgressReporter
from localagent.ingest.tasks import TaskStatus, format_task_line, get_task_store
from localagent.memory.backend import describe_memory_backend, get_memory_backend
from localagent.memory.query import list_memory_tags, query_memories
from localagent.memory.reset import (
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

# Hard-cut: old write paths → LA ingest (exit 2, no side effects)
_REMOVED_CMDS: dict[str, str] = {
    "memory add": 'LA ingest text "…"',
    "memory ingest": "LA ingest chat|chatgpt|doc|kb|text|all …",
    "rag add": "LA ingest doc <path>",
    "rag ingest": "LA ingest kb [--force]",
    "rag rebuild": "LA ingest rebuild [--force]",
}


def _print_removed(old: str) -> int:
    replacement = _REMOVED_CMDS[old]
    print(f"[LA] `{old}` 已移除，请改用: {replacement}")
    return 2


def _cmd_news(args: argparse.Namespace) -> int:
    from localagent.news.commands import cmd_news

    return cmd_news(args)


def _cmd_aware(args: argparse.Namespace) -> int:
    from localagent.aware.commands import cmd_aware

    return cmd_aware(args)


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


def cmd_add(_args: argparse.Namespace) -> int:
    return _print_removed("memory add")


def cmd_memory_pending(args: argparse.Namespace) -> int:
    from localagent.i18n import t
    from localagent.pending import list_pending, pending_count

    limit = getattr(args, "limit", None)
    items = list_pending(limit=limit)
    total = pending_count()
    if not items:
        print(t("memory.pending_empty"))
        return 0
    print(t("memory.pending_count", shown=len(items), total=total))
    for item in items:
        src = (item.metadata or {}).get("source", "")
        src_hint = f" · {src}" if src else ""
        print(f"  {item.id}  {item.text[:80]}{src_hint}")
    if limit is not None and total > len(items):
        print(t("memory.pending_more", n=total - len(items)))
    print(t("memory.pending_approve_hint"))
    print(t("memory.pending_reject_hint"))
    return 0


def cmd_memory_approve(args: argparse.Namespace) -> int:
    from localagent.i18n import t
    from localagent.pending import approve_all, approve_ids, pending_count

    if getattr(args, "all", False):
        warm_ids = approve_all()
    else:
        ids = list(getattr(args, "ids", None) or [])
        if not ids:
            print(t("memory.approve_need_id"))
            return 2
        warm_ids = approve_ids(ids)
    print(t("memory.approve_done", n=len(warm_ids), pending=pending_count()))
    return 0 if warm_ids or getattr(args, "all", False) else 1


def cmd_memory_reject(args: argparse.Namespace) -> int:
    from localagent.i18n import t
    from localagent.pending import pending_count, reject_all, reject_ids

    if getattr(args, "all", False):
        n = reject_all()
    else:
        ids = list(getattr(args, "ids", None) or [])
        if not ids:
            print(t("memory.reject_need_id"))
            return 2
        n = reject_ids(ids)
    print(t("memory.reject_done", n=n, pending=pending_count()))
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
    from localagent.i18n import t
    from localagent.summarize.document import (
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

    if getattr(args, "list", False):
        rows = list_sessions(limit=int(getattr(args, "limit", 20) or 20))
        if not rows:
            print(t("summarize.no_sessions"))
            return 0
        print(f"{'id':<14} {'updated':<22} {'kept':<5} file")
        for row in rows:
            kept = "yes" if row.kept else "no"
            print(f"{row.id:<14} {row.updated_at:<22} {kept:<5} {row.filename}")
        print(t("summarize.resume_hint"))
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
            print(t("summarize.session_not_found", id=resume_id))
            return 1
        source = Path(record.path)
        if not source.is_file():
            print(t("summarize.session_file_missing", path=source))
            return 1
        return _summarize_resume_one(
            source,
            record=record,
            provider=provider,
            heuristic=heuristic,
            keep=keep,
        )

    if not paths_raw:
        print(t("summarize.need_path"))
        return 1

    paths = [Path(p).expanduser().resolve() for p in paths_raw]
    if len(paths) > 1 and not no_chat:
        print(t("summarize.multi_no_chat"))
        return 1

    if do_resume and len(paths) == 1 and not no_chat:
        record = find_session_by_path(paths[0])
        if record is None:
            print(t("summarize.no_existing"))
        else:
            return _summarize_resume_one(
                paths[0],
                record=record,
                provider=provider,
                heuristic=heuristic,
                keep=keep,
            )

    results_md: list[str] = []
    failures = 0
    last_result = None
    for source in paths:
        print(t("summarize.file", path=source))
        try:
            result = summarize_path(source, keep=keep, use_llm=not heuristic)
        except KeyboardInterrupt:
            print(t("summarize.interrupted"))
            return 130
        except (DocumentTooLongError, SummarizeError) as exc:
            print(t("summarize.error", exc=exc))
            failures += 1
            continue
        except Exception as exc:
            print(t("summarize.error", exc=exc))
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
        meta_bits = [t("summarize.chars", n=result.char_count)]
        if result.page_count is not None:
            meta_bits.append(t("summarize.pages", n=result.page_count))
        meta_bits.append(t("summarize.llm") if result.used_llm else t("summarize.heuristic"))
        print(f"[summarize] {' · '.join(meta_bits)}")
        if result.warnings:
            for warning in result.warnings:
                print(t("summarize.warning", warning=warning))
        if result.kept:
            print(t("summarize.kept", target=result.keep_target))
        else:
            print(t("summarize.not_kept", hint=t("summarize.keep_hint")))

    if out_path and results_md:
        out = Path(out_path).expanduser().resolve()
        out.write_text("\n\n".join(results_md).rstrip() + "\n", encoding="utf-8")
        print(t("summarize.wrote", path=out))

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
    provider: str,
    heuristic: bool,
    keep: bool,
) -> int:
    from localagent.i18n import t
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
        print(t("summarize.file_updated"))
        result = summarize_path(source, keep=keep or record.kept, use_llm=not heuristic)
        if record.kept and not result.kept:
            result.kept = True
            result.keep_target = Path(record.keep_target) if record.keep_target else result.keep_target
    else:
        print(t("summarize.resume_session", id=record.id, filename=record.filename))
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
        print(t("summarize.kept", target=result.keep_target))
    else:
        print(t("summarize.not_kept_resume"))

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
    from localagent.i18n import t

    chunks: list[str] = []
    file_path = getattr(args, "file", None)
    if file_path:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(t("polish.file_missing", path=path))
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
    from localagent.i18n import t
    from localagent.ui.console import ActivityIndicator
    from localagent.writing.polish import PolishError, apply_clipboard, polish_text
    from localagent.writing.scenes import SCENE_IDS, normalize_scene

    try:
        draft = _resolve_polish_text(args)
    except FileNotFoundError as exc:
        print(t("polish.error", exc=exc))
        return 1
    if not draft:
        print(t("polish.usage"))
        return 1

    scene_raw = getattr(args, "scene", None)
    if scene_raw:
        scene = normalize_scene(scene_raw)
        if scene is None:
            print(
                t(
                    "polish.unknown_scene",
                    scene=scene_raw,
                    scenes=", ".join(SCENE_IDS),
                )
            )
            return 1
    else:
        scene = None
    tone = (getattr(args, "tone", None) or "").strip() or None
    want_copy = not bool(getattr(args, "no_copy", False))

    with ActivityIndicator("polish", t("polish.status_working")) as activity:
        try:
            result = polish_text(
                draft,
                scene=scene,
                tone=tone,
                on_status=activity.update,
            )
        except KeyboardInterrupt:
            print(t("polish.interrupted"))
            return 130
        except PolishError as exc:
            print(t("polish.error", exc=exc))
            return 1
        except Exception as exc:
            print(t("polish.error", exc=exc))
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


def cmd_add_file(_args: argparse.Namespace) -> int:
    return _print_removed("rag add")


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


def cmd_ingest_file(_args: argparse.Namespace) -> int:
    return _print_removed("rag ingest")


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
    print("  LA ingest doc <path>  软链到 kb/ 并持久记忆化")
    print("  LA rag search <q>     检索知识库（含对话归档）")
    print("  LA ingest kb          增量扫描 data/kb/")
    print("  LA ingest rebuild     重建 kb/ + chat + chatgpt Cold")
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
    from localagent.status.layers import memory_source_counts

    return memory_source_counts()


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
    return _print_removed("rag rebuild")


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

def cmd_ingest_chat(_args: argparse.Namespace) -> int:
    return _print_removed("memory ingest")


def cmd_ingest_chatgpt(_args: argparse.Namespace) -> int:
    return _print_removed("memory ingest")


def cmd_memory_ingest(_args: argparse.Namespace) -> int:
    return _print_removed("memory ingest")


def cmd_ingest_status(_args: argparse.Namespace) -> int:
    from localagent.ingest.conversation_cold import count_chunks_by_origin
    from localagent.ingest.sync_index import get_sync_index
    from localagent.knowledge.indexer import get_knowledge_indexer
    from localagent.persist.conversations import list_sessions

    sync = get_sync_index()
    indexer = get_knowledge_indexer()
    by_origin = count_chunks_by_origin()
    print("[ingest status] 持久记忆化概览")
    print(f"  kb 已索引:    {len(sync.all_filenames())} 文件 · {indexer.count()} chunks")
    print(
        f"  Cold 来源:    kb={by_origin.get('kb', 0)}  "
        f"chat={by_origin.get('chat', 0)}  "
        f"chatgpt={by_origin.get('chatgpt', 0)}  "
        f"other={by_origin.get('other', 0)}"
    )
    print(f"  LA 对话档案:  {len(list_sessions())} · 已消费 {_ingest_index_count(config.CHAT_INGEST_INDEX_FILE)}")
    print(f"  ChatGPT 导入: {_ingest_index_count(config.CHATGPT_IMPORT_INDEX_FILE)}")
    print(f"  Warm 条数:    {get_memory_store().count()}")
    print(f"  Hot 画像:     {'已配置' if _core_profile_configured() else '未配置'}")
    print("\n下一步:")
    print("  LA ingest chat|chatgpt|doc|kb|text|all")
    print("  LA ingest rebuild · LA ingest reset <source>")
    return 0


def cmd_ingest_reset(args: argparse.Namespace) -> int:
    source = (getattr(args, "reset_source", None) or "all").strip().lower()
    origin_map = {
        "chat": "chat",
        "chatgpt": "chatgpt",
        "doc": "file",
        "kb": "file",
        "file": "file",
        "text": "file",
        "all": "all",
    }
    if source not in origin_map:
        print(f"[ingest reset] 未知来源: {source}（可用: chat, chatgpt, doc, kb, text, all）")
        return 1
    origin = origin_map[source]
    reporter = ConsoleProgressReporter(prefix="ingest reset")
    try:
        if origin == "all":
            stats = reset_memory(clear_knowledge=True, source="all", reporter=reporter)
        elif origin == "file":
            stats = reset_knowledge(clear_knowledge=True, reporter=reporter)
        else:
            stats = reset_memory(clear_knowledge=False, source=origin, reporter=reporter)
    except ValueError as exc:
        print(f"[ingest reset] {exc}")
        return 1
    print(f"[ingest reset] cleared ({stats.get('source', source)}):")
    print(f"  facts removed:  {stats.get('memory_facts_removed', 0)}")
    print(f"  cold chunks:    {stats.get('knowledge_chunks_removed', 0)}")
    print(f"  sync entries:   {stats.get('sync_index_entries_removed', 0)}")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Unified persist → Cold → Warm → Hot entry point."""
    from localagent.ingest.engine import run_ingest

    action = (getattr(args, "source", None) or "status").strip().lower()
    if action == "status":
        return cmd_ingest_status(args)
    if action == "reset":
        args.reset_source = (getattr(args, "path_or_text", None) or ["all"])[0]
        return cmd_ingest_reset(args)
    if action == "rebuild":
        reporter = ConsoleProgressReporter(prefix="ingest rebuild")
        try:
            report = run_ingest("rebuild", force=True, reporter=reporter)
        except Exception as exc:
            print(f"[ingest rebuild] {exc}")
            return 1
        print(f"[ingest rebuild] {report.format_summary()}")
        if report.detail:
            print(f"[ingest rebuild] {report.detail}")
        for err in report.errors:
            print(f"[ingest rebuild] ! {err}")
        return 1 if report.errors and report.cold_chunks == 0 else 0

    path_or_text = list(getattr(args, "path_or_text", None) or [])
    files = list(getattr(args, "files", None) or [])
    directory = getattr(args, "directory", None)
    paths: list[str] = []
    text: str | None = None

    if action == "text":
        if files:
            paths = files
        elif path_or_text:
            # Prefer treating as literal text unless a single existing file path
            candidate = Path(path_or_text[0]).expanduser()
            if len(path_or_text) == 1 and candidate.is_file():
                paths = [str(candidate)]
            else:
                text = " ".join(path_or_text)
        else:
            print('[ingest] 请提供文本: LA ingest text "…"')
            return 2
    elif action in ("doc", "news", "summarize", "polish"):
        paths = files or path_or_text
    elif action == "chatgpt":
        paths = files or path_or_text
    else:
        paths = files or path_or_text

    prefix = f"ingest {action}"
    reporter = ConsoleProgressReporter(prefix=prefix)
    try:
        report = run_ingest(
            action,
            force=bool(getattr(args, "force", False)),
            interactive=bool(getattr(args, "interactive", False)),
            include_disabled=bool(getattr(args, "include_disabled", False)),
            background=bool(getattr(args, "background", False)),
            session_id=getattr(args, "session", None),
            paths=paths or None,
            directory=directory,
            text=text,
            reporter=reporter,
        )
    except ValueError as exc:
        print(f"[ingest] {exc}")
        return 2
    except KeyboardInterrupt:
        print(f"\n[{prefix}] 已中断")
        return 130

    for err in report.errors:
        print(f"[{prefix}] ! {err}")
    print(f"[{prefix}] {report.format_summary()}")
    if report.detail:
        # Prefer Chinese wording for background tasks (e2e / UX)
        if "background task=" in report.detail:
            # background task=t-xxx pid=N
            parts = dict(
                p.split("=", 1) for p in report.detail.split() if "=" in p
            )
            tid = parts.get("task") or parts.get("background")
            pid = parts.get("pid", "")
            log = parts.get("log", "")
            if tid:
                print(f"[{prefix}] 后台任务 {tid}" + (f" (pid={pid})" if pid else ""))
                if log:
                    print(f"[{prefix}] 日志: {log}")
            else:
                print(f"[{prefix}] {report.detail}")
        else:
            print(f"[{prefix}] {report.detail}")
    if report.persisted_paths and action in ("doc", "chatgpt", "text"):
        for p in report.persisted_paths[:5]:
            label = "软链" if action == "doc" else "archived"
            print(f"[{prefix}] {label}: {p}")
    if report.warm_saved:
        print(f"→ 已写入记忆 Warm +{report.warm_saved}")
    elif report.cold_chunks and not report.errors:
        print(f"→ Cold +{report.cold_chunks}（无新 Warm 或仍待确认）")
    if action in ("doc", "kb") and not report.errors:
        print(f"[{prefix}] done")
    if action == "chatgpt" and not paths and not directory and report.detail == "no chatgpt exports":
        print("[ingest chatgpt] 请指定导出文件路径，或使用 --file / --dir")
        print("  对话历史: conversations.json")
        print("  已保存记忆: memory.json / memories.json")
        return 1
    if action == "text" and report.warm_saved == 0:
        return 1
    if report.errors and report.cold_chunks == 0 and report.warm_saved == 0:
        return 1
    return 0


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
    from localagent.i18n import t

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
        print(t("memory.search_forget_hint"))
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
    from localagent.i18n import t
    from localagent.persist.conversations import list_sessions

    info = describe_memory_backend()
    print(t("memory.status_title"))
    print(
        t(
            "memory.status_backend",
            backend=info["active_backend"],
            cls=info.get("backend_class", "?"),
        )
    )
    print(t("memory.status_preference", preference=info["preference"]))
    print(t("memory.status_python", version=info["python_version"]))
    print(
        t(
            "memory.status_mem0",
            state=t("memory.installed") if info.get("mem0_installed") else t("memory.not_installed"),
        )
    )
    if info.get("mem0_installed"):
        print(
            t(
                "memory.status_infer",
                state=t("memory.on") if info.get("mem0_infer") else t("memory.off"),
            )
        )
        print(
            t(
                "memory.status_llm",
                provider=info.get("mem0_llm_provider", "?"),
                model=info.get("mem0_llm_model", "?"),
            )
        )
        print(
            t(
                "memory.status_embedder",
                provider=info.get("mem0_embedder_provider", "?"),
                model=info.get("mem0_embedder_model", "?"),
                dims=info.get("mem0_embedder_dims", "?"),
            )
        )
        print(
            t(
                "memory.status_retain_fallback",
                state=t("memory.on") if info.get("retain_json_fallback") else t("memory.off"),
            )
        )
        print(t("memory.status_mem0_dir", path=info.get("mem0_dir", "?")))
    print(t("memory.status_count", n=info["memory_count"]))
    if info.get("unindexed_count"):
        print(t("memory.status_unindexed", n=info["unindexed_count"]))

    sources = _memory_source_counts()
    print(
        t(
            "memory.status_sources",
            chat=sources["chat"],
            chatgpt=sources["chatgpt"],
            file=sources["file"],
            other=sources["other"],
        )
    )
    chat_sessions = len(list_sessions())
    chat_ingested = _ingest_index_count(config.CHAT_INGEST_INDEX_FILE)
    chatgpt_imported = _ingest_index_count(config.CHATGPT_IMPORT_INDEX_FILE)
    print(
        t(
            "memory.status_chat_sessions",
            sessions=chat_sessions,
            ingested=chat_ingested,
        )
    )
    print(t("memory.status_chatgpt", n=chatgpt_imported))
    try:
        from localagent.ingest.conversation_cold import count_chunks_by_origin

        cold = count_chunks_by_origin()
        print(
            t(
                "memory.status_cold",
                chat=cold.get("chat", 0),
                chatgpt=cold.get("chatgpt", 0),
            )
        )
    except Exception:
        pass
    print(
        t(
            "memory.status_hot_profile",
            state=t("memory.configured") if _core_profile_configured() else t("memory.not_configured"),
            path=config.CORE_PROFILE_FILE,
        )
    )
    print(
        t(
            "memory.status_graph",
            state=t("memory.on") if config.MEMORY_GRAPH else t("memory.off"),
        )
    )

    print(
        t(
            "memory.status_profile_pin",
            mode=t("memory.pin_llm") if info.get("profile_pin_llm") else t("memory.pin_regex"),
        )
    )
    print(t("memory.status_bank", bank_id=info["bank_id"]))
    print(t("memory.status_store", path=info["store_file"]))
    if info.get("error"):
        print(t("memory.status_error", error=info["error"]))
    if info["active_backend"] == "json" and info["preference"] != "json":
        print(t("memory.status_json_fallback_hint"))
    if info.get("unindexed_count"):
        print(t("memory.status_unindexed_hint"))

    print(t("memory.status_next"))
    print(t("memory.status_next_query"))
    print(t("memory.status_next_search"))
    print(t("memory.status_next_ingest"))
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
    """Status surface: Daily Actions + data layers + recall priority note."""
    from localagent.status.report import format_status_report

    print(format_status_report())
    return 0


def cmd_workspace(args: argparse.Namespace) -> int:
    _apply_workspace_cwd(getattr(args, "cwd", None))
    from localagent.i18n import t
    from localagent.workspace.context import (
        format_diagnostic_todos,
        format_workspace_summary,
        resolve_workspace,
    )
    from localagent.workspace.tasks import (
        TaskRejected,
        add_task,
        dismiss,
        done,
        format_open_tasks,
        load_tasks,
        purge,
        snooze,
    )

    root = resolve_workspace()
    action = getattr(args, "workspace_action", None) or ""
    todos_only = bool(getattr(args, "todos_only", False))
    detail = bool(getattr(args, "detail", False))
    limit = int(getattr(args, "limit", 80) or 80)
    file_days = int(getattr(args, "days", 7) or 7)

    if todos_only or action == "scan":
        print(format_diagnostic_todos(root, limit=limit))
        return 0

    if action == "tasks":
        tasks_action = getattr(args, "tasks_action", None)
        if tasks_action == "purge":
            older = getattr(args, "older_than", None)
            removed = purge(
                root,
                older_than_days=int(older) if older is not None else None,
            )
            print(t("workspace.purged", removed=removed))
            return 0
        if getattr(args, "all", False):
            items = load_tasks(root)
            if not items:
                print(t("workspace.no_tasks", root=root))
                return 0
            print(t("workspace.all_tasks", root=root, n=len(items)))
            for item in items:
                print(f"  [{item.id}] ({item.status}) {item.title}")
            return 0
        print(format_open_tasks(root, limit=limit, verbose=True))
        return 0

    if action == "add":
        title = (getattr(args, "title", None) or "").strip()
        why = (getattr(args, "why", None) or "").strip()
        hint = (getattr(args, "hint", None) or "").strip()
        try:
            task = add_task(
                title,
                why,
                source="user",
                workspace=root,
                complete_hint=hint,
            )
        except TaskRejected as exc:
            print(t("workspace.rejected", exc=exc))
            return 1
        print(t("workspace.added", id=task.id, title=task.title))
        print(t("workspace.why", rationale=task.rationale))
        print(t("workspace.done_hint", id=task.id))
        return 0

    if action == "done":
        task = done(getattr(args, "task_id", ""), workspace=root)
        if task is None:
            print(t("workspace.not_found"))
            return 1
        print(t("workspace.done", id=task.id, title=task.title))
        return 0

    if action == "dismiss":
        task = dismiss(getattr(args, "task_id", ""), workspace=root)
        if task is None:
            print(t("workspace.not_found"))
            return 1
        print(t("workspace.dismissed", id=task.id, title=task.title))
        return 0

    if action == "snooze":
        snooze_days = int(getattr(args, "snooze_days", None) or 1)
        task = snooze(getattr(args, "task_id", ""), days=snooze_days, workspace=root)
        if task is None:
            print(t("workspace.not_found"))
            return 1
        until = (task.snooze_until or "")[:10]
        print(t("workspace.snoozed", id=task.id, title=task.title, until=until))
        return 0

    if action == "purge":
        older = getattr(args, "older_than", None)
        removed = purge(
            root,
            older_than_days=int(older) if older is not None else None,
        )
        print(t("workspace.purged", removed=removed))
        return 0

    print(
        format_workspace_summary(
            days=file_days,
            workspace=root,
            include_diagnostic=detail,
        )
    )
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
        from localagent.i18n import t

        out = Path(args.report).expanduser()
        write_report(out, since=args.since, workspace_days=args.days)
        print(t("audit.report_written", path=out))
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
    from localagent.i18n import H, t

    parser = argparse.ArgumentParser(
        prog="LA",
        description=t("cli.description"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=t("cli.epilog"),
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"la-localagent {__version__}",
        help=t("cli.version_help"),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help=t("cli.debug_help"),
    )
    sub = parser.add_subparsers(
        dest="cmd",
        required=False,
        metavar="<command>",
        title=H("命令", "commands"),
        description=H("主路径：chat · setup · config；其余为高级能力（memory / rag / audit …）。省略子命令时默认 chat：", "Main path: chat · setup · config; others are advanced (memory / rag / audit …). Defaults to chat when omitted:"),
    )

    p_status = sub.add_parser(
        "status",
        help=H("今日信号 + 数据层（Hot/Warm/Cold/Aware）", "Today's signals + data layers (Hot/Warm/Cold/Aware)"),
        description=H("统一状态：Daily Actions（新闻 sync / pending / workspace 待办 / aware）与数据层库存（Hot 画像 / Warm 事实 / Cold kb·对话·收藏 / Aware），并说明综合召回优先级。会话内等价命令：/status。", "Unified status: Daily Actions (news sync / pending / workspace todos / aware) and data inventory (Hot profile / Warm facts / Cold kb·chats·bookmarks / Aware), plus recall priority. In-session: /status."),
    )
    p_status.set_defaults(func=cmd_status)

    p_chat = sub.add_parser(
        "chat",
        help=t("cli.chat_help", providers="|".join(config.VALID_PROVIDERS)),
        description=t("cli.chat_desc"),
    )
    p_chat.add_argument("--session-id", help=H("恢复指定对话档案 id", "resume a chat archive by id"))
    p_chat.add_argument(
        "--provider",
        "-p",
        default="auto",
        help=H(
            f"模型路径: auto（默认）, {', '.join(config.VALID_PROVIDERS)}",
            f"model path: auto (default), {', '.join(config.VALID_PROVIDERS)}",
        ),
    )
    p_chat.add_argument(
        "--cwd",
        help=H("工作区根目录（等同 LA_WORKSPACE，用于 git/文件/todo 上下文）", "workspace root (same as LA_WORKSPACE; for git/files/todo context)"),
    )
    p_chat.set_defaults(func=cmd_chat)

    p_tasks = sub.add_parser(
        "tasks",
        help=H("[高级] [--limit N] [--tail N] [list | <task_id> | delete|pause|resume|restart|logs <task_id>]  后台索引任务", "[advanced] [--limit N] [--tail N] [list | <task_id> | delete|pause|resume|restart|logs <task_id>]  background index tasks"),
        description=H("[高级] 查看和管理后台索引任务", "[advanced] list and manage background index tasks"),
    )
    p_tasks.add_argument(
        "positional",
        nargs="*",
        metavar="[action] [task_id]",
        help=H(
            "list | <task_id> | <action> <task_id>（delete/pause/resume/restart/logs）",
            "list | <task_id> | <action> <task_id> (delete/pause/resume/restart/logs)",
        ),
    )
    p_tasks.add_argument("--limit", type=int, default=10, help=H("最近任务显示条数（默认 10）", "recent tasks to show (default 10)"))
    p_tasks.add_argument("--tail", type=int, default=50, help=H("logs 操作输出的行数（默认 50）", "lines for logs action (default 50)"))
    p_tasks.set_defaults(func=cmd_tasks)

    p_memory = sub.add_parser(
        "memory",
        help=H("[status]|query|search|pending|…  无参显示概览；Warm 查询与运维", "[status]|query|search|pending|…  overview if bare; Warm query & ops"),
        description=H("Warm 记忆查询与运维。写入请用 LA ingest。\n  LA memory\n  LA memory query / search / consolidate / forget / status / reset / reindex\n  LA memory pending / approve / reject\n  LA memory reflect <query>（亦可用一级命令 LA reflect）\n  LA memory graph stats|rebuild|neo4j|query\n持久记忆化: LA ingest chat|chatgpt|doc|kb|text|all", "Warm memory query & ops. Write via LA ingest.\n  LA memory\n  LA memory query / search / consolidate / forget / status / reset / reindex\n  LA memory pending / approve / reject\n  LA memory reflect <query> (or top-level LA reflect)\n  LA memory graph stats|rebuild|neo4j|query\nPersist: LA ingest chat|chatgpt|doc|kb|text|all"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mem_sub = p_memory.add_subparsers(
        dest="memory_cmd",
        required=False,
        metavar="<action>",
        title=H("操作", "actions"),
    )
    p_memory.set_defaults(func=cmd_memory_status)

    p_mem_add = mem_sub.add_parser(
        "add",
        help=H("[已移除] 请改用 LA ingest text", "[removed] use LA ingest text"),
    )
    p_mem_add.add_argument("text", nargs="?", default="", help=argparse.SUPPRESS)
    p_mem_add.set_defaults(func=cmd_add)

    p_mem_pending = mem_sub.add_parser(
        "pending",
        help=H("[--limit N]  列出待确认的 Warm 记忆候选", "[--limit N]  list pending Warm memory candidates"),
    )
    p_mem_pending.add_argument("--limit", type=int, default=None, help=H("最多显示条数", "max items to show"))
    p_mem_pending.set_defaults(func=cmd_memory_pending)

    p_mem_approve = mem_sub.add_parser(
        "approve",
        help=H("<id…> | --all  批准待确认记忆并写入 Warm", "<id…> | --all  approve pending memories into Warm"),
    )
    p_mem_approve.add_argument("ids", nargs="*", help=H("pending id（可多个）", "pending id(s)"))
    p_mem_approve.add_argument("--all", action="store_true", help=H("批准全部", "approve all"))
    p_mem_approve.set_defaults(func=cmd_memory_approve)

    p_mem_reject = mem_sub.add_parser(
        "reject",
        help=H("<id…> | --all  拒绝待确认记忆（不写入 Warm）", "<id…> | --all  reject pending memories (no Warm write)"),
    )
    p_mem_reject.add_argument("ids", nargs="*", help=H("pending id（可多个）", "pending id(s)"))
    p_mem_reject.add_argument("--all", action="store_true", help=H("拒绝全部", "reject all"))
    p_mem_reject.set_defaults(func=cmd_memory_reject)

    p_mem_forget = mem_sub.add_parser(
        "forget",
        help=H("<id> [--yes]  删除一条记忆", "<id> [--yes]  delete one memory"),
        description=H("删除一条记忆（先用 LA memory search / query 查看 id）", "delete one memory (find id via LA memory search / query)"),
    )
    p_mem_forget.add_argument("id", help=H("记忆 id（支持前缀匹配）", "memory id (prefix match ok)"))
    p_mem_forget.add_argument("--yes", "-y", action="store_true", help=H("跳过确认", "skip confirmation"))
    p_mem_forget.set_defaults(func=cmd_forget)

    p_mem_ingest = mem_sub.add_parser(
        "ingest",
        help=H("[已移除] 请改用 LA ingest …", "[removed] use LA ingest …"),
        description=H("已移除。请改用: LA ingest chat|chatgpt|doc|kb|text|all", "Removed. Use: LA ingest chat|chatgpt|doc|kb|text|all"),
    )
    p_mem_ingest.add_argument(
        "source",
        nargs="?",
        default="chat",
        help=argparse.SUPPRESS,
    )
    p_mem_ingest.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    p_mem_ingest.add_argument("--session", help=argparse.SUPPRESS)
    p_mem_ingest.add_argument("--interactive", action="store_true", help=argparse.SUPPRESS)
    p_mem_ingest.add_argument("path", nargs="?", help=argparse.SUPPRESS)
    p_mem_ingest.add_argument("--file", dest="files", nargs="+", help=argparse.SUPPRESS)
    p_mem_ingest.add_argument("--dir", dest="directory", help=argparse.SUPPRESS)
    p_mem_ingest.add_argument("--include-disabled", action="store_true", help=argparse.SUPPRESS)
    p_mem_ingest.set_defaults(func=cmd_memory_ingest)

    p_mem_reset = mem_sub.add_parser(
        "reset",
        help=H("[chat|chatgpt|all]  按来源清空 Warm 记忆", "[chat|chatgpt|all]  clear Warm memories by source"),
        description=H("按来源清空记忆；默认 all。知识库请用 LA rag reset。", "clear memories by source; default all. For knowledge base use LA rag reset."),
    )
    p_mem_reset.add_argument(
        "source",
        nargs="?",
        default="all",
        choices=("chat", "chatgpt", "all"),
        help=H("清空范围（默认 all）", "clear scope (default all)"),
    )
    p_mem_reset.set_defaults(func=cmd_reset_memory)

    p_mem_status = mem_sub.add_parser(
        "status",
        help=H("诊断 Warm 层记忆后端（Mem0 / JSON）", "diagnose Warm memory backend (Mem0 / JSON)"),
    )
    p_mem_status.set_defaults(func=cmd_memory_status)

    mem_sub.add_parser(
        "reindex",
        help=H("从 memory_store.json 重建 Mem0 向量索引（不删事实）", "rebuild Mem0 vector index from memory_store.json (facts kept)"),
        description=H("保留 JSON 注册表，清空并重建 Mem0 Warm 引擎索引", "keep JSON registry; wipe and rebuild Mem0 Warm engine index"),
    ).set_defaults(func=cmd_reindex_memory)

    p_mem_graph = mem_sub.add_parser(
        "graph",
        help=H("[stats|rebuild|neo4j|query]  记忆关系图 / 精确图查询", "[stats|rebuild|neo4j|query]  memory graph / precise graph query"),
        description=H("SQLite 召回 hop 图（LA_MEMORY_GRAPH）与 Neo4j 精确查询（LA_NEO4J）。stats/rebuild 管本地图；neo4j stats|rebuild 管 Neo4j；query 对计数/聚合/多跳跑 Cypher 模板。", "SQLite recall hop graph (LA_MEMORY_GRAPH) and Neo4j precise query (LA_NEO4J). stats/rebuild for local graph; neo4j stats|rebuild for Neo4j; query runs Cypher templates for counts/aggregates/multi-hop."),
    )
    p_mem_graph.add_argument(
        "graph_action",
        nargs="?",
        default="stats",
        choices=("stats", "rebuild", "neo4j", "query"),
        help=H("stats|rebuild|neo4j|query（默认 stats）", "stats|rebuild|neo4j|query (default stats)"),
    )
    p_mem_graph.add_argument(
        "graph_arg",
        nargs="?",
        default=None,
        help=H("neo4j 时为 stats|rebuild；query 时为问题文本", "for neo4j: stats|rebuild; for query: question text"),
    )
    p_mem_graph.set_defaults(func=cmd_memory_graph)

    p_mem_search = mem_sub.add_parser(
        "search",
        help=H("<query> [--top-k N] [--verbose]  语义搜索 Warm 记忆", "<query> [--top-k N] [--verbose]  semantic search Warm memories"),
    )
    p_mem_search.add_argument("query", help=H("搜索关键词", "search query"))
    p_mem_search.add_argument("--top-k", type=int, default=5, help=H("返回条数（默认 5）", "results to return (default 5)"))
    p_mem_search.add_argument("--verbose", action="store_true", help=H("显示记忆锚点等详情", "show memory anchors and details"))
    p_mem_search.set_defaults(func=cmd_search)

    p_mem_consolidate = mem_sub.add_parser(
        "consolidate",
        help=H("巩固近期记忆（ADD/UPDATE/DELETE，默认后台）", "consolidate recent memories (ADD/UPDATE/DELETE; background by default)"),
        description=H("扫描近期记忆，合并冲突/重复；默认后台任务，可用 la tasks 查看进度", "scan recent memories, merge conflicts/dupes; background by default (see la tasks)"),
    )
    p_mem_consolidate.add_argument(
        "--limit",
        type=int,
        default=40,
        help=H("扫描最近 N 条记忆（默认 40）", "scan last N memories (default 40)"),
    )
    p_mem_consolidate.add_argument(
        "--foreground",
        "-f",
        action="store_true",
        help=H("前台同步执行（默认后台）", "run in foreground (default background)"),
    )
    p_mem_consolidate.set_defaults(func=cmd_consolidate)

    p_mem_query = mem_sub.add_parser(
        "query",
        help=H("[query] [--tag TAG] [--since DATE] [--sort …]  条件浏览/查询记忆", "[query] [--tag TAG] [--since DATE] [--sort …]  browse/query memories"),
        description=H("浏览或查询记忆库：标签过滤、时间范围、排序、语义匹配", "browse or query memories: tags, date range, sort, semantic match"),
    )
    p_mem_query.add_argument("query", nargs="?", default="", help=H("可选，语义搜索关键词", "optional semantic search query"))
    p_mem_query.add_argument(
        "--tag",
        action="append",
        dest="tag",
        metavar="TAG",
        help=H("按标签过滤（可多次指定）", "filter by tag (repeatable)"),
    )
    p_mem_query.add_argument("--since", help=H("起始日期，如 2024-01-01", "start date, e.g. 2024-01-01"))
    p_mem_query.add_argument("--until", help=H("结束日期，如 2024-12-31", "end date, e.g. 2024-12-31"))
    p_mem_query.add_argument(
        "--sort",
        choices=("newest", "oldest", "relevance"),
        default="newest",
        help=H("排序方式（默认 newest；有 query 时可用 relevance）", "sort order (default newest; relevance when query set)"),
    )
    p_mem_query.add_argument("--limit", type=int, default=20, help=H("返回条数（默认 20）", "results to return (default 20)"))
    p_mem_query.add_argument("--verbose", action="store_true", help=H("显示评分细节", "show scoring details"))
    p_mem_query.add_argument("--json", action="store_true", help=H("以 JSON 输出", "output as JSON"))
    p_mem_query.add_argument(
        "--list-tags",
        action="store_true",
        help=H("列出所有记忆标签及数量", "list all memory tags and counts"),
    )
    p_mem_query.set_defaults(func=cmd_memories)

    p_mem_reflect = mem_sub.add_parser(
        "reflect",
        help=H("[高级] <query>  综合推理（记忆 → 知识库 → 归纳）", "[advanced] <query>  reflect (memory → knowledge → synthesis)"),
        description=H("[高级] 先多跳召回长期记忆，再检索知识库，最后综合推理。\n  LA memory reflect \"我最近状态怎么样？\"", "[advanced] multi-hop memory recall, then knowledge search, then synthesize.\n  LA memory reflect \"How have I been lately?\""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_mem_reflect.add_argument("query", help=H("需要推理的问题", "question to reason about"))
    p_mem_reflect.set_defaults(func=cmd_reflect)

    p_reflect = sub.add_parser(
        "reflect",
        help=H("[高级] <query>  综合推理（兼容别名；推荐 LA memory reflect）", "[advanced] <query>  reflect (alias; prefer LA memory reflect)"),
        description=H("[高级] 先多跳召回长期记忆，再检索知识库，最后综合推理给出答案。\n  LA reflect \"我最近状态怎么样？\"\n  等价：LA memory reflect \"…\"", "[advanced] multi-hop memory recall, then knowledge search, then answer.\n  LA reflect \"How have I been lately?\"\n  same as: LA memory reflect \"…\""),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_reflect.add_argument("query", help=H("需要推理的问题", "question to reason about"))
    p_reflect.set_defaults(func=cmd_reflect)

    p_websearch = sub.add_parser(
        "websearch",
        help=H("[高级] <query> [--top-k N]  联网搜索（亦可用会话内自动联网）", "[advanced] <query> [--top-k N]  web search (or auto in session)"),
        description=H("[高级] 直接联网检索并输出结果摘要与来源链接。\n默认后端 ddgs（免费）；可用 LA_WEB_SEARCH_PROVIDER / Tavily / SearXNG。\n多步深度研究请用会话内 /deepsearch。\n  LA websearch \"今天深圳天气\"\n  LA websearch \"最新 AI 进展\" --top-k 8", "[advanced] web search with summaries and source links.\nDefault backend ddgs (free); or LA_WEB_SEARCH_PROVIDER / Tavily / SearXNG.\nFor multi-step research use in-session /deepsearch.\n  LA websearch \"Shenzhen weather today\"\n  LA websearch \"latest AI news\" --top-k 8"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_websearch.add_argument("query", help=H("联网搜索关键词", "web search query"))
    p_websearch.add_argument("--top-k", type=int, default=5, help=H("返回条数（默认 5）", "results to return (default 5)"))
    p_websearch.set_defaults(func=cmd_websearch)

    p_rag = sub.add_parser(
        "rag",
        help=H("[status]|search|reset  无参显示概览；Cold 知识库检索与运维", "[status]|search|reset  overview if bare; Cold knowledge ops"),
        description=H("Cold 知识库检索与运维。写入/重建请用 LA ingest。\n无子命令时显示 status 概览。\n  LA rag\n  LA rag search <query>\n  LA rag status | reset\n持久记忆化: LA ingest doc|kb|rebuild", "Cold knowledge search & ops. Write/rebuild via LA ingest.\nBare command shows status overview.\n  LA rag\n  LA rag search <query>\n  LA rag status | reset\nPersist: LA ingest doc|kb|rebuild"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    rag_sub = p_rag.add_subparsers(
        dest="rag_cmd",
        required=False,
        metavar="<action>",
        title=H("操作", "actions"),
    )
    p_rag.set_defaults(func=cmd_rag_status)

    p_rag_add = rag_sub.add_parser(
        "add",
        help=H("[已移除] 请改用 LA ingest doc", "[removed] use LA ingest doc"),
    )
    p_rag_add.add_argument("path", nargs="?", default="", help=argparse.SUPPRESS)
    p_rag_add.add_argument("--background", "-b", action="store_true", help=argparse.SUPPRESS)
    p_rag_add.set_defaults(func=cmd_add_file)

    p_rag_ingest = rag_sub.add_parser(
        "ingest",
        help=H("[已移除] 请改用 LA ingest kb", "[removed] use LA ingest kb"),
    )
    p_rag_ingest.add_argument("--force", action="store_true", help=argparse.SUPPRESS)
    p_rag_ingest.set_defaults(func=cmd_ingest_file)

    p_rag_search = rag_sub.add_parser(
        "search",
        help=H("<query> [--top-k N]  检索知识库原文", "<query> [--top-k N]  search knowledge base text"),
    )
    p_rag_search.add_argument("query", help=H("搜索关键词", "search query"))
    p_rag_search.add_argument("--top-k", type=int, default=5, help=H("返回条数（默认 5）", "results to return (default 5)"))
    p_rag_search.set_defaults(func=cmd_rag_search)

    rag_sub.add_parser("status", help=H("诊断知识库索引状态", "diagnose knowledge index status")).set_defaults(func=cmd_rag_status)
    rag_sub.add_parser(
        "reset",
        help=H("清空知识库索引（保留 kb/ 软链；并清理旧 ingest 记忆）", "clear knowledge index (keep kb/ symlinks; purge old ingest memories)"),
    ).set_defaults(func=cmd_rag_reset)
    rag_sub.add_parser(
        "rebuild",
        help=H("[已移除] 请改用 LA ingest rebuild", "[removed] use LA ingest rebuild"),
    ).set_defaults(func=cmd_rag_rebuild)

    p_ingest = sub.add_parser(
        "ingest",
        help=H("status|chat|chatgpt|doc|kb|text|all|rebuild|…  统一持久记忆化", "status|chat|chatgpt|doc|kb|text|all|rebuild|…  unified persist ingest"),
        description=H("统一持久记忆化：落盘 → Cold → Warm → core-profile。\n  LA ingest status\n  LA ingest chat [--force] [--session ID]\n  LA ingest chatgpt [path] [--file …] [--dir …] [--force]\n  LA ingest doc [-b] <path>\n  LA ingest kb [--force]\n  LA ingest text \"…\"\n  LA ingest all [--force]\n  LA ingest rebuild\n  LA ingest reset [chat|chatgpt|doc|kb|text|all]\n查询面仍用: LA memory search · LA rag search", "Unified persist ingest: disk → Cold → Warm → core-profile.\n  LA ingest status\n  LA ingest chat [--force] [--session ID]\n  LA ingest chatgpt [path] [--file …] [--dir …] [--force]\n  LA ingest doc [-b] <path>\n  LA ingest kb [--force]\n  LA ingest text \"…\"\n  LA ingest all [--force]\n  LA ingest rebuild\n  LA ingest reset [chat|chatgpt|doc|kb|text|all]\nQuery via: LA memory search · LA rag search"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_ingest.add_argument(
        "source",
        nargs="?",
        default="status",
        help=H("来源或动作: status|chat|chatgpt|doc|kb|text|all|rebuild|reset|aware|news|summarize|polish", "source or action: status|chat|chatgpt|doc|kb|text|all|rebuild|reset|aware|news|summarize|polish"),
    )
    p_ingest.add_argument(
        "path_or_text",
        nargs="*",
        help=H("文档/导出路径，或 text 的正文；reset 时为目标来源", "doc/export path, or text body; for reset: target source"),
    )
    p_ingest.add_argument("--force", action="store_true", help=H("强制重新消费已处理内容", "force re-ingest already processed content"))
    p_ingest.add_argument("--session", help=H("仅处理指定对话 session id（source=chat）", "only process given chat session id (source=chat)"))
    p_ingest.add_argument(
        "--interactive",
        action="store_true",
        help=H("逐条确认是否保存 Warm（chat/chatgpt）", "confirm each Warm save (chat/chatgpt)"),
    )
    p_ingest.add_argument(
        "--file",
        dest="files",
        nargs="+",
        metavar="PATH",
        help=H("一个或多个文件路径（chatgpt/doc）", "one or more file paths (chatgpt/doc)"),
    )
    p_ingest.add_argument(
        "--dir",
        dest="directory",
        help=H("批量导入目录下全部 *.json（chatgpt；默认 data/chatGPTdata/）", "import all *.json under a directory (chatgpt; default data/chatGPTdata/)"),
    )
    p_ingest.add_argument(
        "--include-disabled",
        action="store_true",
        help=H("同时导入 ChatGPT 中已关闭（enabled=false）的记忆", "also import ChatGPT memories with enabled=false"),
    )
    p_ingest.add_argument(
        "--background",
        "-b",
        action="store_true",
        help=H("doc：创建软链后在后台索引", "doc: symlink then index in background"),
    )
    p_ingest.set_defaults(func=cmd_ingest)

    p_workspace = sub.add_parser(
        "workspace",
        help=H("[高级] 工作区摘要 / 托管待办 / 诊断扫描", "[advanced] workspace summary / managed todos / diagnostic scan"),
        description=H("[高级] 工作区最近变更、Git 状态与托管待办。正式待办: tasks / add / done / dismiss / snooze；代码 TODO 扫描仅诊断（--todos-only / scan），不自动入队。", "[advanced] recent workspace changes, Git status, managed todos. Todos: tasks / add / done / dismiss / snooze; code TODO scan is diagnostic only (--todos-only / scan), never auto-queued."),
    )
    p_workspace.add_argument("--days", type=int, default=7, help=H("最近 N 天内的文件变更（默认 7）", "file changes in last N days (default 7)"))
    p_workspace.add_argument("--cwd", help=H("工作区根目录", "workspace root"))
    p_workspace.add_argument(
        "--todos-only",
        action="store_true",
        help=H("诊断扫描代码 TODO/checkbox（未入队；等同 scan）", "diagnostic scan of code TODO/checkbox (not queued; same as scan)"),
    )
    p_workspace.add_argument(
        "--detail",
        action="store_true",
        help=H("摘要末尾附带诊断扫描命中（未入队）", "append diagnostic scan hits to summary (not queued)"),
    )
    p_workspace.add_argument("--limit", type=int, default=80, help=H("列表/扫描上限（默认 80）", "list/scan limit (default 80)"))
    ws_sub = p_workspace.add_subparsers(dest="workspace_action", metavar="action")

    p_ws_tasks = ws_sub.add_parser("tasks", help=H("列出托管待办（open）", "list managed todos (open)"))
    p_ws_tasks.add_argument("--all", action="store_true", help=H("含 done/dismissed/expired/snoozed", "include done/dismissed/expired/snoozed"))
    p_ws_tasks.add_argument("--cwd", help=H("工作区根目录", "workspace root"))
    p_ws_tasks.add_argument("--limit", type=int, default=80, help=H("显示上限", "display limit"))
    tasks_sub = p_ws_tasks.add_subparsers(dest="tasks_action", metavar="action")
    p_ws_tasks_purge = tasks_sub.add_parser("purge", help=H("清理终态待办", "purge terminal-state todos"))
    p_ws_tasks_purge.add_argument(
        "--older-than",
        type=int,
        default=None,
        metavar="DAYS",
        help=H("仅清理创建超过 N 天的终态", "only purge terminal todos older than N days"),
    )
    p_ws_tasks_purge.add_argument("--cwd", help=H("工作区根目录", "workspace root"))
    p_ws_tasks.set_defaults(func=cmd_workspace)
    p_ws_tasks_purge.set_defaults(func=cmd_workspace)

    p_ws_add = ws_sub.add_parser("add", help=H("添加托管待办（须 --why）", "add managed todo (requires --why)"))
    p_ws_add.add_argument("title", help=H("可读标题", "readable title"))
    p_ws_add.add_argument(
        "--why",
        required=True,
        help=H("为何值得占用注意力（必填）", "why it deserves attention (required)"),
    )
    p_ws_add.add_argument("--hint", default="", help=H("如何办完（可选）", "how to finish (optional)"))
    p_ws_add.add_argument("--cwd", help=H("工作区根目录", "workspace root"))
    p_ws_add.set_defaults(func=cmd_workspace)

    p_ws_done = ws_sub.add_parser("done", help=H("完成一条待办", "mark a todo done"))
    p_ws_done.add_argument("task_id", help=H("待办 id（支持前缀）", "todo id (prefix ok)"))
    p_ws_done.add_argument("--cwd", help=H("工作区根目录", "workspace root"))
    p_ws_done.set_defaults(func=cmd_workspace)

    p_ws_dismiss = ws_sub.add_parser("dismiss", help=H("丢弃一条待办", "dismiss a todo"))
    p_ws_dismiss.add_argument("task_id", help=H("待办 id（支持前缀）", "todo id (prefix ok)"))
    p_ws_dismiss.add_argument("--cwd", help=H("工作区根目录", "workspace root"))
    p_ws_dismiss.set_defaults(func=cmd_workspace)

    p_ws_snooze = ws_sub.add_parser("snooze", help=H("搁置一条待办", "snooze a todo"))
    p_ws_snooze.add_argument("task_id", help=H("待办 id（支持前缀）", "todo id (prefix ok)"))
    p_ws_snooze.add_argument(
        "--days",
        type=int,
        default=1,
        dest="snooze_days",
        help=H("搁置天数（默认 1）", "snooze days (default 1)"),
    )
    p_ws_snooze.add_argument("--cwd", help=H("工作区根目录", "workspace root"))
    p_ws_snooze.set_defaults(func=cmd_workspace)

    p_ws_scan = ws_sub.add_parser("scan", help=H("诊断扫描代码 TODO（未入队）", "diagnostic scan of code TODOs (not queued)"))
    p_ws_scan.add_argument("--cwd", help=H("工作区根目录", "workspace root"))
    p_ws_scan.add_argument("--limit", type=int, default=80, help=H("扫描上限", "scan limit"))
    p_ws_scan.set_defaults(func=cmd_workspace)

    p_ws_purge = ws_sub.add_parser("purge", help=H("清理终态待办", "purge terminal-state todos"))
    p_ws_purge.add_argument(
        "--older-than",
        type=int,
        default=None,
        metavar="DAYS",
        help=H("仅清理创建超过 N 天的终态", "only purge terminal todos older than N days"),
    )
    p_ws_purge.add_argument("--cwd", help=H("工作区根目录", "workspace root"))
    p_ws_purge.set_defaults(func=cmd_workspace)

    p_workspace.set_defaults(func=cmd_workspace)

    p_audit = sub.add_parser(
        "audit",
        help=H("[高级] [--since 7d] [--report PATH] [--cwd PATH]  审计摘要与报告", "[advanced] [--since 7d] [--report PATH] [--cwd PATH]  audit summary & report"),
        description=H("[高级] Token/费用、文件安全、记忆健康审计", "[advanced] token/cost, file safety, memory health audit"),
    )
    p_audit.add_argument("--since", help=H("统计起始，如 7d、24h、30m", "stats window start, e.g. 7d, 24h, 30m"))
    p_audit.add_argument(
        "--report",
        help=H("导出报告路径（.md Markdown；.html HTML）", "export report path (.md Markdown; .html HTML)"),
    )
    p_audit.add_argument("--days", type=int, default=7, help=H("报告中工作区快照天数（默认 7）", "workspace snapshot days in report (default 7)"))
    p_audit.add_argument("--cwd", help=H("工作区根目录", "workspace root"))
    p_audit.set_defaults(func=cmd_audit)

    p_logs = sub.add_parser(
        "logs",
        help=H("[高级] [--tail N] [--level LEVEL] [--path]  查看诊断日志", "[advanced] [--tail N] [--level LEVEL] [--path]  view diagnostic logs"),
        description=H("[高级] 查看本地诊断日志（data/logs/localagent.log）。\n与 LA audit（用量/护栏问责）不同：logs 用于排查运行时决策与降级。\n开发时可 LA --debug <command> 或设置 LA_LOG_LEVEL=DEBUG 盯 stderr。", "[advanced] view local diagnostic logs (data/logs/localagent.log).\nUnlike LA audit (usage/guardrails): logs debug runtime decisions & fallbacks.\nDev: LA --debug <command> or LA_LOG_LEVEL=DEBUG on stderr."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_logs.add_argument(
        "--tail",
        type=int,
        default=80,
        help=H("显示最近 N 行（默认 80；0 表示全部）", "show last N lines (default 80; 0 = all)"),
    )
    p_logs.add_argument(
        "--level",
        help=H("仅显示不低于该级别的行（如 DEBUG、INFO、WARNING）", "only lines at or above this level (e.g. DEBUG, INFO, WARNING)"),
    )
    p_logs.add_argument(
        "--path",
        action="store_true",
        help=H("只打印日志文件路径", "print log file path only"),
    )
    p_logs.set_defaults(func=cmd_logs)

    p_config = sub.add_parser(
        "config",
        help=H("[--provider …] | <file.json> | init|list|…  【主路径】快速配置 / 管理模型", "[--provider …] | <file.json> | init|list|…  [main] quick config / model mgmt"),
        description=H("【主路径】快速写入模型与 API Key。\n  la config --provider ollama --base_url http://localhost:11434 --model qwen3.5:4b\n  la config --TAVILY_API_KEY tvly-...\n  la config my.json\n  la config-example\n亦支持 init / list / add / remove / set-key 子命令。", "[main] quickly set model and API keys.\n  la config --provider ollama --base_url http://localhost:11434 --model qwen3.5:4b\n  la config --TAVILY_API_KEY tvly-...\n  la config my.json\n  la config-example\nAlso: init / list / add / remove / set-key."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    def _add_simple_config_flags(parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--provider", help=H("模型路径，如 ollama / openrouter / cursor", "model path, e.g. ollama / openrouter / cursor"))
        parser.add_argument(
            "--base_url",
            "--base-url",
            dest="base_url",
            help="API base URL",
        )
        parser.add_argument("--model", help=H("模型名称，如 qwen3.5:4b", "model name, e.g. qwen3.5:4b"))
        parser.add_argument(
            "--api_key",
            "--api-key",
            dest="api_key",
            help=H("该 provider 的 API Key", "API key for this provider"),
        )
        parser.add_argument("--timeout", type=float, help=H("请求超时秒数", "request timeout seconds"))
        parser.add_argument(
            "--TAVILY_API_KEY",
            "--tavily-api-key",
            dest="tavily_api_key",
            help=H("Tavily 联网搜索 Key（可为空字符串）", "Tavily web-search key (empty string ok)"),
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
        title=H("操作", "actions"),
    )
    p_config_init = config_sub.add_parser(
        "init",
        help=H("初始化或重新加载 config/model_servers.yaml", "init or reload config/model_servers.yaml"),
    )
    p_config_init.add_argument("--force", action="store_true", help=H("用模板覆盖已有配置文件", "overwrite existing config with template"))
    p_config_init.set_defaults(func=cmd_config)
    p_config_list = config_sub.add_parser("list", help=H("列出模型服务与独立 Key（脱敏）", "list model servers and standalone keys (redacted)"))
    p_config_list.set_defaults(func=cmd_config)

    p_config_set = config_sub.add_parser(
        "set",
        help=H("极简写入：--provider / --base_url / --model / --TAVILY_API_KEY …", "minimal set: --provider / --base_url / --model / --TAVILY_API_KEY …"),
    )
    _add_simple_config_flags(p_config_set)
    p_config_set.set_defaults(func=cmd_config)

    p_config_apply = config_sub.add_parser(
        "apply",
        help=H("<file.json>  从 JSON 文件加载配置", "<file.json>  load config from JSON file"),
    )
    p_config_apply.add_argument("config_file", help=H("JSON 配置文件路径", "JSON config file path"))
    p_config_apply.set_defaults(func=cmd_config)

    p_config_add = config_sub.add_parser(
        "add",
        help=H("添加/更新一条模型服务（JSON 或 --provider 参数）", "add/update a model server (JSON or --provider flags)"),
    )
    p_config_add.add_argument("json", nargs="?", help=H("JSON 对象，如 '{\"provider\":\"aiping\",...}'", "JSON object, e.g. '{\"provider\":\"aiping\",...}'"))
    p_config_add.add_argument("--provider", help=H("provider 名称（与 --model 等配合使用）", "provider name (use with --model etc.)"))
    p_config_add.add_argument(
        "--base-url",
        dest="base_url",
        help=H("OpenAI 兼容 API base URL", "OpenAI-compatible API base URL"),
    )
    p_config_add.add_argument("--api-key", dest="api_key", help="API Key")
    p_config_add.add_argument("--model", help=H("模型名称", "model name"))
    p_config_add.add_argument("--timeout", type=float, help=H("请求超时秒数（默认 120）", "request timeout seconds (default 120)"))
    p_config_add.set_defaults(func=cmd_config)

    p_config_remove = config_sub.add_parser("remove", help=H("<provider>  从列表删除一条模型服务", "<provider>  remove a model server from the list"))
    p_config_remove.add_argument("provider", help=H("provider 名称，如 openai / aiping", "provider name, e.g. openai / aiping"))
    p_config_remove.set_defaults(func=cmd_config)

    p_config_set_key = config_sub.add_parser(
        "set-key",
        help=H("<provider> [key]  仅更新 api_key（key 省略或 - 时从 stdin 读取）", "<provider> [key]  update api_key only (omit or - to read stdin)"),
    )
    p_config_set_key.add_argument(
        "provider",
        help=H("LA_MODEL_SERVERS 中的 provider，或 tavily / mem0", "provider in LA_MODEL_SERVERS, or tavily / mem0"),
    )
    p_config_set_key.add_argument(
        "value",
        nargs="?",
        help=H("API Key；省略或传 - 时从 stdin 读取", "API key; omit or pass - to read from stdin"),
    )
    p_config_set_key.set_defaults(func=cmd_config)
    p_config.set_defaults(func=cmd_config)

    p_config_example = sub.add_parser(
        "config-example",
        help=H("打印 config.example.json（复制后改写再用 la config <file>）", "print config.example.json (copy, edit, then la config <file>)"),
        description=H("输出极简配置模板 JSON", "print minimal config template JSON"),
    )
    p_config_example.set_defaults(func=cmd_config_example)

    p_setup = sub.add_parser(
        "setup",
        help=H("[--yes]  【主路径】安装 Ollama 并拉取 qwen3.5:4b（可跳过）", "[--yes]  [main] install Ollama and pull qwen3.5:4b (skippable)"),
        description=H("【主路径】检查本机 Ollama；未安装时询问是否本地安装，缺少默认模型时询问是否拉取。加 -y 跳过确认。", "[main] check local Ollama; offer install if missing, pull default model if needed. Use -y to skip prompts."),
    )
    p_setup.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help=H("无需确认，直接安装/拉取", "install/pull without confirmation"),
    )
    p_setup.set_defaults(func=cmd_setup)

    p_summarize = sub.add_parser(
        "summarize",
        help=H("<path…> [--no-chat] [--keep] [--resume]  文档速读；默认进入文档对话", "<path…> [--no-chat] [--keep] [--resume]  doc skim; enter doc chat by default"),
        description=H("针对本地文档的速读与文档对话（与 la chat「和助手聊」不同）。\n  默认：打印速读卡后进入 sum> 文档对话（TTY）。\n  --no-chat：仅速读（可多文件），不进入对话。\n支持 .txt / .md / .pdf / .xlsx。\n默认不入库；会话内 /keep 或 --keep 收藏到知识库（不每次追问）。\n  la summarize --list                 # 最近文档对话\n  la summarize <path> --resume        # 续聊\n", "Local document skim and doc chat (unlike la chat with the assistant).\n  Default: print skim card then enter sum> doc chat (TTY).\n  --no-chat: skim only (multi-file ok), no chat.\nSupports .txt / .md / .pdf / .xlsx.\nNot ingested by default; /keep or --keep bookmarks to knowledge (no prompt each time).\n  la summarize --list                 # recent doc chats\n  la summarize <path> --resume        # resume\n"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_summarize.add_argument(
        "paths",
        nargs="*",
        metavar="path",
        help=H("本地文件路径（多文件须加 --no-chat）", "local file path(s) (multi-file requires --no-chat)"),
    )
    p_summarize.add_argument(
        "--keep",
        action="store_true",
        help=H("速读后写入知识库（等同 LA ingest doc；默认不入库）", "ingest after skim (same as LA ingest doc; off by default)"),
    )
    p_summarize.add_argument(
        "--no-chat",
        action="store_true",
        help=H("只输出速读卡，不进入文档对话（可多文件）", "print skim card only, no doc chat (multi-file ok)"),
    )
    p_summarize.add_argument(
        "--out",
        metavar="FILE",
        help=H("将速读卡写入 Markdown 文件（常与 --no-chat 同用）", "write skim card to Markdown file (often with --no-chat)"),
    )
    p_summarize.add_argument(
        "--list",
        action="store_true",
        help=H("列出最近的文档对话会话", "list recent document chat sessions"),
    )
    p_summarize.add_argument(
        "--limit",
        type=int,
        default=20,
        help=H("--list 显示条数（默认 20）", "--list display count (default 20)"),
    )
    p_summarize.add_argument(
        "--resume",
        action="store_true",
        help=H("按路径续聊已有文档对话", "resume existing doc chat by path"),
    )
    p_summarize.add_argument(
        "--id",
        dest="id",
        metavar="SESSION_ID",
        help=H("按会话 id 续聊", "resume by session id"),
    )
    p_summarize.add_argument(
        "--provider",
        "-p",
        default="auto",
        help=H(
            f"文档对话模型路径: auto（默认）, {', '.join(config.VALID_PROVIDERS)}",
            f"doc-chat model path: auto (default), {', '.join(config.VALID_PROVIDERS)}",
        ),
    )
    p_summarize.add_argument(
        "--heuristic",
        action="store_true",
        help=H("强制使用本地启发式摘要（不调用模型；便于离线/测试）", "force local heuristic summary (no model; offline/testing)"),
    )
    p_summarize.set_defaults(func=cmd_summarize)

    p_news = sub.add_parser(
        "news",
        help=H("新闻嗅探：sync / brief / read / schedule …", "news sniff: sync / brief / read / schedule …"),
        description=H("从 BestBlogs RSS 同步精选 AI 资讯，生成今日简报并支持精读。\n  la news sync              # 拉取 RSS（TTY 下随后进入简报）\n  la news brief             # 今日简报（TTY 交互；--no-ui 刷屏）\n  la news read <id|url>     # 精读卡片（--keep 入库）\n  la news schedule on       # 每天 08:00 自动 sync（可 off）\n进入 la/chat 后，若早间已 sync，会提示「今日更新已准备好」。", "Sync curated AI news from BestBlogs RSS, daily brief, and deep-read.\n  la news sync              # pull RSS (then brief on TTY)\n  la news brief             # today's brief (TTY; --no-ui dump)\n  la news read <id|url>     # deep-read card (--keep to ingest)\n  la news schedule on       # daily 08:00 auto sync (or off)\nAfter la/chat, morning sync prompts that today's update is ready."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    news_sub = p_news.add_subparsers(dest="news_action", metavar="action")

    p_news_sync = news_sub.add_parser(
        "sync",
        help=H("从 RSS 同步最新条目（TTY 下随后进入简报）", "sync latest RSS items (then brief on TTY)"),
    )
    p_news_sync.add_argument("--url", default=None, help=H("覆盖默认 LA_NEWS_RSS_URL", "override default LA_NEWS_RSS_URL"))
    p_news_sync.add_argument(
        "--no-ui",
        action="store_true",
        help=H("仅同步，不进入交互简报（定时任务/脚本常用）", "sync only, no interactive brief (for cron/scripts)"),
    )
    p_news_sync.add_argument(
        "--provider",
        "-p",
        default="auto",
        help=H("随后进入简报时，精读深聊的模型路径（默认 auto）", "model path for deep-read chat after brief (default auto)"),
    )
    p_news_sync.set_defaults(func=_cmd_news)

    p_news_brief = news_sub.add_parser(
        "brief",
        help=H("今日简报（TTY 下交互浏览；--no-ui 一次性输出）", "today's brief (interactive on TTY; --no-ui one-shot)"),
    )
    p_news_brief.add_argument("--date", default=None, help=H("日期 YYYY-MM-DD（默认今天）", "date YYYY-MM-DD (default today)"))
    p_news_brief.add_argument("--limit", type=int, default=None, help=H("条数上限", "item limit"))
    p_news_brief.add_argument(
        "--plain",
        action="store_true",
        help=H("强制 Markdown 链接（不要 OSC 8）；常与 --no-ui 合用", "force Markdown links (no OSC 8); often with --no-ui"),
    )
    p_news_brief.add_argument(
        "--no-ui",
        action="store_true",
        help=H("不进入交互浏览器，一次性打印全部简报", "print full brief once; no interactive browser"),
    )
    p_news_brief.add_argument(
        "--provider",
        "-p",
        default="auto",
        help=H("精读深聊时的模型路径（默认 auto）", "model path for deep-read chat (default auto)"),
    )
    p_news_brief.set_defaults(func=_cmd_news)

    p_news_skim = news_sub.add_parser("skim", help=H("<id|url>  速读卡片", "<id|url>  skim card"))
    p_news_skim.add_argument("target", help=H("文章 id 或 URL", "article id or URL"))
    p_news_skim.add_argument("--plain", action="store_true")
    p_news_skim.set_defaults(func=_cmd_news)

    p_news_read = news_sub.add_parser("read", help=H("<id|url> [--keep]  精读卡片", "<id|url> [--keep]  deep-read card"))
    p_news_read.add_argument("target", help=H("文章 id 或 URL", "article id or URL"))
    p_news_read.add_argument("--keep", action="store_true", help=H("精读后写入知识库", "ingest after deep-read"))
    p_news_read.add_argument(
        "--heuristic",
        action="store_true",
        help=H("强制启发式摘要（不调模型）", "force heuristic summary (no model)"),
    )
    p_news_read.add_argument("--plain", action="store_true")
    p_news_read.set_defaults(func=_cmd_news)

    p_news_mark = news_sub.add_parser("mark", help="<id> bookmark|skip|read")
    p_news_mark.add_argument("target", help=H("文章 id 或 URL", "article id or URL"))
    p_news_mark.add_argument(
        "mark_action",
        choices=["bookmark", "skip", "read"],
        help=H("动作", "action"),
    )
    p_news_mark.set_defaults(func=_cmd_news)

    p_news_sched = news_sub.add_parser(
        "schedule",
        help=H("on|off|status  配置早间自动 sync", "on|off|status  morning auto-sync"),
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

    p_news_int = news_sub.add_parser("interests", help=H("查看/设置兴趣标签", "view/set interest tags"))
    p_news_int.add_argument(
        "--set",
        dest="set_interests",
        default=None,
        help=H("逗号分隔覆盖 interests", "comma-separated overwrite interests"),
    )
    p_news_int.add_argument("--add", default=None, help=H("追加一个兴趣词", "append one interest term"))
    p_news_int.add_argument("--mute", default=None, help=H("追加 mute 关键词", "append a mute keyword"))
    p_news_int.set_defaults(func=_cmd_news)

    news_sub.add_parser("status", help=H("同步与定时状态", "sync and schedule status")).set_defaults(func=_cmd_news)
    news_sub.add_parser("sources", help=H("查看默认 RSS 源", "show default RSS sources")).set_defaults(func=_cmd_news)
    p_news.set_defaults(func=_cmd_news)

    p_aware = sub.add_parser(
        "aware",
        help=H("本机世界感知（智能总结 / aware> 对话 / --detail / tick · 授权）", "local world awareness (smart summary / aware> chat / --detail / tick · grants)"),
        description=H("Aware：按源授权后感知本机变化（fs / browser / git / terminal）。\n  la aware                      # 智能总结后进入 aware> 感知对话\n  la aware --no-chat            # 只打印概览，不进对话\n  la aware --detail             # 展开分源探测明细（仍可进对话）\n  la aware --since 1w           # 时间窗内智能总结（如 3h/2d/1w/3m/1y，默认 1w）\n  la aware tick                 # 采集后总结；TTY 下可进 aware>\n  la aware grant all            # 授权（ungrant 解除）\n  la aware ungrant browser      # 停止监测某一源\n  la aware suggestion           # 查看建议\n  la aware suggestion approve|reject <id>|all\n可索引文件仅进 suggestion（须用户确认后 LA ingest doc）；绝不自动写入 kb/Cold。", "Aware: sense local changes after per-source grants (fs / browser / git / terminal).\n  la aware                      # smart summary then aware> chat\n  la aware --no-chat            # overview only, no chat\n  la aware --detail             # expand per-source probe details\n  la aware --since 1w           # windowed summary (3h/2d/1w/3m/1y; default 1w)\n  la aware tick                 # collect then summarize; TTY may enter aware>\n  la aware grant all            # grant (ungrant to revoke)\n  la aware ungrant browser      # stop monitoring a source\n  la aware suggestion           # list suggestions\n  la aware suggestion approve|reject <id>|all\nIndexable files only enter suggestion (confirm then LA ingest doc); never auto-write kb/Cold."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_aware.add_argument(
        "--since",
        nargs="?",
        const="1w",
        default=None,
        metavar="WINDOW",
        help=H("查看时间窗内变化：<N>h|<N>d|<N>w|<N>m|<N>y（如 3h、2d、1w；单独 --since 等同 1w）", "changes in window: <N>h|<N>d|<N>w|<N>m|<N>y (e.g. 3h, 2d, 1w; bare --since = 1w)"),
    )
    p_aware.add_argument(
        "--source",
        default=None,
        choices=["fs", "git", "terminal", "browser", "apps", "all"],
        help=H("只展示某一感知源（all=全部）", "show only one sense source (all = everything)"),
    )
    p_aware.add_argument(
        "--detail",
        action="store_true",
        help=H("展开分源探测明细（默认只显示智能总结）", "expand per-source probe details (default: smart summary only)"),
    )
    p_aware.add_argument(
        "--no-chat",
        action="store_true",
        help=H("只打印概览，不进入 aware> 感知对话", "print overview only; no aware> chat"),
    )
    p_aware.add_argument(
        "--provider",
        default="auto",
        help=H("感知对话模型路径（默认 auto）", "aware chat model path (default auto)"),
    )
    aware_sub = p_aware.add_subparsers(dest="aware_action", metavar="action")

    aware_sub.add_parser("status", help=H("授权与定时状态", "grants and schedule status")).set_defaults(func=_cmd_aware)

    p_aware_grant = aware_sub.add_parser("grant", help=H("授权一个或多个传感器", "grant one or more sensors"))
    p_aware_grant.add_argument(
        "sources",
        nargs="+",
        help="all | fs | git | terminal | browser | …",
    )
    p_aware_grant.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=H("敏感源跳过交互确认", "skip interactive confirm for sensitive sources"),
    )
    p_aware_grant.set_defaults(func=_cmd_aware)

    p_aware_ungrant = aware_sub.add_parser("ungrant", help=H("解除授权（停止监测）", "revoke grant (stop monitoring)"))
    p_aware_ungrant.add_argument("sources", nargs="+", help=H("<source> 或 all", "<source> or all"))
    p_aware_ungrant.set_defaults(func=_cmd_aware)

    p_aware_paths = aware_sub.add_parser("paths", help=H("管理 fs 监视路径", "manage fs watch paths"))
    paths_sub = p_aware_paths.add_subparsers(dest="paths_action", metavar="action")
    paths_sub.add_parser("list", help=H("列出路径", "list paths")).set_defaults(func=_cmd_aware)
    p_paths_add = paths_sub.add_parser("add", help=H("添加目录", "add directory"))
    p_paths_add.add_argument("path", help=H("目录路径", "directory path"))
    p_paths_add.set_defaults(func=_cmd_aware)
    p_paths_rm = paths_sub.add_parser("rm", help=H("移除目录", "remove directory"))
    p_paths_rm.add_argument("path", help=H("目录路径", "directory path"))
    p_paths_rm.set_defaults(func=_cmd_aware)
    p_aware_paths.set_defaults(func=_cmd_aware)

    p_aware_sched = aware_sub.add_parser("schedule", help=H("on|off|status  定时 tick", "on|off|status  scheduled tick"))
    p_aware_sched.add_argument(
        "schedule_action",
        nargs="?",
        default="status",
        choices=["on", "off", "status"],
    )
    p_aware_sched.add_argument(
        "--interval",
        type=int,
        default=None,
        help=H("间隔分钟（默认 15）", "interval minutes (default 15)"),
    )
    p_aware_sched.set_defaults(func=_cmd_aware)

    p_aware_tick = aware_sub.add_parser(
        "tick", help=H("采集并报告自上次探测以来的变化", "collect and report changes since last probe")
    )
    p_aware_tick.add_argument(
        "--source",
        default=None,
        choices=["fs", "git", "terminal", "browser", "apps"],
        help=H("只展示某一源", "show only one source"),
    )
    p_aware_tick.add_argument(
        "--detail",
        action="store_true",
        help=H("展开分源探测明细（默认只显示智能总结）", "expand per-source probe details (default: smart summary only)"),
    )
    p_aware_tick.add_argument(
        "--no-chat",
        action="store_true",
        help=H("只打印 tick 结果，不进入 aware> 感知对话", "print tick result only; no aware> chat"),
    )
    p_aware_tick.add_argument(
        "--provider",
        default="auto",
        help=H("感知对话模型路径（默认 auto）", "aware chat model path (default auto)"),
    )
    p_aware_tick.set_defaults(func=_cmd_aware)

    p_aware_sug = aware_sub.add_parser(
        "suggestion",
        help=H("建议：list | approve | reject", "suggestions: list | approve | reject"),
        description=(
            "  la aware suggestion\n"
            "  la aware suggestion list\n"
            "  la aware suggestion approve <id>|all\n"
            "  la aware suggestion reject <id>|all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sug_sub = p_aware_sug.add_subparsers(dest="suggestion_action", metavar="action")
    sug_sub.add_parser("list", help=H("列出建议", "list suggestions")).set_defaults(func=_cmd_aware)
    p_sug_approve = sug_sub.add_parser("approve", help=H("批准并执行建议", "approve and run suggestion"))
    p_sug_approve.add_argument("target", help=H("<id> 或 all", "<id> or all"))
    p_sug_approve.set_defaults(func=_cmd_aware)
    p_sug_reject = sug_sub.add_parser("reject", help=H("拒绝建议", "reject suggestion"))
    p_sug_reject.add_argument("target", help=H("<id> 或 all", "<id> or all"))
    p_sug_reject.set_defaults(func=_cmd_aware)
    p_aware_sug.set_defaults(func=_cmd_aware)

    p_aware_events = aware_sub.add_parser("events", help=H("事件日志（调试）", "event log (debug)"))
    p_aware_events.add_argument("--source", default=None, help=H("按 source 过滤", "filter by source"))
    p_aware_events.add_argument(
        "--since-hours",
        type=int,
        default=24,
        help=H("回溯小时数（默认 24）", "lookback hours (default 24)"),
    )
    p_aware_events.add_argument("--limit", type=int, default=50)
    p_aware_events.add_argument(
        "--raw",
        action="store_true",
        help=H("扁平明细（默认按源摘要）", "flat details (default: per-source summary)"),
    )
    p_aware_events.set_defaults(func=_cmd_aware)

    p_aware.set_defaults(func=_cmd_aware)

    p_polish = sub.add_parser(
        "polish",
        help=H("[--scene …] [--tone …] [--no-copy]  一键润色文案（默认复制主推到剪贴板）", "[--scene …] [--tone …] [--no-copy]  one-shot polish (copies pick to clipboard)"),
        description=H("一键润色：识别邮件 / 朋友圈 / 简历 / 商务对话场景与态度，给出主推 + 两个备选，并默认将主推复制到剪贴板。\n  la polish \"催一下进度的草稿\"\n  la polish --scene email --tone 更正式 --file draft.txt\n  echo \"草稿\" | la polish --no-copy\n会话内: /polish <草稿>", "One-shot polish: detect email / moments / resume / biz tone, pick + 2 alts, copy pick to clipboard by default.\n  la polish \"nudge on progress draft\"\n  la polish --scene email --tone more formal --file draft.txt\n  echo \"draft\" | la polish --no-copy\nIn session: /polish <draft>"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_polish.add_argument(
        "text",
        nargs="*",
        help=H("待润色草稿（也可 --file 或 stdin）", "draft to polish (or --file / stdin)"),
    )
    p_polish.add_argument(
        "--file",
        "-f",
        dest="file",
        help=H("从文件读取草稿", "read draft from file"),
    )
    p_polish.add_argument(
        "--scene",
        choices=["email", "moments", "resume", "biz"],
        help=H("强制场景（默认自动识别）", "force scene (default: auto-detect)"),
    )
    p_polish.add_argument(
        "--tone",
        help=H("语气要求，如：更正式 / 更口语 / 更短", "tone hint, e.g. more formal / more casual / shorter"),
    )
    p_polish.add_argument(
        "--no-copy",
        action="store_true",
        help=H("不写入剪贴板（脚本/管道场景）", "do not write clipboard (scripts/pipes)"),
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
