"""Tests for MCP config loading and schema adaptation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from localagent.mcp.config import (
    interpolate_string,
    load_mcp_config,
)
from localagent.mcp.schema_adapter import (
    json_schema_to_la_parameters,
    mcp_la_tool_name,
    mcp_tool_to_la_definition,
    parse_mcp_la_tool_name,
)


def test_interpolate_env_and_userhome(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_TOKEN", "secret123")
    text = interpolate_string("${env:MY_TOKEN} at ${userHome}/data")
    assert "secret123" in text
    assert str(Path.home()) in text


def test_mcp_tool_naming() -> None:
    la_name = mcp_la_tool_name("File System", "read_file")
    assert la_name == "mcp__file_system__read_file"
    parsed = parse_mcp_la_tool_name(la_name)
    assert parsed == ("file_system", "read_file")


def test_json_schema_to_la_parameters() -> None:
    schema = {
        "type": "object",
        "properties": {
            "msg": {"type": "string", "description": "message body"},
            "limit": {"type": "integer"},
        },
        "required": ["msg"],
    }
    params = json_schema_to_la_parameters(schema)
    assert "msg" in params
    assert "必填" in params["msg"]
    assert "limit" in params
    assert "可选" in params["limit"]


def test_mcp_tool_to_la_definition() -> None:
    spec = mcp_tool_to_la_definition(
        server_id="echo",
        name="echo",
        description="Echo input",
        input_schema={"type": "object", "properties": {"msg": {"type": "string"}}},
    )
    assert spec.la_name == "mcp__echo__echo"
    assert "[MCP:echo]" in spec.la_definition["description"]


def test_load_mcp_config_merge_cursor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    la_yaml = tmp_path / "mcp.yaml"
    la_yaml.write_text(
        """
defaults:
  approval: dangerous
  timeout_seconds: 15
import_cursor: true
cursor_paths: []
servers:
  local_echo:
    transport: stdio
    command: echo
    args: ["hello"]
    enabled: true
""",
        encoding="utf-8",
    )
    cursor_json = tmp_path / "mcp.json"
    cursor_json.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "cursor_only": {
                        "command": "true",
                        "args": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LA_MCP_ENABLED", "1")
    monkeypatch.setenv("LA_MCP_CONFIG", str(la_yaml))
    monkeypatch.setenv("LA_MCP_IMPORT_CURSOR", "0")

    servers = load_mcp_config(path=la_yaml)
    assert "local_echo" in servers
    assert servers["local_echo"].command == "echo"

    la_yaml.write_text(
        la_yaml.read_text(encoding="utf-8").replace(
            "cursor_paths: []",
            f"cursor_paths:\n  - {cursor_json}",
        ),
        encoding="utf-8",
    )
    merged = load_mcp_config(path=la_yaml)
    assert "local_echo" in merged
    assert "cursor_only" in merged


def test_load_mcp_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LA_MCP_ENABLED", "0")
    assert load_mcp_config() == {}
