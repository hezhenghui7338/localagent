"""MCP configuration and tool types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ApprovalPolicy = Literal["always", "dangerous", "off"]
TransportType = Literal["stdio", "http"]


@dataclass(frozen=True)
class McpDefaults:
    enabled: bool = True
    approval: ApprovalPolicy = "dangerous"
    timeout_seconds: int = 30


@dataclass(frozen=True)
class McpServerConfig:
    """Unified MCP server configuration (LA yaml + Cursor json)."""

    server_id: str
    transport: TransportType
    enabled: bool = True
    approval: ApprovalPolicy = "dangerous"
    timeout_seconds: int = 30
    # stdio
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    # http
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    source: str = "la"  # la | cursor


@dataclass(frozen=True)
class McpToolSpec:
    """A tool discovered from an MCP server."""

    server_id: str
    original_name: str
    la_name: str
    description: str
    input_schema: dict[str, Any]
    la_definition: dict[str, Any]


@dataclass
class McpServerStatus:
    """Runtime health snapshot for one MCP server."""

    config: McpServerConfig
    connected: bool = False
    error: str = ""
    tool_count: int = 0
    tools: list[str] = field(default_factory=list)
