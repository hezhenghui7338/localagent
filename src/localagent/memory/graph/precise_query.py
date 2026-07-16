"""Classify precise questions and run Neo4j Cypher templates."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from localagent.memory.graph.cypher_guard import validate_readonly_cypher
from localagent.memory.graph.cypher_templates import CypherTemplate, get_template

logger = logging.getLogger(__name__)

_COUNT_RE = re.compile(
    r"(?:多少|几次|几个|一共|总共|计数|how\s+many|how\s+often|count\b|number\s+of)",
    re.IGNORECASE,
)
_COLLECT_RE = re.compile(
    r"(?:哪些|列出|有哪|list\s+all|which\s+(?:cities|places|people|friends)|"
    r"what\s+(?:cities|places)|都有谁|都去过)",
    re.IGNORECASE,
)
_PATH_RE = re.compile(
    r"(?:朋友.*住|住在哪|通过.+认识|multi-?hop|的朋友|"
    r"friend(?:'s)?\s+(?:live|lives|city|place)|where\s+does)",
    re.IGNORECASE,
)
_CO_RE = re.compile(
    r"(?:同时|一起|both|and\s+also|共同|既.+又|跟.+一起|"
    r"mentioned\s+together|co-?mention)",
    re.IGNORECASE,
)
_ENTITY_TOKEN = re.compile(
    r"[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?|[\u4e00-\u9fff]{2,8}"
)
_STOP = frozenset(
    {
        "how", "many", "what", "which", "where", "who", "the", "and", "for",
        "with", "from", "that", "this", "list", "all", "about", "times",
        "多少", "几次", "几个", "一共", "总共", "哪些", "列出", "什么",
        "哪里", "哪儿", "朋友", "城市", "地点", "记忆", "提到", "说过",
        "一起", "同时", "有没有", "请问",
    }
)


@dataclass
class PreciseIntent:
    kind: str  # open | count | collect | path | co_mention
    template_id: str | None = None
    entities: list[str] = field(default_factory=list)


@dataclass
class PreciseQueryResult:
    ok: bool
    answer: str
    value: Any = None
    cypher: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    fact_ids: list[str] = field(default_factory=list)
    kind: str = "open"
    template_id: str | None = None
    fallback: bool = False
    reason: str = ""


def extract_query_entities(query: str, *, limit: int = 4) -> list[str]:
    """Pull likely entity names from the question (rule-based)."""
    from localagent.memory.entities import extract_entities

    names: list[str] = []
    try:
        names.extend(extract_entities(query, limit=limit))
    except Exception:
        pass
    for tok in _ENTITY_TOKEN.findall(query or ""):
        cleaned = " ".join(tok.split()).strip()
        if not cleaned or cleaned.casefold() in _STOP or cleaned in _STOP:
            continue
        names.append(cleaned)
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= limit:
            break
    return out


def classify_precise_query(query: str) -> PreciseIntent:
    """Rule-based router: precise kinds vs open (hybrid retrieval)."""
    q = (query or "").strip()
    if not q:
        return PreciseIntent(kind="open")
    entities = extract_query_entities(q)
    if _CO_RE.search(q) and len(entities) >= 2:
        return PreciseIntent(
            kind="co_mention",
            template_id="co_mention_count",
            entities=entities,
        )
    if _PATH_RE.search(q) and entities:
        return PreciseIntent(
            kind="path",
            template_id="path_related",
            entities=entities,
        )
    if _COUNT_RE.search(q) and entities:
        # 「提到过几次」= count facts mentioning entity (not RELATES predicate).
        if re.search(
            r"(?:提到过|提到|聊到过|说过|mentioned|how\s+many\s+times)",
            q,
            re.IGNORECASE,
        ):
            return PreciseIntent(
                kind="count",
                template_id="count_facts_mentioning",
                entities=entities,
            )
        if re.search(
            r"(?:去过|visited|met|adopted|喜欢|旅行)",
            q,
            re.IGNORECASE,
        ):
            return PreciseIntent(
                kind="count",
                template_id="count_relations",
                entities=entities,
            )
        return PreciseIntent(
            kind="count",
            template_id="count_facts_mentioning",
            entities=entities,
        )
    if _COLLECT_RE.search(q) and entities:
        return PreciseIntent(
            kind="collect",
            template_id="collect_related",
            entities=entities,
        )
    return PreciseIntent(kind="open", entities=entities)


def _format_answer(kind: str, value: Any, *, entities: list[str]) -> str:
    label = entities[0] if entities else "该实体"
    if kind in {"count", "co_mention"}:
        try:
            n = int(value)
        except (TypeError, ValueError):
            n = value
        if kind == "co_mention" and len(entities) >= 2:
            return f"同时提到「{entities[0]}」与「{entities[1]}」的记忆共 {n} 条。"
        return f"与「{label}」相关的图计算结果为 {n}。"
    if isinstance(value, list):
        if not value:
            return f"未在关系图中找到与「{label}」相关的条目。"
        joined = "、".join(str(v) for v in value[:20])
        return f"与「{label}」相关的结果：{joined}。"
    return f"图查询结果：{value}"


def _normalize_rows(rows: list[dict[str, Any]]) -> tuple[Any, list[str]]:
    if not rows:
        return None, []
    row = rows[0]
    value = row.get("value")
    raw_ids = row.get("fact_ids") or []
    fact_ids: list[str] = []
    if isinstance(raw_ids, list):
        for item in raw_ids:
            if item is None:
                continue
            fact_ids.append(str(item))
    return value, fact_ids


def run_template(
    template: CypherTemplate,
    query: str,
    entities: list[str],
    *,
    store: Any | None = None,
) -> PreciseQueryResult:
    from localagent.memory.graph.neo4j_store import get_neo4j_store, neo4j_available

    params = template.build_params(query, entities)
    if not params:
        return PreciseQueryResult(
            ok=False,
            answer="",
            kind=template.kind,
            template_id=template.id,
            reason="missing template params (need entities)",
        )

    guard = validate_readonly_cypher(template.cypher)
    if not guard.ok:
        return PreciseQueryResult(
            ok=False,
            answer="",
            kind=template.kind,
            template_id=template.id,
            reason=guard.reason,
        )

    cypher = guard.limited_cypher
    try:
        graph = store if store is not None else get_neo4j_store()
        if store is None and not neo4j_available():
            return PreciseQueryResult(
                ok=False,
                answer="",
                kind=template.kind,
                template_id=template.id,
                reason="neo4j unavailable",
            )
        rows = graph.run_cypher(cypher, params)
    except Exception as exc:
        logger.warning("neo4j template %s failed: %s", template.id, exc)
        return PreciseQueryResult(
            ok=False,
            answer="",
            cypher=cypher,
            params=params,
            kind=template.kind,
            template_id=template.id,
            reason=str(exc),
        )

    value, fact_ids = _normalize_rows(rows)
    if value is None and not fact_ids:
        return PreciseQueryResult(
            ok=False,
            answer="",
            cypher=cypher,
            params=params,
            kind=template.kind,
            template_id=template.id,
            reason="empty result",
        )

    answer = _format_answer(template.kind, value, entities=entities)
    return PreciseQueryResult(
        ok=True,
        answer=answer,
        value=value,
        cypher=cypher,
        params=params,
        fact_ids=fact_ids,
        kind=template.kind,
        template_id=template.id,
    )


def precise_graph_query(
    query: str,
    *,
    store: Any | None = None,
    fallback_hybrid: bool = True,
) -> PreciseQueryResult:
    """Run precise Neo4j path; optionally fall back to hybrid recall text."""
    from localagent.memory.graph.neo4j_store import neo4j_enabled

    intent = classify_precise_query(query)
    if intent.kind == "open" or not intent.template_id:
        if fallback_hybrid:
            return _hybrid_fallback(query, intent)
        return PreciseQueryResult(
            ok=False,
            answer="",
            kind="open",
            reason="not a precise query",
        )

    if not neo4j_enabled() and store is None:
        if fallback_hybrid:
            result = _hybrid_fallback(query, intent)
            result.reason = "LA_NEO4J disabled"
            return result
        return PreciseQueryResult(
            ok=False,
            answer="",
            kind=intent.kind,
            reason="LA_NEO4J disabled",
        )

    template = get_template(intent.template_id)
    if template is None:
        return PreciseQueryResult(
            ok=False,
            answer="",
            kind=intent.kind,
            reason=f"unknown template {intent.template_id}",
        )

    result = run_template(template, query, intent.entities, store=store)
    if result.ok:
        return result
    if fallback_hybrid:
        fb = _hybrid_fallback(query, intent)
        fb.fallback = True
        fb.reason = result.reason or "graph query failed"
        fb.cypher = result.cypher
        fb.params = result.params
        fb.template_id = result.template_id
        return fb
    return result


def _hybrid_fallback(query: str, intent: PreciseIntent) -> PreciseQueryResult:
    try:
        from localagent.memory.backend import get_memory_backend

        hits = get_memory_backend().recall(query, max_results=5)
        if not hits:
            return PreciseQueryResult(
                ok=False,
                answer="未在关系图或记忆检索中找到相关信息。",
                kind=intent.kind,
                fallback=True,
                reason="hybrid miss",
            )
        lines = []
        fact_ids: list[str] = []
        for hit in hits[:5]:
            text = str(hit.get("text") or "").strip()
            hid = str(hit.get("id") or "")
            if hid:
                fact_ids.append(hid)
            if text:
                lines.append(f"- {text}")
        return PreciseQueryResult(
            ok=True,
            answer="（图查询未命中，以下为混合检索结果，非精确计算）\n" + "\n".join(lines),
            value=None,
            fact_ids=fact_ids,
            kind=intent.kind,
            fallback=True,
            reason="hybrid fallback",
        )
    except Exception as exc:
        return PreciseQueryResult(
            ok=False,
            answer="",
            kind=intent.kind,
            fallback=True,
            reason=str(exc),
        )


def format_precise_result(result: PreciseQueryResult, *, verbose: bool = False) -> str:
    if not result.answer and not result.ok:
        return result.reason or "图查询失败。"
    parts = [result.answer]
    if verbose:
        if result.template_id:
            parts.append(f"[template={result.template_id}]")
        if result.cypher:
            parts.append(f"[cypher] {result.cypher.strip()}")
        if result.fact_ids:
            parts.append("fact_ids: " + ", ".join(fid[:8] for fid in result.fact_ids[:12]))
    return "\n".join(parts)
