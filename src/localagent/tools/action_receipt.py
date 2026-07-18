"""Action receipt — structured summary of side-effect tools in a turn."""

from __future__ import annotations

from typing import Any

SIDE_EFFECT_TOOLS = frozenset({"run_shell", "write_file", "edit_file"})


def record_side_effect(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    outcome: str = "executed",
) -> dict[str, Any] | None:
    """Build a receipt item for a completed side-effect tool, or None if N/A."""
    if tool_name not in SIDE_EFFECT_TOOLS or outcome != "executed":
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


def format_action_receipt(actions: list[dict[str, Any]]) -> str | None:
    """Format a Chinese Action receipt block, or None when empty."""
    if not actions:
        return None
    lines = ["【Action receipt】"]
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
        else:
            lines.append(f"- {tool}: {summary}")
    return "\n".join(lines)


def append_action_receipt(response: str, actions: list[dict[str, Any]]) -> str:
    """Append receipt to the assistant response when side effects ran."""
    receipt = format_action_receipt(actions)
    if not receipt:
        return response
    body = (response or "").rstrip()
    if not body:
        return receipt
    if "【Action receipt】" in body:
        return body
    return f"{body}\n\n{receipt}"
