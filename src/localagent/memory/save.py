"""Interactive and direct memory save helpers."""

from __future__ import annotations

import sys
from typing import Any

from localagent.memory.hindsight_client import get_memory_backend


def save_facts(
    facts: list[str],
    *,
    metadata: dict[str, Any] | None = None,
) -> list[str]:
    """Write facts to memory without prompting."""
    if not facts:
        return []
    backend = get_memory_backend()
    return backend.retain_batch(facts, metadata=metadata or {})


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
        ids = save_facts(facts, metadata=metadata)
        return ids

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
