"""Human-readable formatting for memory search results."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from localagent.i18n import t

_TYPE_KEYS = {
    "preference": "memory.type_preference",
    "fact": "memory.type_fact",
    "plan": "memory.type_plan",
    "experience": "memory.type_experience",
    "observation": "memory.type_observation",
    "world": "memory.type_world",
}

_GENERIC_SOURCES = frozenset({"direct", "manual", "manual_add", "chat", "unknown"})


def _format_date(created_at: str) -> str:
    if not created_at:
        return t("memory.unknown_time")
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
    return title or t("memory.untitled")


def _resolve_tags(hit: dict[str, Any]) -> list[str]:
    meta = hit.get("metadata") or {}
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        return [tags] if tags else []
    return [str(tag) for tag in tags if str(tag).strip()]


def _resolve_type(hit: dict[str, Any]) -> str:
    meta = hit.get("metadata") or {}
    raw = str(meta.get("type") or hit.get("type") or "fact")
    key = _TYPE_KEYS.get(raw)
    return t(key) if key else raw


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
    source = hit.get("source_file") or str(meta.get("source_file") or "")
    if source and source not in ("manual", "?"):
        return source
    heading = hit.get("section_heading") or ""
    if heading and heading != source:
        return f"{source} / {heading}" if source else heading
    return source or t("memory.unknown_source")


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

    tag_part = " · ".join(f"#{tag}" for tag in tags) if tags else ""
    meta_line_parts: list[str] = []
    if score > 0:
        meta_line_parts.append(t("memory.relevance", score=score))
    meta_line_parts.extend([date_str, mem_type])
    if tag_part:
        meta_line_parts.append(tag_part)
    meta_line = " · ".join(meta_line_parts)

    lines = [
        f"### {index}. {title}",
        meta_line,
        "",
        body,
    ]

    footer_parts = [t("memory.source_label", source=source)]
    if show_ids and hit.get("id"):
        footer_parts.append(f"id: {hit['id'][:8]}")
    lines.extend(["", " · ".join(footer_parts)])

    if verbose:
        anchor = hit.get("anchor") or {}
        if anchor:
            lines.append(t("memory.time_anchor", anchor=anchor))
        if hit.get("semantic_score") is not None:
            lines.append(
                t(
                    "memory.semantic_temporal",
                    semantic=hit["semantic_score"],
                    temporal=hit.get("temporal_score", 0),
                )
            )
        full_text = str((hit.get("metadata") or {}).get("char_count", ""))
        if full_text:
            lines.append(t("memory.char_count", n=full_text))

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

    header = t("memory.found_n", n=len(hits))
    if query:
        header += t("memory.found_query", query=query)
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
