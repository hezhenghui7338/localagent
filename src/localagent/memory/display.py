"""Human-readable formatting for memory search results."""

from __future__ import annotations

from datetime import datetime
from typing import Any

_TYPE_LABELS = {
    "preference": "偏好",
    "fact": "事实",
    "plan": "计划",
    "experience": "经历",
    "observation": "观察",
    "world": "世界知识",
}

_GENERIC_SOURCES = frozenset({"direct", "manual", "manual_add", "chat", "unknown"})


def _format_date(created_at: str) -> str:
    if not created_at:
        return "未知时间"
    try:
        dt = datetime.fromisoformat(created_at)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return created_at[:10] if len(created_at) >= 10 else created_at


def _resolve_title(hit: dict[str, Any]) -> str:
    meta = hit.get("metadata") or {}
    title = meta.get("title") or hit.get("section_heading") or ""
    title = str(title).strip()
    if title.startswith("##"):
        title = title.lstrip("# ").strip()
    return title or "未命名记忆"


def _resolve_tags(hit: dict[str, Any]) -> list[str]:
    meta = hit.get("metadata") or {}
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        return [tags] if tags else []
    return [str(t) for t in tags if str(t).strip()]


def _resolve_type(hit: dict[str, Any]) -> str:
    meta = hit.get("metadata") or {}
    raw = str(meta.get("type") or hit.get("type") or "fact")
    return _TYPE_LABELS.get(raw, raw)


def _resolve_body(hit: dict[str, Any]) -> str:
    meta = hit.get("metadata") or {}
    summary = str(meta.get("summary") or "").strip()
    text = str(hit.get("text") or "").strip()
    if summary and summary != text and len(text) > len(summary) + 20:
        return summary
    return text


def _resolve_source(hit: dict[str, Any]) -> str:
    meta = hit.get("metadata") or {}
    if meta.get("source") and meta["source"] not in _GENERIC_SOURCES:
        return str(meta["source"])
    source = hit.get("source_file") or ""
    if source and source not in ("manual", "?"):
        return source
    heading = hit.get("section_heading") or ""
    if heading and heading != source:
        return f"{source} / {heading}" if source else heading
    return source or "未知来源"


def format_memory_hit(
    hit: dict[str, Any],
    *,
    index: int,
    show_ids: bool = False,
    verbose: bool = False,
) -> str:
    """Format a single memory hit as a readable card."""
    title = _resolve_title(hit)
    tags = _resolve_tags(hit)
    body = _resolve_body(hit)
    score = hit.get("score", 0.0)
    date_str = _format_date(hit.get("created_at", ""))
    mem_type = _resolve_type(hit)
    source = _resolve_source(hit)

    tag_part = " · ".join(f"#{t}" for t in tags) if tags else ""
    meta_line_parts = [f"相关度 {score:.2f}", date_str, mem_type]
    if tag_part:
        meta_line_parts.append(tag_part)
    meta_line = " · ".join(meta_line_parts)

    lines = [
        f"### {index}. {title}",
        meta_line,
        "",
        body,
    ]

    footer_parts = [f"来源: {source}"]
    if show_ids and hit.get("id"):
        footer_parts.append(f"id: {hit['id'][:8]}")
    lines.extend(["", " · ".join(footer_parts)])

    if verbose:
        anchor = hit.get("anchor") or {}
        if anchor:
            lines.append(f"时间锚点: {anchor}")
        if hit.get("semantic_score") is not None:
            lines.append(
                f"语义 {hit['semantic_score']:.2f} · "
                f"时间衰减 {hit.get('temporal_score', 0):.2f}"
            )
        full_text = str((hit.get("metadata") or {}).get("char_count", ""))
        if full_text:
            lines.append(f"原始长度: {full_text} 字")

    return "\n".join(lines)


def format_memory_hits(
    hits: list[dict[str, Any]],
    *,
    query: str = "",
    show_ids: bool = False,
    verbose: bool = False,
) -> str:
    """Format memory search results as a structured report."""
    if not hits:
        return ""

    header = f"找到 {len(hits)} 条相关记忆"
    if query:
        header += f"（查询: {query}）"
    blocks = [header, ""]
    for idx, hit in enumerate(hits, start=1):
        blocks.append(format_memory_hit(
            hit,
            index=idx,
            show_ids=show_ids,
            verbose=verbose,
        ))
        if idx < len(hits):
            blocks.append("─" * 40)
    return "\n".join(blocks)
