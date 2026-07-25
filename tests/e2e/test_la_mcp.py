"""E2E MCP CLI: list, tools, connection test."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from helpers import PROJECT_ROOT, run_la

pytestmark = [pytest.mark.e2e, pytest.mark.xdist_group("serial")]

ECHO_SERVER = PROJECT_ROOT / "tests" / "fixtures" / "mcp_echo_server.py"


def test_e2e_mcp_list_disabled(la_env):
    """Default e2e env keeps MCP off — list should succeed with empty/disabled message."""
    result = run_la(["mcp", "list"], env=la_env)
    assert result.returncode == 0
    assert "无已启用" in result.stdout or "未配置" in result.stdout or "MCP" in result.stdout



@pytest.fixture
def la_env_mcp(la_env, tmp_path: Path):
    echo_server = str(ECHO_SERVER.resolve())
    mcp_yaml = tmp_path / "mcp.yaml"
    mcp_yaml.write_text(
        f"""
defaults:
  approval: off
  timeout_seconds: 30
import_cursor: false
servers:
  echo:
    transport: stdio
    command: {sys.executable}
    args: ["{echo_server}"]
    enabled: true
""",
        encoding="utf-8",
    )
    return {
        **la_env,
        "LA_MCP_ENABLED": "1",
        "LA_MCP_CONFIG": str(mcp_yaml.resolve()),
        "LA_MCP_IMPORT_CURSOR": "0",
    }


def test_e2e_mcp_list_with_echo_server(la_env_mcp):
    result = run_la(["mcp", "list"], env=la_env_mcp, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "echo" in result.stdout.lower(), result.stdout

    tools = run_la(["mcp", "tools", "--server", "echo"], env=la_env_mcp, timeout=90)
    assert tools.returncode == 0, tools.stdout + tools.stderr
    assert "echo" in tools.stdout.lower(), tools.stdout


def test_e2e_mcp_test_connection(la_env_mcp):
    result = run_la(["mcp", "test", "echo"], env=la_env_mcp, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "✓" in result.stdout or "tools" in result.stdout.lower()
