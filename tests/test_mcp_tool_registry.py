"""Tests for MCP tool registry and approval integration."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from localagent.mcp.config import mcp_available
from localagent.mcp.tool_registry import ToolRegistry
from localagent.mcp.types import McpServerConfig
from localagent.tools.approval import classify_tool, needs_approval

pytestmark = pytest.mark.xdist_group("serial")

ECHO_SERVER = Path(__file__).resolve().parent / "fixtures" / "mcp_echo_server.py"


@pytest.fixture(autouse=True)
def _enable_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LA_MCP_ENABLED", "1")
    monkeypatch.setattr("localagent.config.MCP_ENABLED", True)


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    ToolRegistry.shutdown()
    yield
    ToolRegistry.shutdown()


@pytest.mark.skipif(not mcp_available(), reason="mcp package not installed")
def test_registry_execute_mcp_tool() -> None:
    cfg = McpServerConfig(
        server_id="echo",
        transport="stdio",
        command=sys.executable,
        args=(str(ECHO_SERVER),),
        timeout_seconds=20,
    )
    with patch("localagent.mcp.tool_registry.load_mcp_config", return_value={"echo": cfg}):
        ToolRegistry.reload()
    la_name = "mcp__echo__echo"
    defs = ToolRegistry.all_definitions()
    assert any(d["name"] == la_name for d in defs)
    result = ToolRegistry.execute(la_name, {"msg": "ping"})
    assert "echo: ping" in result


def test_mcp_approval_defaults_dangerous() -> None:
    with patch("localagent.tools.approval._mcp_server_approval", return_value="dangerous"):
        risk = classify_tool("mcp__srv__do_thing", {"x": 1})
        assert risk.level == "dangerous"
        assert needs_approval("mcp__srv__do_thing", risk, policy="always")


def test_mcp_approval_off_skips_gate() -> None:
    with patch("localagent.tools.approval._mcp_server_approval", return_value="off"):
        risk = classify_tool("mcp__srv__read", {})
        assert risk.level == "safe"
        assert not needs_approval("mcp__srv__read", risk, policy="always")
