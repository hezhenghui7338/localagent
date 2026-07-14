"""Interactive and direct memory save helpers."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from localagent.memory.backend import get_memory_backend

if TYPE_CHECKING:
    from localagent.memory.conversation_extract import ExtractedMemory


def save_facts(
    facts: list[str],
    *,
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    """Write facts to memory without prompting."""
    if not facts:
        return []
    backend = get_memory_backend()
    ids = backend.retain_batch(facts, metadata=metadata or {})
    from localagent.memory.profile_pin import pin_facts_to_profile

    pin_facts_to_profile(facts)
    return ids


def save_extracted(
    memories: list[ExtractedMemory],
    *,
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    """Write ExtractedMemory items, attaching slots/type/tags into per-fact metadata."""
    if not memories:
        return []
    backend = get_memory_backend()
    base = dict(metadata or {})
    ids: list[str] = []
    texts: list[str] = []
    for mem in memories:
        meta = {**base, **mem.to_metadata_extra()}
        fact_id = backend.retain(mem.text, metadata=meta)
        if fact_id:
            ids.append(fact_id)
            texts.append(mem.text)
    if texts:
        from localagent.memory.profile_pin import pin_facts_to_profile

        pin_facts_to_profile(texts)
    return ids


def _should_save_interactively(*, interactive: bool | None) -> bool:
    if interactive is not None:
        return interactive
    return sys.stdin.isatty()


def confirm_save_facts(
    facts: list[str],
    *,
    metadata: dict[str, Any] | None = None,
    title: str | None = None,
    interactive: bool | None = None,
) -> list[str]:
    """Prompt to save extracted facts. Default: save. Returns saved fact ids."""
    if not facts:
        return []

    if not _should_save_interactively(interactive=interactive):
        return save_facts(facts, metadata=metadata)

    label = title or f"提取到 {len(facts)} 条记忆"
    print(f"\n[记忆] {label}：")
    for index, fact in enumerate(facts, start=1):
        print(f"  {index}. {fact}")

    try:
        answer = input("保存？[Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        answer = ""

    if answer in ("n", "no"):
        print("[记忆] 已跳过")
        return []

    ids = save_facts(facts, metadata=metadata)
    print(f"[记忆] 已保存 {len(ids)} 条")
    return ids


def confirm_save_extracted(
    memories: list[ExtractedMemory],
    *,
    metadata: dict[str, Any] | None = None,
    title: str | None = None,
    interactive: bool | None = None,
) -> list[str]:
    """Prompt to save ExtractedMemory list (same UX as confirm_save_facts)."""
    if not memories:
        return []
    if not _should_save_interactively(interactive=interactive):
        return save_extracted(memories, metadata=metadata)

    label = title or f"提取到 {len(memories)} 条记忆"
    print(f"\n[记忆] {label}：")
    for index, mem in enumerate(memories, start=1):
        print(f"  {index}. {mem.text}")

    try:
        answer = input("保存？[Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        answer = ""

    if answer in ("n", "no"):
        print("[记忆] 已跳过")
        return []

    ids = save_extracted(memories, metadata=metadata)
    print(f"[记忆] 已保存 {len(ids)} 条")
    return ids
