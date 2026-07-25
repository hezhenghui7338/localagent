"""Integration tests for MCP client pool."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from localagent.mcp.client_pool import McpClientPool
from localagent.mcp.config import mcp_available
from localagent.mcp.types import McpServerConfig

ECHO_SERVER = Path(__file__).resolve().parent / "fixtures" / "mcp_echo_server.py"


pytestmark = pytest.mark.skipif(not mcp_available(), reason="mcp package not installed")


@pytest.fixture(autouse=True)
def _enable_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LA_MCP_ENABLED", "1")
    monkeypatch.setattr("localagent.config.MCP_ENABLED", True)


@pytest.fixture(autouse=True)
def _cleanup_pool() -> None:
    yield
    McpClientPool.shutdown()


def test_stdio_echo_server_roundtrip() -> None:
    cfg = McpServerConfig(
        server_id="echo",
        transport="stdio",
        command=sys.executable,
        args=(str(ECHO_SERVER),),
        timeout_seconds=20,
    )
    McpClientPool.refresh({"echo": cfg})
    status = McpClientPool.test_server("echo")
    assert status.connected, status.error
    assert status.tool_count >= 1
    assert any("mcp__echo__echo" == t for t in status.tools)
    result = McpClientPool.call_tool("echo", "echo", {"msg": "hello"})
    assert "echo: hello" in result


def test_isolated_server_failure() -> None:
    bad = McpServerConfig(
        server_id="bad",
        transport="stdio",
        command="false",
        args=(),
        timeout_seconds=5,
    )
    good = McpServerConfig(
        server_id="echo",
        transport="stdio",
        command=sys.executable,
        args=(str(ECHO_SERVER),),
        timeout_seconds=20,
    )
    McpClientPool.refresh({"bad": bad, "echo": good})
    bad_status = McpClientPool.test_server("bad")
    good_status = McpClientPool.test_server("echo")
    assert not bad_status.connected
    assert good_status.connected
