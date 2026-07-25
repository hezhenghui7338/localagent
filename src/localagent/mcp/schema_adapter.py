"""Adapt MCP JSON Schema tool definitions to LA prompt format."""

from __future__ import annotations

import json
import re
from typing import Any

from localagent.mcp.types import McpToolSpec

_MCP_PREFIX = "mcp__"


def normalize_server_id(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower()
    return slug or "server"


def mcp_la_tool_name(server_id: str, tool_name: str) -> str:
    return f"{_MCP_PREFIX}{normalize_server_id(server_id)}__{tool_name}"


def parse_mcp_la_tool_name(la_name: str) -> tuple[str, str] | None:
    if not la_name.startswith(_MCP_PREFIX):
        return None
    rest = la_name[len(_MCP_PREFIX) :]
    if "__" not in rest:
        return None
    server_id, tool_name = rest.split("__", 1)
    if not server_id or not tool_name:
        return None
    return server_id, tool_name


def is_mcp_tool_name(name: str) -> bool:
    return parse_mcp_la_tool_name(name) is not None


def _schema_property_description(name: str, spec: dict[str, Any]) -> str:
    desc = str(spec.get("description") or spec.get("title") or "").strip()
    ptype = spec.get("type")
    if isinstance(ptype, list):
        ptype = next((t for t in ptype if t != "null"), ptype[0] if ptype else "")
    if ptype:
        type_hint = f"类型: {ptype}"
        return f"{desc} ({type_hint})" if desc else type_hint
    return desc or name


def json_schema_to_la_parameters(schema: dict[str, Any] | None) -> dict[str, str]:
    """Convert MCP inputSchema to LA simplified parameters dict."""
    if not schema or not isinstance(schema, dict):
        return {}
    props = schema.get("properties")
    if not isinstance(props, dict):
        return {}
    required = set(schema.get("required") or [])
    params: dict[str, str] = {}
    for key, spec in props.items():
        if not isinstance(spec, dict):
            continue
        desc = _schema_property_description(str(key), spec)
        if key in required:
            desc = f"必填。{desc}" if desc else "必填"
        else:
            desc = f"可选。{desc}" if desc else "可选"
        params[str(key)] = desc
    return params


def mcp_tool_to_la_definition(
    *,
    server_id: str,
    name: str,
    description: str,
    input_schema: dict[str, Any] | None,
) -> McpToolSpec:
    schema = input_schema if isinstance(input_schema, dict) else {}
    la_name = mcp_la_tool_name(server_id, name)
    la_params = json_schema_to_la_parameters(schema)
    la_def: dict[str, Any] = {
        "name": la_name,
        "description": f"[MCP:{server_id}] {description}".strip(),
        "parameters": la_params,
        "mcp_server": normalize_server_id(server_id),
        "mcp_tool": name,
    }
    if schema:
        la_def["input_schema"] = schema
    return McpToolSpec(
        server_id=normalize_server_id(server_id),
        original_name=name,
        la_name=la_name,
        description=description,
        input_schema=schema,
        la_definition=la_def,
    )


def format_tool_result_content(content: Any) -> str:
    """Serialize MCP CallToolResult content blocks to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    blocks = getattr(content, "content", content)
    if not isinstance(blocks, list):
        return str(blocks)
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict):
            btype = block.get("type")
            if btype == "text":
                parts.append(str(block.get("text") or ""))
            elif btype == "image":
                data = block.get("data") or ""
                mime = block.get("mimeType") or "image"
                parts.append(f"[MCP 返回 {mime} 图像，{len(str(data))} 字节]")
            else:
                parts.append(json.dumps(block, ensure_ascii=False))
            continue
        btype = getattr(block, "type", None)
        if btype == "text":
            parts.append(str(getattr(block, "text", "") or ""))
        elif btype == "image":
            data = getattr(block, "data", "") or ""
            mime = getattr(block, "mimeType", None) or "image"
            parts.append(f"[MCP 返回 {mime} 图像，{len(str(data))} 字节]")
        else:
            parts.append(str(block))
    return "\n".join(p for p in parts if p).strip()
