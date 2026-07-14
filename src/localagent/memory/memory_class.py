"""Cognitive memory-class tagging (semantic / episodic / procedural).

Working memory stays runtime-only and is never written to Warm.
This module maps Warm facts onto the other three classes and routes
recall soft-boosts by query intent — without replacing Hot/Warm/Cold.
"""

from __future__ import annotations

from typing import Any, Literal

from localagent.memory.temporal_intent import TemporalIntent

MemoryClass = Literal["semantic", "episodic", "procedural"]
MEMORY_CLASSES: frozenset[str] = frozenset({"semantic", "episodic", "procedural"})

_TYPE_TO_CLASS: dict[str, MemoryClass] = {
    "preference": "semantic",
    "fact": "semantic",
    "plan": "semantic",
    "observation": "semantic",
    "experience": "episodic",
    "decision": "episodic",
    "skill": "procedural",
    "procedure": "procedural",
}

_CHAT_SUMMARY_SOURCES = frozenset(
    {
        "chat",
        "rememorize-chat",
        "chat_explicit",
        "session",
        "exit_extract",
        "session_summary",
    }
)

_PROCEDURAL_CUES = (
    "怎么做",
    "如何做",
    "怎么弄",
    "步骤",
    "流程",
    "操作方法",
    "how to",
    "how do i",
    "how do you",
    "steps to",
    "walk me through",
)

_SEMANTIC_CUES_ZH = (
    "喜欢",
    "偏好",
    "习惯",
    "叫什么",
    "是谁",
    "住在",
    "住址",
    "居住",
    "职业",
    "工作是",
    "我的名字",
)

_SEMANTIC_CUES_EN = (
    "prefer",
    "favorite",
    "favourite",
    "who am i",
    "my name",
    "where do i live",
    "identity",
    "what is my",
)

_EPISODIC_CUES_EN = (
    "what did",
    "when did",
    "where did",
    "said about",
    "talked about",
    "mentioned",
    "last time",
    "that day",
    "that night",
)


def infer_memory_class(
    *,
    memory_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    text: str = "",
) -> MemoryClass:
    """Resolve cognitive class from type + metadata signals.

    Explicit ``memory_class`` in metadata wins when valid. Dialog-bound
    facts (``dia_id``) are episodic even if type is ``fact``.
    """
    del text  # reserved for future heuristic cues
    meta = metadata or {}
    explicit = str(meta.get("memory_class") or "").strip().lower()
    if explicit in MEMORY_CLASSES:
        return explicit  # type: ignore[return-value]

    mtype = (memory_type or str(meta.get("type") or "fact")).strip().lower()
    kind = str(meta.get("memory_kind") or "").strip().lower()
    source = str(meta.get("source") or "").strip().lower()

    if mtype in ("skill", "procedure") or kind == "skill":
        return "procedural"

    if meta.get("dia_id"):
        return "episodic"
    if mtype in ("experience", "decision"):
        return "episodic"
    if kind == "summary" and source in _CHAT_SUMMARY_SOURCES:
        return "episodic"
    if meta.get("occurred_at") and mtype in ("experience", "decision", "observation"):
        return "episodic"

    return _TYPE_TO_CLASS.get(mtype, "semantic")


def stamp_memory_class(
    metadata: dict[str, Any],
    *,
    text: str = "",
    memory_type: str | None = None,
) -> dict[str, Any]:
    """Finalize ``memory_class``: dia_id → episodic; else keep explicit; else infer."""
    meta = dict(metadata)
    if meta.get("dia_id"):
        meta["memory_class"] = "episodic"
        return meta
    explicit = str(meta.get("memory_class") or "").strip().lower()
    if explicit in MEMORY_CLASSES:
        return meta
    meta["memory_class"] = infer_memory_class(
        memory_type=memory_type or meta.get("type"),
        metadata=meta,
        text=text,
    )
    return meta


def resolve_memory_class_for_recall(
    metadata: dict[str, Any] | None = None,
    *,
    text: str = "",
) -> MemoryClass:
    """Recall-time class: dialog turns are always episodic; else trust stamp/infer."""
    meta = metadata or {}
    if meta.get("dia_id"):
        return "episodic"
    return infer_memory_class(metadata=meta, text=text)


def parse_memory_class_intent(
    query: str,
    temporal: TemporalIntent | None = None,
) -> MemoryClass | None:
    """Infer which memory class the query prefers; None = no class bias."""
    raw = (query or "").strip()
    if not raw:
        return None
    q = raw.lower()

    if temporal is not None and (
        temporal.raises_temporal_weight or temporal.prefers_event_neighbors
    ):
        return "episodic"

    if any(cue in q for cue in _PROCEDURAL_CUES) or any(cue in raw for cue in _PROCEDURAL_CUES):
        return "procedural"

    if any(cue in raw for cue in _SEMANTIC_CUES_ZH) or any(cue in q for cue in _SEMANTIC_CUES_EN):
        return "semantic"

    if any(cue in q for cue in _EPISODIC_CUES_EN):
        return "episodic"

    return None


def memory_class_alignment(
    hit_class: MemoryClass,
    preferred: MemoryClass | None,
) -> float:
    """0..1 soft alignment for finalize_hybrid_rank (1 = match)."""
    if preferred is None:
        return 0.5
    if hit_class == preferred:
        return 1.0
    if preferred == "procedural":
        return 0.15
    if preferred == "semantic" and hit_class == "episodic":
        return 0.25
    if preferred == "episodic" and hit_class == "semantic":
        return 0.35
    if preferred == "semantic" and hit_class == "procedural":
        return 0.3
    if preferred == "episodic" and hit_class == "procedural":
        return 0.3
    return 0.4
