"""Milestone-level observation summaries."""

from __future__ import annotations

from localagent.context.compress.core import compress_observation


def summarize_for_milestone(
    tool_name: str,
    result: str,
    *,
    limit: int = 200,
    user_query: str = "",
) -> str:
    """Compress a tool observation into a short milestone summary."""
    compressed = compress_observation(
        tool_name,
        result or "",
        user_query=user_query,
        budget=limit,
    )
    text = compressed.strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
