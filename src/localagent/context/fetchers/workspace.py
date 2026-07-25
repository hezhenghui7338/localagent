"""Workspace git/recent-files prefetch."""

from __future__ import annotations

from localagent.context.compress import compress_observation
from localagent.context.router import PrefetchRoute, prefetch_header


def prefetch_workspace_context(
    user_message: str,
    *,
    route: PrefetchRoute | None = None,
) -> str:
    from localagent.tools import workspace_context_tool

    result = compress_observation("workspace_context", workspace_context_tool(days=7))
    if not result:
        return ""
    return "\n".join(
        [
            prefetch_header(
                route,
                "workspace",
                strong="[工作区上下文（已预加载，直接回答，勿再调用 workspace_context）]",
                soft="[工作区上下文（已预加载，可优先据此回答；不足时再调用 workspace_context）]",
            ),
            result,
        ]
    )
