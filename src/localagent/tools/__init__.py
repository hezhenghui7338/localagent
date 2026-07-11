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
from localagent.memory.hindsight_client import get_memory_backend
from localagent.memory.scoped_recall import scoped_recall
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
    facts = get_memory_store().all_facts()
    if not facts:
        return "记忆库为空，尚未保存任何记忆。"

    recent = sorted(facts, key=lambda fact: fact.created_at, reverse=True)[:top_k]
    hits = [_fact_to_hit(fact, score=1.0 - index * 0.02) for index, fact in enumerate(recent)]
    body = format_memory_hits(hits, show_ids=False)
    return f"记忆库共 {len(facts)} 条，展示最近 {len(recent)} 条\n\n{body}"


def search_memory(
    query: str,
    *,
    top_k: int = 5,
    fallback: bool = True,
    show_ids: bool = False,
    verbose: bool = False,
) -> str:
    hits = scoped_recall(query, max_results=top_k)
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

    is_news = any(marker in query or marker in q for marker in news_markers)
    is_recent = any(marker in query or marker in q for marker in recent_markers)
    is_today = any(marker in query or marker in q for marker in today_markers)

    if is_news:
        opts["topic"] = "news"
        opts["days"] = 1 if is_today else 7
    elif is_recent:
        opts["time_range"] = "day" if is_today else "week"
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
    with httpx.Client(timeout=30.0) as client:
        resp = client.post("https://api.tavily.com/search", json=payload)
        resp.raise_for_status()
        data = resp.json()
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


def workspace_context_tool(*, days: int = 7) -> str:
    """Agent tool: workspace git/files/todos summary."""
    from localagent.workspace.context import workspace_context

    return workspace_context(days=days)


TOOL_DEFINITIONS: list[dict[str, Any]] = [
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
        "name": "workspace_context",
        "description": "获取工作区上下文：最近修改的文件、Git 状态与提交、待办 TODO；用于「我最近干了啥、git 怎样、有什么待办」类问题",
        "parameters": {"days": "可选，最近几天内的文件变更，默认 7"},
    },
]


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    if name == "search_memory":
        return search_memory(arguments.get("query", ""))
    if name == "search_knowledge":
        return search_knowledge(arguments.get("query", ""))
    if name == "web_search":
        return web_search(arguments.get("query", ""))
    if name == "workspace_context":
        days_raw = arguments.get("days", 7)
        try:
            days = int(days_raw)
        except (TypeError, ValueError):
            days = 7
        return workspace_context_tool(days=days)
    return f"未知工具: {name}"
