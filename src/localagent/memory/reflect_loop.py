"""Multi-hop reflect: memory recall → knowledge retrieve → synthesize."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol

from localagent import config

logger = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class _RecallReflectBackend(Protocol):
    def recall(self, query: str, *, max_results: int = 10) -> list[dict[str, Any]]: ...


def _hit_id(hit: dict[str, Any]) -> str:
    return str(hit.get("id") or "") or f"text:{hash(str(hit.get('text') or ''))}"


def _source_label(hit: dict[str, Any]) -> str:
    source = str(hit.get("source") or "memory").strip().lower()
    if source in {"knowledge", "rag", "kb"}:
        return "知识库"
    return "记忆"


def _format_evidence(hits: list[dict[str, Any]], *, limit: int = 12) -> str:
    lines: list[str] = []
    for hit in hits[:limit]:
        text = str(hit.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"- [{_source_label(hit)}|{_hit_id(hit)[:8]}] {text}")
    return "\n".join(lines)


def _parse_hop_decision(reply: str) -> tuple[bool, list[str]]:
    """Return (ready_to_answer, followup_queries)."""
    raw = (reply or "").strip()
    if not raw:
        return True, []
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    data: Any = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = _JSON_RE.search(raw)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None
    if isinstance(data, dict):
        status = str(data.get("status") or data.get("decision") or "").strip().lower()
        queries_raw = data.get("queries") or data.get("followups") or []
        queries = [str(q).strip() for q in queries_raw if str(q).strip()]
        if status in {"ready", "answer", "done", "ok"}:
            return True, []
        if status in {"need", "need_more", "search", "followup", "continue"}:
            return False, queries[:2]
        # Heuristic: if queries present, continue; else ready.
        return (not queries), queries[:2]

    # Plain-text fallback
    lower = raw.lower()
    if "need" in lower or "不足" in raw or "还需要" in raw:
        queries = re.findall(r"[\"“](.+?)[\"”]", raw)
        if not queries:
            queries = [line.strip("-• ").strip() for line in raw.splitlines() if "?" in line]
        return False, [q for q in queries if q][:2]
    return True, []


def decide_followups(query: str, hits: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Return (ready_to_answer, followup_queries) for multi-hop re-recall."""
    if not hits:
        # No evidence yet — try decomposing once via a forced follow-up from the query itself.
        from localagent.memory.decompose import decompose_recall_query

        parts = decompose_recall_query(query)
        followups = [p for p in parts[1:] if p and p != query][:2]
        return (not followups), followups

    try:
        from localagent.models.router import ChatMessage, get_model_router
    except Exception:
        return True, []

    evidence = _format_evidence(hits)
    prompt = (
        "你是记忆检索规划器。根据用户问题与已召回记忆，判断能否回答。\n"
        "只输出 JSON（不要 markdown）：\n"
        '{"status":"ready|need","queries":["补充检索子问题1","子问题2"]}\n'
        "规则：\n"
        "- 证据足够 → status=ready，queries=[]\n"
        "- 缺关键事实（尤其多跳）→ status=need，给出最多 2 个具体子查询\n"
        "- 子查询要短、可检索，不要重复原问题原文\n\n"
        f"问题：{query}\n\n已召回记忆：\n{evidence}\n"
    )
    try:
        reply = get_model_router().chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.0,
            usage_command="reflect_plan",
        )
    except Exception as exc:
        logger.debug("reflect hop plan failed: %s", exc)
        return True, []
    return _parse_hop_decision(reply)


# Back-compat alias used inside this module.
_decide_followups = decide_followups


def _recall_knowledge(query: str, *, top_k: int) -> list[dict[str, Any]]:
    """Retrieve knowledge-base hits as reflect evidence."""
    try:
        from localagent.knowledge.hybrid import get_hybrid_retriever

        raw = get_hybrid_retriever().retrieve(query, top_k=top_k)
    except Exception as exc:
        logger.debug("reflect knowledge retrieve failed: %s", exc)
        return []

    hits: list[dict[str, Any]] = []
    for item in raw:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        meta = item.get("metadata") or {}
        heading = str(meta.get("heading") or "").strip()
        source_file = str(meta.get("source_file") or "").strip()
        origin = str(meta.get("origin") or "").strip()
        kind = str(meta.get("chunk_kind") or "").strip()
        chunk_id = str(meta.get("chunk_id") or meta.get("id") or "").strip()
        tags = []
        if origin:
            tags.append(origin)
        if kind == "summary":
            tags.append("摘要")
        tag = f"[{'/'.join(tags)}] " if tags else ""
        where = " / ".join(part for part in (heading, source_file) if part)
        prefixed = f"{tag}{where}: {text}" if where else f"{tag}{text}"
        hits.append(
            {
                "id": chunk_id or f"rag:{hash(text)}",
                "text": prefixed,
                "source": "knowledge",
                "score": item.get("score_rrf"),
            }
        )
    return hits


def _synthesize(query: str, hits: list[dict[str, Any]]) -> str | None:
    if not hits:
        return None
    evidence = _format_evidence(hits)
    if not evidence.strip():
        return None
    try:
        from localagent.models.router import ChatMessage, get_model_router
    except Exception:
        return None
    prompt = (
        "你是 LocalAgent 的综合推理模块。根据下列已召回的长期记忆与知识库资料，"
        "回答用户问题。优先依据记忆中的个人事实，知识库作补充；只依据证据归纳，不要编造；"
        "若仍不足请明确说明缺什么。\n\n"
        f"问题：{query}\n\n证据：\n{evidence}\n\n请用简洁中文回答："
    )
    try:
        answer = get_model_router().chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.2,
            usage_command="reflect",
        )
    except Exception as exc:
        logger.warning("reflect synthesize failed: %s", exc)
        return None
    text = (answer or "").strip()
    return text or None


def reflect_with_hops(
    backend: _RecallReflectBackend,
    query: str,
    *,
    max_hops: int | None = None,
    top_k: int | None = None,
) -> str | None:
    """Recall memory (multi-hop) → query knowledge → synthesize an answer."""
    hops = config.MEMORY_REFLECT_MAX_HOPS if max_hops is None else max_hops
    hops = max(0, int(hops))
    k = config.MEMORY_REFLECT_TOP_K if top_k is None else top_k
    k = max(1, int(k))

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    pending = [query]

    for hop in range(hops + 1):
        for sub in pending:
            try:
                hits = backend.recall(sub, max_results=k)
            except Exception as exc:
                logger.debug("reflect recall failed (%s): %s", sub[:40], exc)
                hits = []
            for hit in hits:
                hid = _hit_id(hit)
                if hid in seen:
                    continue
                seen.add(hid)
                enriched = dict(hit)
                enriched.setdefault("source", "memory")
                enriched["reflect_hop"] = hop
                merged.append(enriched)

        if hop >= hops:
            break
        ready, followups = _decide_followups(query, merged)
        if ready or not followups:
            break
        # Avoid re-running the exact same queries.
        pending = [q for q in followups if q.strip().lower() != query.strip().lower()]
        if not pending:
            break

    # After memory recall: always query the knowledge base once.
    for hit in _recall_knowledge(query, top_k=k):
        hid = _hit_id(hit)
        if hid in seen:
            continue
        seen.add(hid)
        merged.append(hit)

    return _synthesize(query, merged)
