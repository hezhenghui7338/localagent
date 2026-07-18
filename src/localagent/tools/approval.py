"""User approval gate for agent tools that mutate the local machine."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any, Literal

from localagent import config
from localagent.ui.console import prepare_for_input

ApprovalPolicy = Literal["always", "dangerous", "off"]
RiskLevel = Literal["safe", "dangerous", "blocked"]

APPROVAL_TOOLS = frozenset({"run_shell", "write_file", "edit_file"})

# Hard-blocked: never execute, never ask.
_BLOCKED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-\w*f\w*\s+)?(-\w*r\w*\s+)?/\s*$", re.I), "禁止删除根目录"),
    (re.compile(r"\brm\s+(-\w*f\w*\s+)?(-\w*r\w*\s+)?/\*", re.I), "禁止删除根目录"),
    (re.compile(r"\bmkfs\.", re.I), "禁止格式化磁盘"),
    (re.compile(r"\bdd\s+.*\bof=/dev/", re.I), "禁止直接写入块设备"),
    (re.compile(r">\s*/dev/sd[a-z]", re.I), "禁止覆写磁盘设备"),
    (re.compile(r":\(\)\s*\{.*:\|:.*\}.*;", re.I), "禁止 fork bomb"),
]

# Dangerous: execute only after explicit confirmation (with warning).
_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-[^\s]*\s+)*", re.I), "删除文件/目录"),
    (re.compile(r"\bsudo\b", re.I), "以管理员权限执行"),
    (re.compile(r"\bchmod\b", re.I), "修改文件权限"),
    (re.compile(r"\bchown\b", re.I), "修改文件所有者"),
    (re.compile(r"\b(mv|cp)\b", re.I), "移动/复制文件"),
    (re.compile(r"\b(unlink|shred|truncate)\b", re.I), "破坏性文件操作"),
    (re.compile(r"\bfind\b.*\s-delete\b", re.I), "find 批量删除"),
    (re.compile(r"\bgit\s+push\b.*--force", re.I), "强制推送"),
    (re.compile(r"\bgit\s+reset\b.*--hard", re.I), "硬重置"),
    (re.compile(r"\bgit\s+clean\b.*-[^\s]*f", re.I), "强制清理工作区"),
    (re.compile(r"\bkill\b|\bpkill\b|\bkillall\b", re.I), "终止进程"),
    (re.compile(r"\b(curl|wget)\b.*\|\s*(ba)?sh\b", re.I), "下载并执行脚本"),
    (re.compile(r"\beval\b", re.I), "动态执行代码"),
    (re.compile(r">\s*/", re.I), "重定向写入绝对路径"),
    (re.compile(r"\bdd\b", re.I), "底层磁盘读写"),
    (re.compile(r"\b(shutdown|reboot|halt|poweroff)\b", re.I), "关机/重启"),
    (re.compile(r"\b(pip|npm|brew)\s+uninstall\b", re.I), "卸载软件包"),
]


@dataclass(frozen=True)
class ToolRisk:
    level: RiskLevel
    reason: str | None = None
    summary: str = ""


@dataclass
class SessionApprovalGate:
    """Session-scoped approve-once for *safe* tool patterns only.

    Dangerous / blocked classifications are never remembered.
    """

    _allowed: set[str] = field(default_factory=set)

    @staticmethod
    def pattern_key(name: str, risk: ToolRisk) -> str:
        return f"{name}:{risk.level}"

    def is_preapproved(self, name: str, risk: ToolRisk) -> bool:
        if risk.level != "safe":
            return False
        return self.pattern_key(name, risk) in self._allowed

    def remember(self, name: str, risk: ToolRisk) -> None:
        if risk.level != "safe":
            return
        self._allowed.add(self.pattern_key(name, risk))


def normalize_approval_policy(raw: str | None) -> ApprovalPolicy:
    value = (raw or "always").strip().lower()
    if value in ("always", "all", "1", "true", "yes"):
        return "always"
    if value in ("dangerous", "danger", "warn"):
        return "dangerous"
    if value in ("off", "0", "false", "no", "never"):
        return "off"
    return "always"


def get_approval_policy() -> ApprovalPolicy:
    return normalize_approval_policy(getattr(config, "TOOL_APPROVAL", "always"))


def classify_shell_command(command: str) -> ToolRisk:
    cmd = command.strip()
    if not cmd:
        return ToolRisk(level="safe", summary="(空命令)")

    for pattern, reason in _BLOCKED_PATTERNS:
        if pattern.search(cmd):
            return ToolRisk(level="blocked", reason=reason, summary=cmd)

    for pattern, reason in _DANGEROUS_PATTERNS:
        if pattern.search(cmd):
            return ToolRisk(level="dangerous", reason=reason, summary=cmd)

    return ToolRisk(level="safe", summary=cmd)


def classify_tool(name: str, arguments: dict[str, Any]) -> ToolRisk:
    if name == "run_shell":
        return classify_shell_command(str(arguments.get("command") or ""))
    if name == "write_file":
        path = str(arguments.get("path") or "").strip() or "(未指定路径)"
        mode = str(arguments.get("mode") or "overwrite").strip().lower()
        content = str(arguments.get("content") or "")
        preview = content if len(content) <= 80 else f"{content[:80]}…"
        action = "追加" if mode == "append" else "覆盖写入"
        return ToolRisk(
            level="dangerous",
            reason=f"{action}本地文件",
            summary=f"{path} ({action}, {len(content)} 字符)\n预览: {preview}",
        )
    if name == "edit_file":
        path = str(arguments.get("path") or "").strip() or "(未指定路径)"
        old = str(arguments.get("old_string") or "")
        new = str(arguments.get("new_string") or "")
        replace_all = bool(arguments.get("replace_all"))
        old_preview = old if len(old) <= 60 else f"{old[:60]}…"
        new_preview = new if len(new) <= 60 else f"{new[:60]}…"
        scope = "全部替换" if replace_all else "单处替换"
        return ToolRisk(
            level="dangerous",
            reason="精确编辑本地文件",
            summary=(
                f"{path} ({scope})\n"
                f"- old: {old_preview}\n"
                f"- new: {new_preview}"
            ),
        )
    return ToolRisk(level="safe", summary=name)


def needs_approval(name: str, risk: ToolRisk, *, policy: ApprovalPolicy | None = None) -> bool:
    """Whether the tool call should pause for user confirmation."""
    if name not in APPROVAL_TOOLS:
        return False
    if risk.level == "blocked":
        return False  # hard-deny; do not ask
    effective = policy if policy is not None else get_approval_policy()
    if effective == "off":
        return False
    if effective == "always":
        return True
    # dangerous policy: write_file + dangerous/blocked-classified shell
    return risk.level == "dangerous"


def format_approval_prompt(name: str, arguments: dict[str, Any], risk: ToolRisk) -> str:
    if name == "run_shell":
        label = "执行命令"
    elif name == "edit_file":
        label = "编辑文件"
    else:
        label = "写入文件"
    lines = [f"⚠ Agent 请求{label}，需你确认后才会执行。"]
    if risk.level == "dangerous" and risk.reason:
        lines.append(f"风险: {risk.reason}")
    if name == "run_shell":
        cmd = str(arguments.get("command") or "").strip()
        lines.append(f"命令: {cmd}")
        cwd = arguments.get("cwd")
        if cwd:
            lines.append(f"目录: {cwd}")
    elif name in {"write_file", "edit_file"}:
        lines.append(f"目标: {risk.summary}")
    return "\n".join(lines)


def prompt_tool_approval(
    name: str,
    arguments: dict[str, Any],
    risk: ToolRisk,
    *,
    default: bool = False,
    session_gate: SessionApprovalGate | None = None,
) -> bool:
    """Ask on a TTY whether to allow the tool. Non-interactive → deny by default.

    For safe tools, ``a`` / ``always`` remembers the pattern for this session
    when ``session_gate`` is provided. Dangerous/blocked patterns are never
    session-remembered.
    """
    if session_gate is not None and session_gate.is_preapproved(name, risk):
        return True

    if not sys.stdin.isatty():
        return default

    prepare_for_input()
    print(format_approval_prompt(name, arguments, risk), flush=True)
    allow_session = risk.level == "safe" and session_gate is not None
    if risk.level == "dangerous":
        suffix = "[y/N]"
        default = False
        question = "⚠ 这是潜在危险操作，确定要执行吗？"
    elif allow_session:
        suffix = "[y/N/a]"
        question = "是否允许执行？（a = 本会话同类安全操作不再询问）"
    else:
        suffix = "[y/N]"
        question = "是否允许执行？"

    try:
        answer = input(f"{question} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default
    if answer in ("a", "always", "all", "会话") and allow_session and session_gate is not None:
        session_gate.remember(name, risk)
        return True
    if answer in ("y", "yes", "是"):
        return True
    if answer in ("n", "no", "否"):
        return False
    return default


def denied_message(*, blocked: bool = False, reason: str | None = None) -> str:
    if blocked:
        return f"错误: {reason or '该操作已被安全策略禁止'}。"
    return "用户拒绝执行该操作。"
