"""Unified Warm/Cold retrieval for prefetch and agent tools."""

from __future__ import annotations

import logging
import re
from typing import Any

from localagent.knowledge.hybrid import get_hybrid_retriever
from localagent.memory.backend import get_memory_backend
from localagent.memory.display import format_memory_hits
from localagent.memory.query import list_memory_tags, query_memories

logger = logging.getLogger(__name__)

MEMORY_MISS = "未找到相关记忆。"
KNOWLEDGE_MISS = "未找到相关知识片段。"
ALL_MISS = "未在记忆、知识库索引或文档原文中找到相关信息。"


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


class RetrievalGateway:
    """Facade over Warm recall, Cold hybrid search, and structured Warm queries."""

    def recall_warm(
        self,
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
            return format_memory_hits(
                hits,
                query=query,
                show_ids=show_ids,
                verbose=verbose,
            )

        if not fallback:
            return MEMORY_MISS

        knowledge = self.search_cold(query, top_k=top_k, fallback=False)
        if knowledge != KNOWLEDGE_MISS:
            logger.info("search_memory miss→knowledge")
            return f"（记忆未命中，以下为知识库检索结果）\n{knowledge}"

        from localagent import config as la_config

        if la_config.DOC_KEYWORD_FALLBACK:
            documents = self.search_documents(query, top_k=top_k)
            if documents:
                logger.info("search_memory miss→documents")
                return f"（记忆和 RAG 均未命中，以下为文档原文关键词补充检索）\n{documents}"

        logger.info("search_memory miss (all)")
        return ALL_MISS

    def search_cold(
        self,
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
                rerank_score = h.get("rerank_score")
                if rerank_score is not None:
                    try:
                        score_label = f"rerank:{float(rerank_score):.3f}"
                    except (TypeError, ValueError):
                        score_label = f"rrf:{h.get('score_rrf', 0.0):.3f}"
                else:
                    score_label = f"rrf:{h.get('score_rrf', 0.0):.3f}"
                lines.append(
                    f"- [{score_label}] {prefix}{heading} ({display_source})\n"
                    f"  {h['text'][:300]}"
                )
            return "\n".join(lines)

        if not fallback:
            return KNOWLEDGE_MISS

        from localagent import config as la_config

        if la_config.DOC_KEYWORD_FALLBACK and not (since or until or conversation_only):
            documents = self.search_documents(query, top_k=top_k)
            if documents:
                return f"（知识库索引未命中，以下为文档原文关键词补充检索）\n{documents}"

        return KNOWLEDGE_MISS

    def query_warm(
        self,
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

    def list_knowledge_in_range(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        limit: int = 40,
    ) -> str:
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
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        limit: int = 40,
    ) -> str:
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

    def search_documents(self, query: str, *, top_k: int = 5, context_chars: int = 300) -> str:
        from localagent import config
        from localagent.ingest.loader import load_file
        from localagent.ingest.sync_file import list_kb_files

        terms = re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]{2,}", query.lower())
        if not terms:
            return ""

        hits: list[tuple[int, str]] = []
        for path in list_kb_files():
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


_gateway: RetrievalGateway | None = None


def get_retrieval_gateway() -> RetrievalGateway:
    global _gateway
    if _gateway is None:
        _gateway = RetrievalGateway()
    return _gateway
