"""Model Context Protocol integration for LocalAgent."""

from localagent.mcp.client_pool import McpClientPool
from localagent.mcp.config import load_mcp_config, mcp_available, resolve_mcp_config_path
from localagent.mcp.errors import (
    McpConfigError,
    McpConnectionError,
    McpError,
    McpNotAvailableError,
    McpToolError,
)
from localagent.mcp.schema_adapter import is_mcp_tool_name, parse_mcp_la_tool_name
from localagent.mcp.serve import run_mcp_server
from localagent.mcp.tool_registry import ToolRegistry, get_tool_definitions

__all__ = [
    "McpClientPool",
    "McpConfigError",
    "McpConnectionError",
    "McpError",
    "McpNotAvailableError",
    "McpToolError",
    "ToolRegistry",
    "get_tool_definitions",
    "is_mcp_tool_name",
    "load_mcp_config",
    "mcp_available",
    "parse_mcp_la_tool_name",
    "resolve_mcp_config_path",
    "run_mcp_server",
]
