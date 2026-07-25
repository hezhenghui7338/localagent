"""MCP server mode — expose LocalAgent tools to external hosts."""

from __future__ import annotations

import logging
import os
from typing import Literal

from localagent.mcp.config import mcp_available
from localagent.mcp.errors import McpNotAvailableError

logger = logging.getLogger(__name__)

# Whitelist of LA tools exposed via MCP (no shell/file mutation by default).
SERVE_TOOL_NAMES = (
    "search_memory",
    "query_memories",
    "reflect_memory",
    "search_knowledge",
    "retain_memory",
    "workspace_context",
)


def _optional_web_search() -> bool:
    return os.getenv("LA_MCP_SERVE_WEB_SEARCH", "").strip().lower() in ("1", "true", "yes")


def run_mcp_server(
    *,
    transport: Literal["stdio", "streamable-http"] = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    if not mcp_available():
        raise McpNotAvailableError("未安装 mcp 包，请运行: pip install 'la-localagent[mcp]'")

    from mcp.server.fastmcp import FastMCP

    from localagent.tools import (
        query_memories_tool,
        reflect_memory,
        retain_memory,
        search_knowledge,
        search_memory,
        workspace_context_tool,
    )

    app = FastMCP(
        "localagent",
        instructions=(
            "LocalAgent MCP server — 暴露本地记忆与知识库检索。"
            "写入记忆可能进入 pending 审批队列。"
        ),
    )

    @app.tool()
    def search_memory_tool(query: str) -> str:
        """搜索用户长期记忆。"""
        return search_memory(query)

    @app.tool()
    def query_memories(
        query: str = "",
        tags: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        sort: str = "newest",
        limit: int = 20,
    ) -> str:
        """浏览或查询本地记忆库。"""
        return query_memories_tool(
            query=query,
            tags=tags,
            since=since,
            until=until,
            sort=sort,
            limit=limit,
        )

    @app.tool()
    def reflect_memory_tool(query: str) -> str:
        """多跳综合推理：记忆 + 知识库。"""
        return reflect_memory(query)

    @app.tool()
    def search_knowledge_tool(query: str, since: str | None = None, until: str | None = None) -> str:
        """搜索知识库文档与对话归档。"""
        kwargs: dict = {}
        if since:
            kwargs["since"] = since
        if until:
            kwargs["until"] = until
        return search_knowledge(query, **kwargs)

    @app.tool()
    def retain_memory_tool(content: str) -> str:
        """将用户明确要求记住的内容写入长期记忆。"""
        return retain_memory(content)

    @app.tool()
    def workspace_context(days: int = 7) -> str:
        """获取工作区上下文（Git、最近文件、托管待办）。"""
        return workspace_context_tool(days=days)

    if _optional_web_search():
        from localagent.tools.web_search import web_search

        @app.tool()
        def web_search_tool(query: str) -> str:
            """联网搜索最新信息。"""
            return web_search(query)

    if transport == "streamable-http":
        token = os.getenv("LA_MCP_SERVE_TOKEN", "").strip()
        if not token:
            logger.warning("LA_MCP_SERVE_TOKEN 未设置，HTTP 模式无鉴权保护")
        os.environ.setdefault("FASTMCP_HOST", host)
        os.environ.setdefault("FASTMCP_PORT", str(port))

    logger.info("starting localagent mcp server transport=%s tools=%s", transport, SERVE_TOOL_NAMES)
    app.run(transport=transport)
