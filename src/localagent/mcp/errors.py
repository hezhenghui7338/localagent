"""MCP-specific errors."""


class McpError(Exception):
    """Base MCP error."""


class McpNotAvailableError(McpError):
    """Raised when the optional ``mcp`` package is not installed."""


class McpConfigError(McpError):
    """Invalid or missing MCP configuration."""


class McpConnectionError(McpError):
    """Failed to connect to an MCP server."""


class McpToolError(McpError):
    """Tool call failed on an MCP server."""
