"""Long-text / session summarization for Warm memory layer."""

from __future__ import annotations

import re
from typing import Any

from localagent import config

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？.!?])\s+|\n+")


def heuristic_summary(text: str, *, max_chars: int = 600) -> str:
    """Extract a compact summary without LLM."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(cleaned) if p.strip()]
    if not parts:
        return cleaned[: max_chars - 1] + "…"
    out = parts[0]
    for part in parts[1:]:
        candidate = f"{out} {part}"
        if len(candidate) > max_chars:
            break
        out = candidate
    if len(out) > max_chars:
        out = out[: max_chars - 1] + "…"
    return out


def llm_summary(text: str, *, context: str = "", max_chars: int = 600) -> str | None:
    """Ask the model router for a short summary; None on failure."""
    try:
        from localagent.models.router import ChatMessage, get_model_router
    except Exception:
        return None
    prompt = (
        "请用简洁中文（或原文语言）概括下列内容，保留关键事实、人名、时间与结论。"
        f"不超过 {max(80, max_chars // 2)} 字，不要列表，不要前言。\n"
    )
    if context:
        prompt += f"上下文: {context}\n"
    prompt += f"\n内容:\n{(text or '')[:6000]}"
    try:
        reply = get_model_router().chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.1,
            usage_command="memory_summarize",
        )
    except Exception:
        return None
    summary = " ".join((reply or "").split()).strip()
    if not summary:
        return None
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1] + "…"
    return summary


def summarize_text(
    text: str,
    *,
    context: str = "",
    max_chars: int | None = None,
    use_llm: bool | None = None,
) -> str:
    """Summarize text; LLM optional with heuristic fallback."""
    limit = max_chars if max_chars is not None else config.MEMORY_SUMMARY_MAX_CHARS
    if use_llm is None:
        use_llm = config.MEMORY_SUMMARY_USE_LLM
    if use_llm:
        llm = llm_summary(text, context=context, max_chars=limit)
        if llm:
            return llm
    return heuristic_summary(text, max_chars=limit)


def build_document_summary_facts(
    text: str,
    *,
    filename: str,
    sections: list[Any] | None = None,
) -> list[dict[str, Any]]:
    """Build Warm summary facts for a long document.

    Strategy:
    - Always one document-level summary when text is long enough.
    - Plus up to N section summaries for long sections.
    """
    if not config.INGEST_WARM_SUMMARY:
        return []
    cleaned = (text or "").strip()
    if len(cleaned) < config.INGEST_SUMMARY_MIN_CHARS:
        return []

    facts: list[dict[str, Any]] = []
    doc_summary = summarize_text(cleaned, context=f"file={filename}")
    if doc_summary:
        facts.append(
            {
                "text": f"[文档摘要:{filename}] {doc_summary}",
                "metadata": {
                    "source": "ingest_summary",
                    "source_file": filename,
                    "section_heading": "document_summary",
                    "memory_kind": "summary",
                    "summary_of": filename,
                },
            }
        )

    max_sections = max(0, config.INGEST_SUMMARY_MAX_SECTIONS)
    if not sections or max_sections <= 0:
        return facts[: config.INGEST_MEMORY_MAX_FACTS]

    added = 0
    for section in sections:
        if added >= max_sections:
            break
        heading = str(getattr(section, "heading", "") or "")
        body = str(getattr(section, "text", "") or "").strip()
        if len(body) < config.INGEST_SUMMARY_MIN_CHARS:
            continue
        section_summary = summarize_text(
            body,
            context=f"file={filename}; section={heading}",
        )
        if not section_summary:
            continue
        title = heading.lstrip("# ").strip() or "section"
        facts.append(
            {
                "text": f"[章节摘要:{filename}/{title}] {section_summary}",
                "metadata": {
                    "source": "ingest_summary",
                    "source_file": filename,
                    "section_heading": heading or "section_summary",
                    "memory_kind": "summary",
                    "summary_of": f"{filename}::{title}",
                },
            }
        )
        added += 1

    return facts[: config.INGEST_MEMORY_MAX_FACTS]


def build_session_summary_fact(
    session_id: str,
    user_texts: list[str],
) -> dict[str, Any] | None:
    """Build one session-level summary fact from recent user turns.

    Ephemeral chats (weather/news/chitchat) stay in conversation persist only;
    Warm session_summary requires durable personal/project substance.
    """
    if not user_texts:
        return None
    from localagent.memory.value_filter import is_warm_worthy_session

    if not is_warm_worthy_session(user_texts):
        return None
    combined = "\n".join(user_texts)
    summary = summarize_text(combined, context=f"session={session_id}")
    if not summary:
        return None
    return {
        "text": f"[会话摘要:{session_id}] {summary}",
        "metadata": {
            "source": "chat_summary",
            "session_id": session_id,
            "section_heading": "session_summary",
            "memory_kind": "summary",
            "summary_of": session_id,
        },
    }
