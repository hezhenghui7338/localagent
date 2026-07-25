"""CLI commands for MCP management."""

from __future__ import annotations

import argparse
import json

from localagent.mcp.config import load_mcp_config, mcp_available, resolve_mcp_config_path
from localagent.mcp.client_pool import McpClientPool
from localagent.mcp.errors import McpNotAvailableError
from localagent.mcp.serve import run_mcp_server
from localagent.mcp.tool_registry import ToolRegistry


def format_mcp_status_lines() -> list[str]:
    if not mcp_available():
        return ["MCP: 未安装（pip install 'la-localagent[mcp]'）"]
    config_path = resolve_mcp_config_path()
    servers = load_mcp_config()
    if not servers:
        return [f"MCP: 未配置（{config_path}）"]
    ToolRegistry.reload()
    statuses = McpClientPool.statuses()
    connected = sum(1 for s in statuses.values() if s.connected)
    tool_total = sum(s.tool_count for s in statuses.values())
    lines = [
        f"MCP: {connected}/{len(servers)} server 已连接 · {tool_total} 工具 · 配置 {config_path}",
    ]
    for sid, status in sorted(statuses.items()):
        state = "ok" if status.connected else "err"
        detail = f"{status.tool_count} tools" if status.connected else (status.error or "disconnected")
        lines.append(f"  · {sid} [{state}] {detail}")
    return lines


def cmd_mcp_list(_args: argparse.Namespace) -> int:
    if not mcp_available():
        print("MCP 未安装。运行: pip install 'la-localagent[mcp]'")
        return 1
    print(f"配置: {resolve_mcp_config_path()}")
    servers = load_mcp_config()
    if not servers:
        print("无已启用的 MCP server。")
        return 0
    ToolRegistry.reload()
    for sid, status in sorted(McpClientPool.statuses().items()):
        mark = "✓" if status.connected else "✗"
        print(f"{mark} {sid} ({status.config.transport}, src={status.config.source})")
        if status.error:
            print(f"    错误: {status.error}")
        elif status.tools:
            for name in status.tools:
                print(f"    - {name}")
        else:
            print("    (无工具)")
    return 0


def cmd_mcp_test(args: argparse.Namespace) -> int:
    if not mcp_available():
        print("MCP 未安装。运行: pip install 'la-localagent[mcp]'")
        return 1
    server_id = str(args.server or "").strip()
    if not server_id:
        print("用法: la mcp test <server>")
        return 1
    servers = load_mcp_config()
    if server_id not in servers and server_id not in {s for s in servers}:
        # try normalized match
        from localagent.mcp.schema_adapter import normalize_server_id

        norm = normalize_server_id(server_id)
        if norm not in servers:
            print(f"未知 server: {server_id}")
            return 1
        server_id = norm
    ToolRegistry.reload()
    status = McpClientPool.test_server(server_id)
    if status.connected:
        print(f"✓ {server_id}: {status.tool_count} tools")
        for name in status.tools:
            print(f"  - {name}")
        return 0
    print(f"✗ {server_id}: {status.error or '连接失败'}")
    return 1


def cmd_mcp_tools(args: argparse.Namespace) -> int:
    if not mcp_available():
        print("MCP 未安装。运行: pip install 'la-localagent[mcp]'")
        return 1
    ToolRegistry.reload()
    server_filter = str(getattr(args, "server", "") or "").strip()
    specs = ToolRegistry.mcp_tools()
    if server_filter:
        from localagent.mcp.schema_adapter import normalize_server_id

        sid = normalize_server_id(server_filter)
        specs = [s for s in specs if s.server_id == sid]
    if not specs:
        print("无 MCP 工具。")
        return 0
    for spec in specs:
        print(json.dumps(spec.la_definition, ensure_ascii=False, indent=2))
        print("")
    return 0


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    transport = str(getattr(args, "transport", "stdio") or "stdio").strip()
    if transport == "http":
        transport = "streamable-http"
    host = str(getattr(args, "host", "127.0.0.1") or "127.0.0.1")
    port = int(getattr(args, "port", 8765) or 8765)
    try:
        run_mcp_server(transport=transport, host=host, port=port)  # type: ignore[arg-type]
    except McpNotAvailableError as exc:
        print(exc)
        return 1
    except KeyboardInterrupt:
        print("\n[MCP] 已停止")
        return 0
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    action = getattr(args, "mcp_action", None) or "list"
    if action == "list":
        return cmd_mcp_list(args)
    if action == "test":
        return cmd_mcp_test(args)
    if action == "tools":
        return cmd_mcp_tools(args)
    if action == "serve":
        return cmd_mcp_serve(args)
    print(f"未知 mcp 子命令: {action}")
    return 1
