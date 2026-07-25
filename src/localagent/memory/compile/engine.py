"""Structured profile compilation orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from localagent.ingest.doc_classifier import DocType, classify_document, extract_html_title
from localagent.memory.conversation_extract import ExtractedMemory


@dataclass
class ProfileCompileResult:
    profile_updates: list[dict[str, Any]] = field(default_factory=list)
    warm_memories: list[ExtractedMemory] = field(default_factory=list)
    source: str = ""
    doc_type: DocType = DocType.GENERAL


def compile_document_profile(
    *,
    filename: str,
    text: str,
    source_path: str = "",
) -> ProfileCompileResult:
    """Compile structured Hot updates (+ optional Warm memories) from a document."""
    title = extract_html_title(text)
    doc_type = classify_document(filename=filename, text=text, title=title)
    source = source_path or filename

    if doc_type == DocType.RESUME:
        from localagent.memory.compile.resume import compile_resume

        result = compile_resume(text, filename=filename, source=source)
        result.doc_type = DocType.RESUME
        return result

    return ProfileCompileResult(source=source, doc_type=doc_type)


def apply_compile_result(result: ProfileCompileResult) -> dict[str, int]:
    """Apply compile result to Hot (+ Warm when memories present)."""
    from localagent.memory.profile_pin import apply_profile_updates, pin_facts_to_profile
    from localagent.memory.save import save_extracted

    stats = {"profile_updates": 0, "warm_saved": 0}
    if result.profile_updates:
        if apply_profile_updates(result.profile_updates):
            stats["profile_updates"] = len(result.profile_updates)

    if result.warm_memories:
        meta: dict[str, Any] = {"source": "profile_compile"}
        if result.source:
            meta["source_file"] = result.source
        ids = save_extracted(
            result.warm_memories,
            metadata=meta,
        )
        stats["warm_saved"] = len(ids)
    elif result.profile_updates and stats["profile_updates"] == 0:
        if apply_profile_updates(result.profile_updates):
            stats["profile_updates"] = len(result.profile_updates)

    return stats


def compile_kb_profiles(*, force: bool = False) -> dict[str, int]:
    """Scan KB directory and compile resume-like documents."""
    from localagent import config
    from localagent.ingest.loader import load_file

    stats = {"files": 0, "profile_updates": 0, "warm_saved": 0}
    kb = config.KB_DIR
    if not kb.is_dir():
        return stats

    for path in sorted(kb.iterdir()):
        if not path.is_file() and not path.is_symlink():
            continue
        doc = load_file(path)
        if doc is None:
            continue
        result = compile_document_profile(
            filename=doc.filename,
            text=doc.text,
            source_path=doc.filename,
        )
        if result.doc_type.value != "resume" and not result.profile_updates:
            continue
        applied = apply_compile_result(result)
        stats["files"] += 1
        stats["profile_updates"] += applied.get("profile_updates", 0)
        stats["warm_saved"] += applied.get("warm_saved", 0)
    return stats


def compile_warm_identity_facts() -> dict[str, int]:
    """Re-pin identity-related Warm facts into Hot profile."""
    from localagent.memory.conversation_extract import ExtractedMemory
    from localagent.memory.profile_pin import pin_facts_to_profile
    from localagent.memory.store import get_memory_store

    texts: list[str] = []
    memories: list[ExtractedMemory] = []
    identity_markers = ("居住", "职业", "工作", "我叫", "姓名", "喜欢", "偏好", "工程师", "经理")
    for fact in get_memory_store().all_facts():
        text = (fact.text or "").strip()
        if not text:
            continue
        if not any(marker in text for marker in identity_markers):
            continue
        texts.append(text)
        slots = (fact.metadata or {}).get("slots") or {}
        memories.append(
            ExtractedMemory(
                text=text,
                slots={str(k): str(v) for k, v in slots.items() if v} if isinstance(slots, dict) else {},
                memory_type=str((fact.metadata or {}).get("type") or "fact"),
            )
        )

    if texts:
        from localagent.memory.profile_pin import pin_facts_to_profile, pin_from_memory_slots

        pin_facts_to_profile(texts)
        pin_from_memory_slots(memories)
    return {"facts_scanned": len(texts)}


def compile_all_sources(*, source: str = "all", force: bool = False) -> dict[str, int]:
    """Batch compile Hot profile from KB and/or Warm."""
    merged: dict[str, int] = {}
    if source in {"kb", "all"}:
        kb_stats = compile_kb_profiles(force=force)
        merged.update({f"kb_{k}": v for k, v in kb_stats.items()})
    if source in {"warm", "all"}:
        warm_stats = compile_warm_identity_facts()
        merged.update({f"warm_{k}": v for k, v in warm_stats.items()})
    return merged
