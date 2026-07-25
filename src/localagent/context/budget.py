"""Prefetch block budget allocation for turn-level context."""

from __future__ import annotations

from localagent import config

# Prefetch blocks: higher priority kept when total budget is exceeded.
PREFETCH_PRIORITY = (
    "work",
    "personal",
    "archive",
    "session",
    "web",
    "workspace",
    "aware",
)

# When the user asks about STM (today / last session), keep session first.
PREFETCH_PRIORITY_SESSION_FIRST = (
    "session",
    "work",
    "personal",
    "archive",
    "web",
    "workspace",
    "aware",
)


def default_prefetch_budget() -> int:
    return max(200, int(getattr(config, "PREFETCH_BUDGET_CHARS", 1500)))


def budget_prefetch_blocks(
    blocks: dict[str, str],
    *,
    budget: int | None = None,
    session_first: bool = False,
) -> dict[str, str]:
    """Shrink prefetch blocks so their combined size fits ``budget``.

    Priority (kept first): personal → archive → session → web → workspace.
    When ``session_first`` is True (STM recall), session is kept ahead of others.
    Lower-priority blocks are truncated or dropped when over budget.
    """
    from localagent.context.compress.core import apply_context_budget

    limit = budget if budget is not None else default_prefetch_budget()
    priority = PREFETCH_PRIORITY_SESSION_FIRST if session_first else PREFETCH_PRIORITY
    ordered = [k for k in priority if blocks.get(k)]
    for key in blocks:
        if key not in ordered and blocks.get(key):
            ordered.append(key)

    result: dict[str, str] = {}
    remaining = limit
    for key in ordered:
        text = blocks.get(key) or ""
        if not text:
            continue
        if remaining <= 0:
            break
        if len(text) <= remaining:
            result[key] = text
            remaining -= len(text)
            continue
        # Partial fit: keep a truncated stub if there is room for signal.
        if remaining >= 40:
            result[key] = apply_context_budget(text, budget=remaining, label=key)
        break

    return result
