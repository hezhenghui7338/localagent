"""Agent tools."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from collections.abc import Callable

from localagent.knowledge.hybrid import get_hybrid_retriever
from localagent.memory.display import format_memory_hits
from localagent.memory.backend import get_memory_backend
from localagent.memory.query import list_memory_tags, query_memories
from localagent.memory.store import MemoryFact, get_memory_store
from localagent.tools.web_search import (
    augment_web_query,
    derive_search_params,
    resolve_web_search_provider,
    web_search,
)

logger = logging.getLogger(__name__)

_MEMORY_MISS = "未找到相关记忆。"
_KNOWLEDGE_MISS = "未找到相关知识片段。"
_ALL_MISS = "未在记忆、知识库索引或文档原文中找到相关信息。"


def _format_memory_hits(
    hits: list[dict[str, Any]],
    *,
    query: str = "",
    show_ids: bool = False,
    verbose: bool = False,
) -> str:
    return format_memory_hits(
        hits,
        query=query,
        show_ids=show_ids,
        verbose=verbose,
    )


def search_documents(query: str, *, top_k: int = 5, context_chars: int = 300) -> str:
    """Direct keyword search in kb/ files when RAG index misses."""
    from localagent import config
    from localagent.ingest.loader import load_file
    from localagent.ingest.sync_file import list_kb_files

    terms = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]{2,}", query.lower())
    if not terms:
        return ""

    hits: list[tuple[int, str]] = []
    for path in list_kb_files():
        # Images are textified at ingest time into Cold RAG; do not re-run VL here.
        if path.suffix.lower() in config.IMAGE_SUFFIXES:
            continue
        doc = load_file(path)
        if not doc:
            continue
        text_lower = doc.text.lower()
        score = sum(1 for term in terms if term in text_lower)
        if score == 0:
            continue

        snippet = ""
        for term in terms:
            idx = text_lower.find(term)
            if idx >= 0:
                start = max(0, idx - context_chars // 2)
                end = min(len(doc.text), idx + context_chars // 2)
                snippet = doc.text[start:end].strip()
                break
        if not snippet:
            snippet = doc.text[:context_chars].strip()

        hits.append((score, f"- [{score}] {doc.filename}\n  {snippet}"))

    if not hits:
        return ""
    hits.sort(key=lambda item: item[0], reverse=True)
    return "\n".join(line for _, line in hits[:top_k])


def _fact_to_hit(fact: MemoryFact, *, score: float = 1.0) -> dict[str, Any]:
    return {
        "id": fact.id,
        "text": fact.text,
        "score": score,
        "source_file": fact.source_file,
        "section_heading": fact.section_heading,
        "created_at": fact.created_at,
        "metadata": fact.metadata,
    }


def browse_memories(*, top_k: int = 8) -> str:
    """Return a recent sample from the memory store for meta/browse questions."""
    return query_memories_tool(sort="newest", limit=top_k)


def query_memories_tool(
    *,
    query: str = "",
    tags: list[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    sort: str = "newest",
    limit: int = 20,
    show_ids: bool = True,
    verbose: bool = False,
    time_field: str = "effective",
) -> str:
    """Query memories with tag/time filters, sorting, and optional semantic match."""
    total = get_memory_backend().count()
    if total == 0:
        return "记忆库为空，尚未保存任何记忆。"

    sort_order = sort if sort in ("newest", "oldest", "relevance") else "newest"
    field = time_field if time_field in ("effective", "recorded") else "effective"
    hits = query_memories(
        query=query,
        tags=tags,
        since=since,
        until=until,
        sort=sort_order,  # type: ignore[arg-type]
        limit=limit,
        time_field=field,  # type: ignore[arg-type]
    )

    filters: list[str] = []
    if query:
        filters.append(f"语义: {query}")
    if tags:
        filters.append("标签: " + ", ".join(tags))
    if since:
        filters.append(f"自 {since}")
    if until:
        filters.append(f"至 {until}")
    filter_hint = f"（{' · '.join(filters)}）" if filters else ""

    if not hits:
        tag_summary = list_memory_tags(limit=10)
        tag_hint = ""
        if tag_summary:
            tag_hint = "\n可用标签: " + ", ".join(f"{tag}({count})" for tag, count in tag_summary)
        return f"未找到匹配记忆{filter_hint}。记忆库共 {total} 条。{tag_hint}"

    header = f"记忆库共 {total} 条，返回 {len(hits)} 条{filter_hint}"
    body = format_memory_hits(
        hits,
        query=query,
        show_ids=show_ids,
        verbose=verbose,
    )
    return f"{header}\n\n{body}"


def retain_memory(content: str, *, source: str = "chat_explicit") -> str:
    """Immediately retain a user-stated fact into long-term memory."""
    text = content.strip()
    if not text:
        return "未提供可记住的内容。"

    from localagent.memory.save import save_facts
    from localagent.memory.value_filter import filter_facts

    facts = filter_facts([text])
    if not facts:
        # Explicit "记住/记录一下" should still persist short personal facts.
        facts = [text]
    ids = save_facts(facts, metadata={"source": source, "type": "fact"})
    if not ids:
        return "记忆写入失败，请稍后重试。"
    return f"已记住并写入长期记忆：{facts[0]}"


def search_memory(
    query: str,
    *,
    top_k: int = 5,
    fallback: bool = True,
    show_ids: bool = False,
    verbose: bool = False,
) -> str:
    from localagent.logging_setup import truncate_for_log

    backend = get_memory_backend()
    hits = backend.recall(query, max_results=top_k)
    logger.info(
        "search_memory backend=%s hits=%s fallback=%s",
        backend.backend_name(),
        len(hits),
        fallback,
    )
    logger.debug("search_memory query=%s", truncate_for_log(query))
    if hits:
        return _format_memory_hits(
            hits,
            query=query,
            show_ids=show_ids,
            verbose=verbose,
        )

    if not fallback:
        return _MEMORY_MISS

    knowledge = search_knowledge(query, top_k=top_k, fallback=False)
    if knowledge != _KNOWLEDGE_MISS:
        logger.info("search_memory miss→knowledge")
        return f"（记忆未命中，以下为知识库检索结果）\n{knowledge}"

    from localagent import config as la_config

    if la_config.DOC_KEYWORD_FALLBACK:
        documents = search_documents(query, top_k=top_k)
        if documents:
            logger.info("search_memory miss→documents")
            return f"（记忆和 RAG 均未命中，以下为文档原文关键词补充检索）\n{documents}"

    logger.info("search_memory miss (all)")
    return _ALL_MISS


def search_knowledge(
    query: str,
    *,
    top_k: int = 5,
    fallback: bool = True,
    since: str | None = None,
    until: str | None = None,
    conversation_only: bool = False,
    source_file: str | None = None,
) -> str:
    hits = get_hybrid_retriever().retrieve(
        query,
        top_k=top_k,
        since=since,
        until=until,
        conversation_only=conversation_only,
        source_file=source_file,
    )
    if hits:
        from localagent.knowledge.time_filter import format_recorded_label

        lines = []
        for h in hits:
            meta = h.get("metadata", {}) or {}
            heading = meta.get("heading", "")
            source = meta.get("source_file", "")
            origin = str(meta.get("origin") or "").strip()
            kind = str(meta.get("chunk_kind") or "").strip()
            title = str(meta.get("title") or "").strip()
            date_label = format_recorded_label(meta)
            label_parts: list[str] = []
            if origin:
                label_parts.append(origin)
            if kind == "summary":
                label_parts.append("摘要")
            if date_label:
                label_parts.append(date_label)
            prefix = f"[{'/'.join(label_parts)}] " if label_parts else ""
            display_source = title or source
            if title and source and title not in source:
                display_source = f"{title} ({source})"
            lines.append(
                f"- [{h['score_rrf']:.3f}] {prefix}{heading} ({display_source})\n"
                f"  {h['text'][:300]}"
            )
        return "\n".join(lines)

    if not fallback:
        return _KNOWLEDGE_MISS

    from localagent import config as la_config

    if la_config.DOC_KEYWORD_FALLBACK and not (since or until or conversation_only):
        documents = search_documents(query, top_k=top_k)
        if documents:
            return f"（知识库索引未命中，以下为文档原文关键词补充检索）\n{documents}"

    return _KNOWLEDGE_MISS


def _empty_archive_window_message(
    *,
    since: str | None,
    until: str | None,
) -> str:
    window = " · ".join(
        part
        for part in (
            f"自 {since}" if since else "",
            f"至 {until}" if until else "",
        )
        if part
    )
    hint = f"（{window}）" if window else ""
    return f"该时段无对话归档{hint}。"


def list_knowledge_in_range(
    *,
    since: str | None = None,
    until: str | None = None,
    limit: int = 40,
) -> str:
    """List Cold conversation archives in a recorded_at window (browse by time)."""
    hits = get_hybrid_retriever().list_conversations_in_range(
        since=since,
        until=until,
        limit=limit,
    )
    if not hits:
        return _empty_archive_window_message(since=since, until=until)

    from localagent.knowledge.time_filter import format_recorded_label

    lines = []
    for h in hits:
        meta = h.get("metadata", {}) or {}
        origin = str(meta.get("origin") or "").strip()
        kind = str(meta.get("chunk_kind") or "").strip()
        title = str(meta.get("title") or meta.get("source_file") or "").strip()
        date_label = format_recorded_label(meta)
        label_parts = [p for p in (origin, "摘要" if kind == "summary" else "", date_label) if p]
        prefix = f"[{'/'.join(label_parts)}] " if label_parts else ""
        lines.append(f"- {prefix}{title}\n  {h['text'][:400]}")
    return "\n".join(lines)


def list_user_questions_in_range(
    *,
    since: str | None = None,
    until: str | None = None,
    limit: int = 40,
) -> str:
    """List user questions from Cold conversation body chunks in a date window."""
    hits = get_hybrid_retriever().list_user_questions_in_range(
        since=since,
        until=until,
        limit=limit,
    )
    if not hits:
        return _empty_archive_window_message(since=since, until=until)

    from localagent.knowledge.time_filter import format_recorded_label

    lines = []
    for h in hits:
        meta = h.get("metadata", {}) or {}
        origin = str(meta.get("origin") or "").strip()
        date_label = format_recorded_label(meta)
        label_parts = [p for p in (origin, date_label) if p]
        prefix = f"[{'/'.join(label_parts)}] " if label_parts else ""
        question = " ".join(str(h.get("text") or "").split())
        lines.append(f"- {prefix}{question[:240]}")
    return "\n".join(lines)


def deep_search(
    topic: str,
    *,
    rounds: int = 3,
    on_status: Callable[[str], None] | None = None,
) -> str:
    """Multi-round research: search → synthesize."""
    from localagent.models.router import ChatMessage, get_model_router

    def _status(message: str) -> None:
        if on_status is not None:
            on_status(message)

    router = get_model_router()
    queries = [topic, f"{topic} 最新进展", f"{topic} 对比分析"]
    all_evidence: list[str] = []
    for index, q in enumerate(queries[:rounds], start=1):
        _status(f"联网搜索 ({index}/{min(rounds, len(queries))}): {q[:40]}")
        evidence = web_search(q)
        all_evidence.append(f"## Query: {q}\n{evidence}")

    from localagent.i18n import resolve_lang, t

    _status(
        "Synthesizing research report…"
        if resolve_lang() == "en"
        else "综合多轮结果，撰写研究报告…"
    )
    synthesis_prompt = t("prompt.deep_report", topic=topic) + "\n\n".join(all_evidence)
    return router.chat([ChatMessage(role="user", content=synthesis_prompt)], temperature=0.4, usage_command="deepsearch")


def reflect_memory(query: str) -> str:
    """Reason over memories + knowledge: recall → RAG → synthesize."""
    backend = get_memory_backend()
    answer = backend.reflect(query)
    if answer:
        return answer
    return "未能从记忆与知识库中推理出答案。"


def query_memory_graph(query: str, *, verbose: bool = False) -> str:
    """Precise graph query: counts / aggregations / multi-hop via Neo4j Cypher."""
    from localagent.memory.graph import format_precise_result, precise_graph_query
    from localagent.memory.graph.neo4j_store import neo4j_enabled

    if not neo4j_enabled():
        return (
            "Neo4j 精确图查询未启用（设 LA_NEO4J=1，"
            "并 pip install 'la-localagent[neo4j]' 或 LA_NEO4J_URI=memory://）。"
            "计数/聚合类问题请勿用 search_memory 估算数字。"
        )
    result = precise_graph_query(query, fallback_hybrid=True)
    return format_precise_result(result, verbose=verbose)


def workspace_context_tool(*, days: int = 7) -> str:
    """Agent tool: workspace git/files/managed-tasks summary."""
    from localagent.workspace.context import workspace_context

    return workspace_context(days=days)


def workspace_task_tool(
    action: str,
    *,
    title: str = "",
    rationale: str = "",
    task_id: str = "",
    days: int = 1,
    complete_hint: str = "",
    evidence: str = "",
) -> str:
    """Agent tool: list / add / propose / done / dismiss / snooze managed workspace tasks."""
    from localagent.workspace.tasks import (
        TaskRejected,
        add_task,
        dismiss,
        done,
        format_open_tasks,
        propose_task,
        snooze,
    )

    act = (action or "").strip().lower()
    if act in ("list", "tasks", ""):
        return format_open_tasks(limit=20, verbose=True)
    if act == "add":
        try:
            task = add_task(
                title,
                rationale,
                source="user",
                complete_hint=complete_hint,
                evidence=evidence,
            )
        except TaskRejected as exc:
            return f"未创建待办: {exc}"
        return f"已添加托管待办 [{task.id}] {task.title}\n为何: {task.rationale}\n→ done {task.id}"
    if act == "propose":
        try:
            task = propose_task(
                title,
                rationale,
                complete_hint=complete_hint,
                evidence=evidence,
            )
        except TaskRejected as exc:
            return f"未提议待办: {exc}"
        return (
            f"已提议重大待办 [{task.id}] {task.title}\n"
            f"为何: {task.rationale}\n"
            f"→ 用户可 la workspace done {task.id}"
        )
    if act == "done":
        task = done(task_id)
        if task is None:
            return "未找到该待办"
        return f"已完成 [{task.id}] {task.title}"
    if act == "dismiss":
        task = dismiss(task_id)
        if task is None:
            return "未找到该待办"
        return f"已丢弃 [{task.id}] {task.title}"
    if act == "snooze":
        task = snooze(task_id, days=max(1, int(days or 1)))
        if task is None:
            return "未找到该待办"
        return f"已搁置 [{task.id}] {task.title} → {(task.snooze_until or '')[:10]}"
    return (
        "未知 action。可用: list / add / propose / done / dismiss / snooze。"
        "add/propose 必须提供 title + rationale（充分理由）；"
        "propose 仅用于重大问题（每日上限），禁止把代码扫描结果批量入队。"
    )


def run_shell(command: str, *, cwd: str | None = None, timeout: float | None = None) -> str:
    """Agent tool: run a shell command in the workspace."""
    from localagent.tools.shell import run_shell_tool

    return run_shell_tool(command, cwd=cwd, timeout=timeout)


def write_file(
    path: str,
    content: str,
    *,
    mode: str = "overwrite",
    cwd: str | None = None,
) -> str:
    """Agent tool: create or update a file in the workspace."""
    from localagent.tools.files import write_file_tool

    return write_file_tool(path, content, mode=mode, cwd=cwd)


def read_file(
    path: str,
    *,
    offset: int | None = None,
    limit: int | None = None,
    cwd: str | None = None,
) -> str:
    """Agent tool: read a workspace file with optional line window."""
    from localagent.tools.files import read_file_tool

    return read_file_tool(path, offset=offset, limit=limit, cwd=cwd)


def edit_file(
    path: str,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
    cwd: str | None = None,
) -> str:
    """Agent tool: exact string replace in a workspace file."""
    from localagent.tools.files import edit_file_tool

    return edit_file_tool(
        path,
        old_string,
        new_string,
        replace_all=replace_all,
        cwd=cwd,
    )


def glob_files(
    pattern: str,
    *,
    path: str | None = None,
    cwd: str | None = None,
    max_results: int = 100,
) -> str:
    """Agent tool: find files by glob pattern."""
    from localagent.tools.search import glob_tool

    return glob_tool(pattern, path=path, cwd=cwd, max_results=max_results)


def grep_files(
    pattern: str,
    *,
    path: str | None = None,
    glob: str | None = None,
    output_mode: str = "content",
    head_limit: int = 50,
    case_insensitive: bool = False,
    cwd: str | None = None,
) -> str:
    """Agent tool: search file contents with regex."""
    from localagent.tools.search import grep_tool

    return grep_tool(
        pattern,
        path=path,
        glob=glob,
        output_mode=output_mode,
        head_limit=head_limit,
        case_insensitive=case_insensitive,
        cwd=cwd,
    )


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "retain_memory",
        "description": (
            "将用户明确要求记住的事实立即写入长期记忆；"
            "用于「记住/记录一下/记下」等指令，写入后可跨会话召回"
        ),
        "parameters": {"content": "要记住的事实内容"},
    },
    {
        "name": "search_memory",
        "description": "搜索用户长期记忆；未命中时自动回退到知识库 RAG 与文档原文",
        "parameters": {"query": "搜索关键词"},
    },
    {
        "name": "search_knowledge",
        "description": (
            "搜索知识库文档与对话归档；未命中时自动回退到文档原文关键词检索。"
            "按某年某月浏览「问过什么」时请传 since/until（YYYY-MM-DD）"
        ),
        "parameters": {
            "query": "搜索关键词",
            "since": "可选，起始日期 YYYY-MM-DD（对话发生时间）",
            "until": "可选，结束日期 YYYY-MM-DD",
        },
    },
    {
        "name": "web_search",
        "description": (
            "联网搜索最新信息，用于时效性、新闻、天气、外部资料类问题（默认免费可用）。"
            "天气查询用「城市 + 今天/明天」（如「深圳 今天天气」），不要写完整年份日期；"
            "其他时效问题可含地点与日期；返回结果会标注时效核对，过期条目不可当作当前事实"
        ),
        "parameters": {"query": "搜索关键词（含地点与日期更佳）"},
    },
    {
        "name": "reflect_memory",
        "description": (
            "综合推理：先多跳召回长期记忆，再检索知识库，最后归纳回答；"
            "适用于需要结合个人记忆与文档证据的跨条问题"
        ),
        "parameters": {"query": "需要推理的问题"},
    },
    {
        "name": "query_memory_graph",
        "description": (
            "精确图查询（Neo4j/Cypher）：用于「多少次/几个/一共/列出所有/同时提到」等"
            "计数、聚合与可形式化多跳；返回计算结果而非文本采样。"
            "禁止用 search_memory 估算数字；开放语义问仍用 search_memory"
        ),
        "parameters": {"query": "精确问题（含实体名）"},
    },
    {
        "name": "workspace_context",
        "description": (
            "获取工作区上下文：最近修改的文件、Git 状态与提交、托管待办队列；"
            "用于「我最近干了啥、git 怎样、有什么待办」类问题。"
            "正式待办来自托管队列（非代码 TODO 扫描）；完成/添加请用 workspace_task"
        ),
        "parameters": {"days": "可选，最近几天内的文件变更，默认 7"},
    },
    {
        "name": "workspace_task",
        "description": (
            "管理工作区托管待办：list / add / propose / done / dismiss / snooze。"
            "add：用户明确要求记下待办时用（须 rationale 说明为何重要）；"
            "propose：仅当发现重大问题（测试持续失败、配置失效、安全/数据风险）时提议，须充分 rationale，每日有上限；"
            "禁止把代码里的 TODO/FIXME 扫描结果批量入队。"
            "done/dismiss/snooze 需要 task_id。"
        ),
        "parameters": {
            "action": "list|add|propose|done|dismiss|snooze",
            "title": "add/propose 时的可读标题",
            "rationale": "add/propose 必填：为何值得占用用户注意力",
            "task_id": "done/dismiss/snooze 时的待办 id",
            "days": "snooze 搁置天数，默认 1",
            "complete_hint": "可选，如何办完",
            "evidence": "可选，旁证如 path:line",
        },
    },
    {
        "name": "query_memories",
        "description": (
            "浏览或查询本地记忆库：支持按标签、时间范围过滤，按时间或相关度排序，"
            "以及内容语义匹配；用于「记忆里有什么、按标签查看、某段时间的记忆」类问题。"
            "「某月问过/聊过什么」请传 since/until；对话发生时间过滤用 recorded"
        ),
        "parameters": {
            "query": "可选，语义搜索关键词",
            "tags": "可选，标签列表，如 [\"偏好\", \"工作\"]",
            "since": "可选，起始日期 YYYY-MM-DD",
            "until": "可选，结束日期 YYYY-MM-DD",
            "sort": "可选，newest（默认）/ oldest / relevance",
            "limit": "可选，返回条数，默认 20",
            "time_field": "可选，effective（默认）或 recorded（对话发生时间）",
        },
    },
    {
        "name": "read_file",
        "description": (
            "读取工作区内的文本文件（带行号）；支持 offset/limit 分页。"
            "查看文件内容时优先用本工具，不要用 run_shell 的 cat/head"
        ),
        "parameters": {
            "path": "文件路径（相对工作区或绝对路径）",
            "offset": "可选，起始行号（从 1 开始）",
            "limit": "可选，最多读取行数",
            "cwd": "可选，工作目录（默认 LA_WORKSPACE 或当前目录）",
        },
    },
    {
        "name": "glob",
        "description": (
            "按文件名/路径 glob 模式查找工作区文件（按修改时间排序）。"
            "找文件时优先用本工具，不要用 run_shell 的 find"
        ),
        "parameters": {
            "pattern": "glob 模式，如 **/*.py 或 src/**/*.ts",
            "path": "可选，限制在工作区内的子目录",
            "cwd": "可选，工作目录（默认 LA_WORKSPACE 或当前目录）",
        },
    },
    {
        "name": "grep",
        "description": (
            "在工作区文件内容中用正则搜索（返回 path:line:内容）。"
            "搜代码/符号时优先用本工具，不要用 run_shell 的 grep/rg"
        ),
        "parameters": {
            "pattern": "正则表达式",
            "path": "可选，限制文件或子目录",
            "glob": "可选，文件名过滤，如 *.py",
            "output_mode": "可选，content（默认）/ files_with_matches / count",
            "head_limit": "可选，最多返回条数，默认 50",
            "case_insensitive": "可选，是否忽略大小写，默认 false",
            "cwd": "可选，工作目录（默认 LA_WORKSPACE 或当前目录）",
        },
    },
    {
        "name": "edit_file",
        "description": (
            "精确字符串替换编辑工作区已有文件（old_string 须唯一匹配，除非 replace_all）。"
            "修改已有文件时优先用本工具；新建或整文件覆盖用 write_file；不要用 run_shell 的 sed"
        ),
        "parameters": {
            "path": "文件路径（相对工作区或绝对路径）",
            "old_string": "要替换的原文（须与文件完全一致）",
            "new_string": "替换后的新文本",
            "replace_all": "可选，true 时替换所有匹配，默认 false",
            "cwd": "可选，工作目录（默认 LA_WORKSPACE 或当前目录）",
        },
    },
    {
        "name": "write_file",
        "description": (
            "在工作区创建或整文件覆盖/追加写入；"
            "新建文件或需要重写整文件时使用；局部修改优先 edit_file"
        ),
        "parameters": {
            "path": "文件路径（相对工作区或绝对路径）",
            "content": "要写入的文本内容",
            "mode": "可选，overwrite（默认，覆盖）或 append（追加）",
            "cwd": "可选，工作目录（默认 LA_WORKSPACE 或当前目录）",
        },
    },
    {
        "name": "run_shell",
        "description": (
            "在工作区目录执行 shell 命令并返回输出；"
            "用于运行测试/构建、包管理、git 等。"
            "读文件用 read_file，找文件用 glob，搜内容用 grep，改文件用 edit_file/write_file，不要用本工具替代它们"
        ),
        "parameters": {
            "command": "要执行的 shell 命令，如 pytest tests/ -q",
            "cwd": "可选，工作目录（默认 LA_WORKSPACE 或当前目录）",
        },
    },
    {
        "name": "summarize_document",
        "description": (
            "原子速读本地文档（txt/md/pdf/xlsx）：最多三句话 + 带章节/页索引的结构化要点。"
            "默认不入库；仅当用户明确要求收藏/入库时才传 keep=true。"
            "需要多轮追问时，引导用户运行 `la summarize <path>` 进入文档对话（sum>），不要假装已进入会话。"
            "不要在总结后主动追问是否入库；若用户问为何搜不到/没入库，说明默认不入库并告知 "
            "会话内 /keep 或 `la summarize <path> --keep`"
        ),
        "parameters": {
            "path": "文件路径（相对工作区或绝对路径）",
            "keep": "可选，true 时总结后写入知识库，默认 false",
            "cwd": "可选，工作目录（默认 LA_WORKSPACE 或当前目录）",
        },
    },
    {
        "name": "news_brief",
        "description": (
            "获取今日新闻简报（BestBlogs RSS 精选池经本地兴趣重排）。"
            "用于「今天有什么新闻/早报/资讯」；每条含可点击原文链接。"
            "若库为空请先提示用户运行 la news sync"
        ),
        "parameters": {
            "date": "可选，日期 YYYY-MM-DD，默认今天",
            "limit": "可选，条数上限，默认按用户 brief_size",
        },
    },
    {
        "name": "news_read",
        "description": (
            "精读一篇新闻：抓取正文并生成总结卡片；默认不入库。"
            "仅当用户明确要求入库时传 keep=true"
        ),
        "parameters": {
            "id_or_url": "文章 id（如 n_abc…）或原文 URL",
            "keep": "可选，true 时写入知识库，默认 false",
        },
    },
    {
        "name": "news_mark",
        "description": "标记新闻：bookmark 收藏 / skip 不感兴趣 / read 已读",
        "parameters": {
            "id_or_url": "文章 id 或 URL",
            "action": "bookmark | skip | read",
        },
    },
]


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    if name == "retain_memory":
        content = str(
            arguments.get("content")
            or arguments.get("fact")
            or arguments.get("text")
            or arguments.get("query")
            or ""
        )
        return retain_memory(content)
    if name == "search_memory":
        return search_memory(arguments.get("query", ""))
    if name == "search_knowledge":
        sk_kwargs: dict[str, Any] = {}
        if arguments.get("since"):
            sk_kwargs["since"] = arguments.get("since")
        if arguments.get("until"):
            sk_kwargs["until"] = arguments.get("until")
        if arguments.get("source_file"):
            sk_kwargs["source_file"] = arguments.get("source_file")
        return search_knowledge(arguments.get("query", ""), **sk_kwargs)
    if name == "web_search":
        return web_search(arguments.get("query", ""))
    if name == "reflect_memory":
        return reflect_memory(arguments.get("query", ""))
    if name == "query_memory_graph":
        return query_memory_graph(arguments.get("query", ""))
    if name == "workspace_context":
        days_raw = arguments.get("days", 7)
        try:
            days = int(days_raw)
        except (TypeError, ValueError):
            days = 7
        return workspace_context_tool(days=days)
    if name == "workspace_task":
        days_raw = arguments.get("days", 1)
        try:
            snooze_days = int(days_raw)
        except (TypeError, ValueError):
            snooze_days = 1
        return workspace_task_tool(
            str(arguments.get("action") or "list"),
            title=str(arguments.get("title") or ""),
            rationale=str(arguments.get("rationale") or arguments.get("why") or ""),
            task_id=str(arguments.get("task_id") or arguments.get("id") or ""),
            days=snooze_days,
            complete_hint=str(arguments.get("complete_hint") or ""),
            evidence=str(arguments.get("evidence") or ""),
        )
    if name == "query_memories":
        tags_raw = arguments.get("tags")
        tags: list[str] | None = None
        if isinstance(tags_raw, list):
            tags = [str(tag) for tag in tags_raw if str(tag).strip()]
        elif isinstance(tags_raw, str) and tags_raw.strip():
            tags = [part.strip() for part in tags_raw.split(",") if part.strip()]
        limit_raw = arguments.get("limit", 20)
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 20
        return query_memories_tool(
            query=str(arguments.get("query") or ""),
            tags=tags,
            since=arguments.get("since"),
            until=arguments.get("until"),
            sort=str(arguments.get("sort") or "newest"),
            limit=limit,
            show_ids=True,
            time_field=str(arguments.get("time_field") or "effective"),
        )
    if name == "write_file":
        path = str(arguments.get("path") or "").strip()
        content = str(arguments.get("content") or "")
        mode = str(arguments.get("mode") or "overwrite")
        cwd = arguments.get("cwd")
        cwd_str = str(cwd).strip() if cwd else None
        return write_file(path, content, mode=mode, cwd=cwd_str)
    if name == "read_file":
        path = str(arguments.get("path") or "").strip()
        cwd = arguments.get("cwd")
        cwd_str = str(cwd).strip() if cwd else None
        offset = arguments.get("offset")
        limit = arguments.get("limit")
        offset_val: int | None = None
        limit_val: int | None = None
        if offset is not None and str(offset).strip() != "":
            try:
                offset_val = int(offset)
            except (TypeError, ValueError):
                return "错误: offset 必须是整数。"
        if limit is not None and str(limit).strip() != "":
            try:
                limit_val = int(limit)
            except (TypeError, ValueError):
                return "错误: limit 必须是整数。"
        return read_file(path, offset=offset_val, limit=limit_val, cwd=cwd_str)
    if name == "edit_file":
        path = str(arguments.get("path") or "").strip()
        old_string = str(arguments.get("old_string") or "")
        new_string = str(arguments.get("new_string") if "new_string" in arguments else "")
        replace_all = bool(arguments.get("replace_all"))
        cwd = arguments.get("cwd")
        cwd_str = str(cwd).strip() if cwd else None
        return edit_file(
            path,
            old_string,
            new_string,
            replace_all=replace_all,
            cwd=cwd_str,
        )
    if name == "glob":
        pattern = str(arguments.get("pattern") or arguments.get("query") or "").strip()
        path = arguments.get("path")
        path_str = str(path).strip() if path else None
        cwd = arguments.get("cwd")
        cwd_str = str(cwd).strip() if cwd else None
        max_raw = arguments.get("max_results", 100)
        try:
            max_results = int(max_raw)
        except (TypeError, ValueError):
            max_results = 100
        return glob_files(pattern, path=path_str, cwd=cwd_str, max_results=max_results)
    if name == "grep":
        pattern = str(arguments.get("pattern") or arguments.get("query") or "").strip()
        path = arguments.get("path")
        path_str = str(path).strip() if path else None
        glob_filter = arguments.get("glob")
        glob_str = str(glob_filter).strip() if glob_filter else None
        cwd = arguments.get("cwd")
        cwd_str = str(cwd).strip() if cwd else None
        head_raw = arguments.get("head_limit", 50)
        try:
            head_limit = int(head_raw)
        except (TypeError, ValueError):
            head_limit = 50
        case_raw = arguments.get("case_insensitive", False)
        if isinstance(case_raw, str):
            case_insensitive = case_raw.strip().lower() in {"1", "true", "yes", "on"}
        else:
            case_insensitive = bool(case_raw)
        return grep_files(
            pattern,
            path=path_str,
            glob=glob_str,
            output_mode=str(arguments.get("output_mode") or "content"),
            head_limit=head_limit,
            case_insensitive=case_insensitive,
            cwd=cwd_str,
        )
    if name == "run_shell":
        command = str(arguments.get("command") or "").strip()
        cwd = arguments.get("cwd")
        cwd_str = str(cwd).strip() if cwd else None
        timeout_raw = arguments.get("timeout")
        timeout_val: float | None = None
        if timeout_raw is not None:
            try:
                timeout_val = float(timeout_raw)
            except (TypeError, ValueError):
                timeout_val = None
        return run_shell(command, cwd=cwd_str, timeout=timeout_val)
    if name == "summarize_document":
        from localagent.summarize.document import summarize_document_tool

        path = str(arguments.get("path") or "").strip()
        cwd = arguments.get("cwd")
        cwd_str = str(cwd).strip() if cwd else None
        keep_raw = arguments.get("keep", False)
        if isinstance(keep_raw, str):
            keep = keep_raw.strip().lower() in {"1", "true", "yes", "on"}
        else:
            keep = bool(keep_raw)
        return summarize_document_tool(path, keep=keep, cwd=cwd_str)
    if name == "news_brief":
        from localagent.news.brief import build_brief

        date = str(arguments.get("date") or "").strip() or None
        limit_raw = arguments.get("limit")
        limit: int | None = None
        if limit_raw is not None and str(limit_raw).strip():
            try:
                limit = int(limit_raw)
            except (TypeError, ValueError):
                limit = None
        text, _ranked = build_brief(since_date=date, limit=limit, plain_links=True)
        return text
    if name == "news_read":
        from localagent.news.read import read_article

        target = str(
            arguments.get("id_or_url")
            or arguments.get("id")
            or arguments.get("url")
            or ""
        ).strip()
        keep_raw = arguments.get("keep", False)
        if isinstance(keep_raw, str):
            keep = keep_raw.strip().lower() in {"1", "true", "yes", "on"}
        else:
            keep = bool(keep_raw)
        result = read_article(target, keep=keep, plain_links=True)
        if result.error:
            return f"错误: {result.error}"
        return result.markdown
    if name == "news_mark":
        from localagent.news.mark import mark_article

        target = str(
            arguments.get("id_or_url")
            or arguments.get("id")
            or arguments.get("url")
            or ""
        ).strip()
        action = str(arguments.get("action") or "").strip()
        _art, msg = mark_article(target, action)
        return msg if _art else f"错误: {msg}"
    return f"未知工具: {name}"
