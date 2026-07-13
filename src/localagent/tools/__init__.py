"""Agent tools."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import httpx

from collections.abc import Callable

from localagent import config
from localagent.audit.usage import log_usage
from localagent.knowledge.hybrid import get_hybrid_retriever
from localagent.memory.display import format_memory_hits
from localagent.memory.backend import get_memory_backend
from localagent.memory.query import list_memory_tags, query_memories
from localagent.memory.store import MemoryFact, get_memory_store

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
    from localagent.ingest.loader import load_file
    from localagent.ingest.sync_file import list_kb_files

    terms = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]{2,}", query.lower())
    if not terms:
        return ""

    hits: list[tuple[int, str]] = []
    for path in list_kb_files():
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
) -> str:
    """Query memories with tag/time filters, sorting, and optional semantic match."""
    total = get_memory_backend().count()
    if total == 0:
        return "记忆库为空，尚未保存任何记忆。"

    sort_order = sort if sort in ("newest", "oldest", "relevance") else "newest"
    hits = query_memories(
        query=query,
        tags=tags,
        since=since,
        until=until,
        sort=sort_order,  # type: ignore[arg-type]
        limit=limit,
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
    hits = get_memory_backend().recall(query, max_results=top_k)
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
        return f"（记忆未命中，以下为知识库检索结果）\n{knowledge}"

    documents = search_documents(query, top_k=top_k)
    if documents:
        return f"（记忆和 RAG 均未命中，以下为文档原文检索）\n{documents}"

    return _ALL_MISS


def search_knowledge(query: str, *, top_k: int = 5, fallback: bool = True) -> str:
    hits = get_hybrid_retriever().retrieve(query, top_k=top_k)
    if hits:
        lines = []
        for h in hits:
            meta = h.get("metadata", {})
            heading = meta.get("heading", "")
            source = meta.get("source_file", "")
            lines.append(f"- [{h['score_rrf']:.3f}] {heading} ({source})\n  {h['text'][:300]}")
        return "\n".join(lines)

    if not fallback:
        return _KNOWLEDGE_MISS

    documents = search_documents(query, top_k=top_k)
    if documents:
        return f"（知识库索引未命中，以下为文档原文检索）\n{documents}"

    return _KNOWLEDGE_MISS


def augment_web_query(query: str) -> str:
    """Add a current-date hint when the query lacks an explicit year."""
    q = query.strip()
    if not q or re.search(r"20\d{2}", q):
        return q
    today = date.today()
    return f"{q} {today.strftime('%Y年%m月')}"


def derive_search_params(query: str) -> dict[str, Any]:
    """Derive Tavily recency/topic options from query text."""
    opts: dict[str, Any] = {"search_depth": "basic", "include_answer": True}
    q = query.lower()

    news_markers = ("新闻", "时事", "头条", "热点", "快讯", "news", "breaking")
    recent_markers = ("最近", "最新", "今日", "今天", "昨天", "本周", "近期", "当下", "现在", "latest", "recent")
    today_markers = ("今天", "今日", "today", "刚刚")
    time_markers = ("几点", "当前时间", "现在时间", "今天几号", "今天日期", "what time", "current time")

    is_news = any(marker in query or marker in q for marker in news_markers)
    is_recent = any(marker in query or marker in q for marker in recent_markers)
    is_today = any(marker in query or marker in q for marker in today_markers)
    is_time = any(marker in query or marker in q for marker in time_markers)

    if is_news:
        opts["topic"] = "news"
        opts["days"] = 1 if is_today else 7
    elif is_time or is_today:
        opts["time_range"] = "day"
    elif is_recent:
        opts["time_range"] = "week"
    return opts


def web_search(query: str, *, max_results: int = 5) -> str:
    if not config.TAVILY_API_KEY:
        return "联网搜索未配置（请设置 TAVILY_API_KEY）。"
    search_query = augment_web_query(query)
    payload = {
        "api_key": config.TAVILY_API_KEY,
        "query": search_query,
        "max_results": max_results,
        **derive_search_params(query),
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return f"联网搜索失败: {exc}"
    try:
        log_usage("tavily", "search", command="web_search", per_call=True)
    except Exception:
        pass
    lines: list[str] = []
    answer = data.get("answer", "")
    if answer:
        lines.append(f"摘要: {answer}")
    results = data.get("results", [])
    if not results:
        return answer or "未找到联网结果。"
    for r in results:
        published = r.get("published_date", "")
        date_hint = f" ({published})" if published else ""
        lines.append(f"- {r.get('title', '')}{date_hint}: {r.get('content', '')[:200]}")
        lines.append(f"  URL: {r.get('url', '')}")
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

    _status("综合多轮结果，撰写研究报告…")
    synthesis_prompt = (
        f"基于以下多轮搜索结果，撰写关于「{topic}」的深度研究报告（中文，结构化）：\n\n"
        + "\n\n".join(all_evidence)
    )
    return router.chat([ChatMessage(role="user", content=synthesis_prompt)], temperature=0.4, usage_command="deepsearch")


def reflect_memory(query: str) -> str:
    """Reason over memories (Mem0 search + LLM); falls back to recall on JSON backend."""
    backend = get_memory_backend()
    answer = backend.reflect(query)
    if answer:
        return answer

    if backend.backend_name() == "json":
        hits = backend.recall(query, max_results=5)
        if hits:
            body = _format_memory_hits(hits, query=query)
            return (
                "（当前为 JSON 记忆后端，无跨记忆推理；以下为 recall 结果）\n"
                + body
            )
        return (
            "推理召回需要 Mem0 记忆引擎。"
            "请确认已安装 mem0ai，并将 LA_MEMORY_BACKEND 设为 mem0。"
        )

    return "未能从记忆中推理出答案。"


def workspace_context_tool(*, days: int = 7) -> str:
    """Agent tool: workspace git/files/todos summary."""
    from localagent.workspace.context import workspace_context

    return workspace_context(days=days)


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
        "description": "搜索知识库文档；未命中时自动回退到文档原文关键词检索",
        "parameters": {"query": "搜索关键词"},
    },
    {
        "name": "web_search",
        "description": "联网搜索最新信息，用于时效性、新闻、外部资料类问题",
        "parameters": {"query": "搜索关键词"},
    },
    {
        "name": "reflect_memory",
        "description": (
            "对记忆进行推理综合，处理矛盾、歧义或需要跨多条记忆归纳的问题；"
            "需要 Mem0 引擎（search + LLM）；JSON 后端会降级为 recall"
        ),
        "parameters": {"query": "需要推理的问题"},
    },
    {
        "name": "workspace_context",
        "description": "获取工作区上下文：最近修改的文件、Git 状态与提交、待办 TODO；用于「我最近干了啥、git 怎样、有什么待办」类问题",
        "parameters": {"days": "可选，最近几天内的文件变更，默认 7"},
    },
    {
        "name": "query_memories",
        "description": (
            "浏览或查询本地记忆库：支持按标签、时间范围过滤，按时间或相关度排序，"
            "以及内容语义匹配；用于「记忆里有什么、按标签查看、某段时间的记忆」类问题"
        ),
        "parameters": {
            "query": "可选，语义搜索关键词",
            "tags": "可选，标签列表，如 [\"偏好\", \"工作\"]",
            "since": "可选，起始日期 YYYY-MM-DD",
            "until": "可选，结束日期 YYYY-MM-DD",
            "sort": "可选，newest（默认）/ oldest / relevance",
            "limit": "可选，返回条数，默认 20",
        },
    },
    {
        "name": "write_file",
        "description": (
            "在工作区创建或写入文件（覆盖或追加）；"
            "用于创建、修改、更新文件内容，优先于 run_shell"
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
            "用于统计代码行数、列目录、运行测试/构建、查看 git log 等需要终端的操作"
        ),
        "parameters": {
            "command": "要执行的 shell 命令，如 find . -name '*.py' | wc -l",
            "cwd": "可选，工作目录（默认 LA_WORKSPACE 或当前目录）",
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
        return search_knowledge(arguments.get("query", ""))
    if name == "web_search":
        return web_search(arguments.get("query", ""))
    if name == "reflect_memory":
        return reflect_memory(arguments.get("query", ""))
    if name == "workspace_context":
        days_raw = arguments.get("days", 7)
        try:
            days = int(days_raw)
        except (TypeError, ValueError):
            days = 7
        return workspace_context_tool(days=days)
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
        )
    if name == "write_file":
        path = str(arguments.get("path") or "").strip()
        content = str(arguments.get("content") or "")
        mode = str(arguments.get("mode") or "overwrite")
        cwd = arguments.get("cwd")
        cwd_str = str(cwd).strip() if cwd else None
        return write_file(path, content, mode=mode, cwd=cwd_str)
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
    return f"未知工具: {name}"
