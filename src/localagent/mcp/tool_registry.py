"""Unified built-in + MCP tool registry."""

from __future__ import annotations

import logging
from typing import Any

from localagent import config
from localagent.mcp.client_pool import McpClientPool
from localagent.mcp.config import load_mcp_config, mcp_available
from localagent.mcp.schema_adapter import is_mcp_tool_name, parse_mcp_la_tool_name
from localagent.mcp.types import McpToolSpec
from localagent.tools import TOOL_DEFINITIONS, execute_builtin_tool

logger = logging.getLogger(__name__)

_registry_initialized = False


class ToolRegistry:
    """Merge built-in tools with MCP-discovered tools."""

    @staticmethod
    def ensure_loaded() -> None:
        global _registry_initialized
        if _registry_initialized:
            return
        servers = load_mcp_config()
        if servers:
            McpClientPool.refresh(servers)
        _registry_initialized = True

    @staticmethod
    def reload() -> None:
        global _registry_initialized
        servers = load_mcp_config()
        McpClientPool.refresh(servers)
        _registry_initialized = True

    @staticmethod
    def builtin_definitions() -> list[dict[str, Any]]:
        return list(TOOL_DEFINITIONS)

    @staticmethod
    def mcp_tools() -> list[McpToolSpec]:
        ToolRegistry.ensure_loaded()
        return McpClientPool.all_tools()

    @staticmethod
    def mcp_definitions() -> list[dict[str, Any]]:
        return [spec.la_definition for spec in ToolRegistry.mcp_tools()]

    @staticmethod
    def all_definitions(*, max_mcp: int | None = None) -> list[dict[str, Any]]:
        ToolRegistry.ensure_loaded()
        builtin = ToolRegistry.builtin_definitions()
        mcp_defs = ToolRegistry.mcp_definitions()
        cap = max_mcp if max_mcp is not None else config.MCP_MAX_TOOLS
        if cap > 0 and len(mcp_defs) > cap:
            mcp_defs = mcp_defs[:cap]
        return builtin + mcp_defs

    @staticmethod
    def get_mcp_tool_spec(la_name: str) -> McpToolSpec | None:
        for spec in ToolRegistry.mcp_tools():
            if spec.la_name == la_name:
                return spec
        return None

    @staticmethod
    def get_server_approval(server_id: str) -> str:
        from localagent.mcp.config import load_mcp_config

        servers = load_mcp_config()
        cfg = servers.get(server_id)
        return cfg.approval if cfg else "dangerous"

    @staticmethod
    def execute(name: str, arguments: dict[str, Any]) -> str:
        ToolRegistry.ensure_loaded()
        if is_mcp_tool_name(name):
            parsed = parse_mcp_la_tool_name(name)
            if parsed is None:
                return f"未知 MCP 工具: {name}"
            server_id, tool_name = parsed
            if not mcp_available():
                return "错误: 未安装 mcp 包，请运行 pip install 'la-localagent[mcp]'"
            try:
                return McpClientPool.call_tool(server_id, tool_name, arguments)
            except Exception as exc:
                return f"错误: MCP 工具执行失败: {exc}"
        return execute_builtin_tool(name, arguments)

    @staticmethod
    def shutdown() -> None:
        global _registry_initialized
        McpClientPool.shutdown()
        _registry_initialized = False


def get_tool_definitions(*, max_mcp: int | None = None) -> list[dict[str, Any]]:
    return ToolRegistry.all_definitions(max_mcp=max_mcp)
