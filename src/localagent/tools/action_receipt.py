"""Action receipt — structured summary of side-effect tools in a turn."""

from __future__ import annotations

import json
from typing import Any

from localagent.mcp.schema_adapter import is_mcp_tool_name, parse_mcp_la_tool_name

SIDE_EFFECT_TOOLS = frozenset({"run_shell", "write_file", "edit_file"})


def record_side_effect(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    outcome: str = "executed",
) -> dict[str, Any] | None:
    """Build a receipt item for a completed side-effect tool, or None if N/A."""
    if outcome != "executed":
        return None
    if is_mcp_tool_name(tool_name):
        parsed = parse_mcp_la_tool_name(tool_name)
        if not parsed:
            return None
        server_id, original = parsed
        try:
            args_text = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        except TypeError:
            args_text = str(arguments)
        if len(args_text) > 120:
            args_text = f"{args_text[:120]}…"
        return {
            "tool": tool_name,
            "outcome": outcome,
            "summary": f"{server_id}/{original} {args_text}",
        }
    if tool_name not in SIDE_EFFECT_TOOLS:
        return None
    item: dict[str, Any] = {"tool": tool_name, "outcome": outcome}
    if tool_name == "run_shell":
        cmd = str(arguments.get("command") or "").strip()
        item["summary"] = cmd if len(cmd) <= 100 else f"{cmd[:100]}…"
    else:
        path = str(arguments.get("path") or "").strip() or "(未指定路径)"
        item["summary"] = path
        if tool_name == "write_file":
            mode = str(arguments.get("mode") or "overwrite").strip().lower()
            item["mode"] = mode
    return item


def format_milestone_progress(
    *,
    completed: list[str] | None = None,
    pending: list[str] | None = None,
    partial: bool = False,
) -> str | None:
    """Format milestone progress lines for the action receipt."""
    done = [c for c in (completed or []) if c]
    todo = [p for p in (pending or []) if p]
    if not done and not todo:
        return None
    lines: list[str] = []
    if done:
        lines.append(f"已完成步骤 ({len(done)}):")
        for item in done:
            lines.append(f"  ✓ {item}")
    if todo:
        lines.append(f"待完成 ({len(todo)}):")
        for item in todo:
            lines.append(f"  ○ {item}")
    if partial:
        lines.append("（部分完成）")
    return "\n".join(lines)


def format_action_receipt(
    actions: list[dict[str, Any]],
    *,
    milestone_progress: str | None = None,
) -> str | None:
    """Format a Chinese Action receipt block, or None when empty."""
    if not actions and not milestone_progress:
        return None
    lines = ["【Action receipt】"]
    if milestone_progress:
        lines.append(milestone_progress)
    for action in actions:
        tool = str(action.get("tool") or "")
        summary = str(action.get("summary") or "")
        if tool == "run_shell":
            lines.append(f"- run_shell: {summary}")
        elif tool == "write_file":
            mode = str(action.get("mode") or "overwrite")
            lines.append(f"- write_file ({mode}): {summary}")
        elif tool == "edit_file":
            lines.append(f"- edit_file: {summary}")
        elif is_mcp_tool_name(tool):
            lines.append(f"- {tool}: {summary}")
        else:
            lines.append(f"- {tool}: {summary}")
    return "\n".join(lines)


def append_action_receipt(
    response: str,
    actions: list[dict[str, Any]],
    *,
    milestone_progress: str | None = None,
) -> str:
    """Append action receipt block to agent response when non-empty."""
    block = format_action_receipt(actions, milestone_progress=milestone_progress)
    if not block:
        return response
    if response.strip():
        return f"{response.rstrip()}\n\n{block}"
    return block
