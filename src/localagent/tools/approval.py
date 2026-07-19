"""User approval gate for agent tools that mutate the local machine."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any, Literal

from localagent import config
from localagent.i18n import t
from localagent.ui.console import prepare_for_input

ApprovalPolicy = Literal["always", "dangerous", "off"]
RiskLevel = Literal["safe", "dangerous", "blocked"]

APPROVAL_TOOLS = frozenset({"run_shell", "write_file", "edit_file"})

# Hard-blocked: never execute, never ask. Values are i18n keys.
_BLOCKED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-\w*f\w*\s+)?(-\w*r\w*\s+)?/\s*$", re.I), "approval.deny_rm_root"),
    (re.compile(r"\brm\s+(-\w*f\w*\s+)?(-\w*r\w*\s+)?/\*", re.I), "approval.deny_rm_root"),
    (re.compile(r"\bmkfs\.", re.I), "approval.deny_mkfs"),
    (re.compile(r"\bdd\s+.*\bof=/dev/", re.I), "approval.deny_dd_dev"),
    (re.compile(r">\s*/dev/sd[a-z]", re.I), "approval.deny_overwrite_disk"),
    (re.compile(r":\(\)\s*\{.*:\|:.*\}.*;", re.I), "approval.deny_fork_bomb"),
]

# Dangerous: execute only after explicit confirmation (with warning).
_DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-[^\s]*\s+)*", re.I), "approval.risk_rm"),
    (re.compile(r"\bsudo\b", re.I), "approval.risk_sudo"),
    (re.compile(r"\bchmod\b", re.I), "approval.risk_chmod"),
    (re.compile(r"\bchown\b", re.I), "approval.risk_chown"),
    (re.compile(r"\b(mv|cp)\b", re.I), "approval.risk_mv_cp"),
    (re.compile(r"\b(unlink|shred|truncate)\b", re.I), "approval.risk_destructive"),
    (re.compile(r"\bfind\b.*\s-delete\b", re.I), "approval.risk_find_delete"),
    (re.compile(r"\bgit\s+push\b.*--force", re.I), "approval.risk_force_push"),
    (re.compile(r"\bgit\s+reset\b.*--hard", re.I), "approval.risk_hard_reset"),
    (re.compile(r"\bgit\s+clean\b.*-[^\s]*f", re.I), "approval.risk_git_clean"),
    (re.compile(r"\bkill\b|\bpkill\b|\bkillall\b", re.I), "approval.risk_kill"),
    (re.compile(r"\b(curl|wget)\b.*\|\s*(ba)?sh\b", re.I), "approval.risk_pipe_sh"),
    (re.compile(r"\beval\b", re.I), "approval.risk_eval"),
    (re.compile(r">\s*/", re.I), "approval.risk_redirect"),
    (re.compile(r"\bdd\b", re.I), "approval.risk_dd"),
    (re.compile(r"\b(shutdown|reboot|halt|poweroff)\b", re.I), "approval.risk_power"),
    (re.compile(r"\b(pip|npm|brew)\s+uninstall\b", re.I), "approval.risk_uninstall"),
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
        return ToolRisk(level="safe", summary=t("approval.empty_cmd"))

    for pattern, reason_key in _BLOCKED_PATTERNS:
        if pattern.search(cmd):
            return ToolRisk(level="blocked", reason=t(reason_key), summary=cmd)

    for pattern, reason_key in _DANGEROUS_PATTERNS:
        if pattern.search(cmd):
            return ToolRisk(level="dangerous", reason=t(reason_key), summary=cmd)

    return ToolRisk(level="safe", summary=cmd)


def classify_tool(name: str, arguments: dict[str, Any]) -> ToolRisk:
    if name == "run_shell":
        return classify_shell_command(str(arguments.get("command") or ""))
    if name == "write_file":
        path = str(arguments.get("path") or "").strip() or t("approval.path_unset")
        mode = str(arguments.get("mode") or "overwrite").strip().lower()
        content = str(arguments.get("content") or "")
        preview = content if len(content) <= 80 else f"{content[:80]}…"
        action = t("approval.write_append") if mode == "append" else t("approval.write_overwrite")
        return ToolRisk(
            level="dangerous",
            reason=t("approval.write_reason", action=action),
            summary=t(
                "approval.write_summary",
                path=path,
                action=action,
                n=len(content),
                preview=preview,
            ),
        )
    if name == "edit_file":
        path = str(arguments.get("path") or "").strip() or t("approval.path_unset")
        old = str(arguments.get("old_string") or "")
        new = str(arguments.get("new_string") or "")
        replace_all = bool(arguments.get("replace_all"))
        old_preview = old if len(old) <= 60 else f"{old[:60]}…"
        new_preview = new if len(new) <= 60 else f"{new[:60]}…"
        scope = t("approval.edit_all") if replace_all else t("approval.edit_one")
        return ToolRisk(
            level="dangerous",
            reason=t("approval.edit_reason"),
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
        label = t("approval.label_shell")
    elif name == "edit_file":
        label = t("approval.label_edit")
    else:
        label = t("approval.label_write")
    lines = [t("approval.request", label=label)]
    if risk.level == "dangerous" and risk.reason:
        lines.append(t("approval.risk_line", reason=risk.reason))
    if name == "run_shell":
        cmd = str(arguments.get("command") or "").strip()
        lines.append(t("approval.cmd_line", cmd=cmd))
        cwd = arguments.get("cwd")
        if cwd:
            lines.append(t("approval.cwd_line", cwd=cwd))
    elif name in {"write_file", "edit_file"}:
        lines.append(t("approval.target_line", summary=risk.summary))
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
        question = t("approval.q_dangerous")
    elif allow_session:
        suffix = "[y/N/a]"
        question = t("approval.q_session")
    else:
        suffix = "[y/N]"
        question = t("approval.q_default")

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
        return t(
            "approval.blocked",
            reason=reason or t("approval.blocked_default"),
        )
    return t("approval.denied")
