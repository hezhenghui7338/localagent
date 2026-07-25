"""Turn-level Context Engine — JIT prefetch, budget, and message assembly."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from localagent.context.assemble import build_system_prompt
from localagent.context.budget import budget_prefetch_blocks
from localagent.context.fetchers import fetch_prefetch_blocks
from localagent.context.router import route_prefetch_modules
from localagent.context.types import ContextBlocks, TurnContext
from localagent.mcp.tool_registry import get_tool_definitions
from localagent.models.router import ChatMessage

logger = logging.getLogger(__name__)


class ContextEngine:
    """Build turn-level LLM context: route → prefetch → budget → messages."""

    def build_turn_context(
        self,
        user_message: str,
        history: list[dict[str, str]] | None,
        *,
        session_id: str | None = None,
        document_context: str | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> TurnContext:
        route = route_prefetch_modules(user_message)
        logger.info(
            "context engine route modules=%s confidence=%.2f source=%s",
            route.modules,
            route.confidence,
            route.source,
        )

        raw_blocks, hits = fetch_prefetch_blocks(
            user_message,
            history,
            session_id,
            route,
            on_status=on_status,
        )
        if hits.get("work"):
            logger.info("agent prefetch work=yes")
        for module in ("personal", "archive", "session", "web", "workspace", "aware"):
            if hits.get(module):
                logger.info("agent prefetch %s=yes", module)

        budgeted_dict = budget_prefetch_blocks(
            raw_blocks.as_dict(),
            session_first=route.session_first,
        )
        blocks = ContextBlocks.from_dict(budgeted_dict)
        doc_ctx = (document_context or "").strip()
        tool_defs = get_tool_definitions()

        def rebuild_system(**kwargs: Any) -> str:
            merged_tools = kwargs.pop("tool_definitions", tool_defs)
            return build_system_prompt(
                personal_context=blocks.personal,
                archive_context=blocks.archive,
                session_context=blocks.session,
                web_context=blocks.web,
                workspace_context=blocks.workspace,
                aware_context=blocks.aware,
                work_context=blocks.work,
                document_context=doc_ctx,
                tool_definitions=merged_tools,
                **kwargs,
            )

        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=rebuild_system()),
        ]
        if history:
            for msg in history[-10:]:
                messages.append(ChatMessage(role=msg["role"], content=msg["content"]))
        messages.append(ChatMessage(role="user", content=user_message))

        return TurnContext(
            messages=messages,
            blocks=blocks,
            route=route,
            rebuild_system=rebuild_system,
            metadata={
                "prefetch_hits": hits,
                "route_modules": list(route.modules),
                "route_confidence": route.confidence,
                "route_source": route.source,
            },
        )
