"""Pre-execution tool call sanity checks (milestone-aware)."""

from __future__ import annotations

import re

from localagent.agent.validation.types import ValidationResult

_MUTATION_OBJECTIVE_RE = re.compile(
    r"(?:修改|改|写|创建|添加|更新|修复|edit|write|create|fix|update|append)",
    re.IGNORECASE,
)
_READ_ONLY_TOOLS = frozenset({"read_file", "glob", "grep"})
_SIDE_EFFECT_TOOLS = frozenset({"write_file", "edit_file", "run_shell"})


def check_tool_call(
    tool_name: str,
    arguments: dict | None,
    *,
    milestone_objective: str = "",
    tool_calls: list[dict] | None = None,
) -> ValidationResult | None:
    """Return a validation result when the tool choice looks mismatched; else None."""
    _ = arguments  # reserved for future argument-level checks
    objective = (milestone_objective or "").strip()
    if not objective or not _MUTATION_OBJECTIVE_RE.search(objective):
        return None
    name = (tool_name or "").strip()
    if name not in _READ_ONLY_TOOLS:
        return None

    prior = tool_calls or []
    if any(str(c.get("name") or "") in _SIDE_EFFECT_TOOLS for c in prior):
        return None

    read_count = sum(
        1 for c in prior if str(c.get("name") or "") in _READ_ONLY_TOOLS
    )
    if read_count < 2:
        return None

    return ValidationResult.warn(
        "当前步骤目标含修改/写入，已连续多次只读检索仍未变更文件。",
        retry_hint="请改用 edit_file 或 write_file 完成修改；必要时用 run_shell 执行命令。",
        pre_call=True,
        read_only_streak=read_count + 1,
    )


def build_pre_call_followup(result: ValidationResult) -> str:
    """User message when a tool call is blocked or redirected before execution."""
    hint = result.retry_hint or "请调整工具选择后重试。"
    marker = result.markers[0] if result.markers else "【工具选择警告】"
    return (
        f"{marker}{hint}"
        "不要再次连续调用 read_file/glob/grep；"
        "若信息已足够，请直接执行写入或编辑操作。"
    )
