"""Run shell commands in the workspace for the agent."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from localagent import config
from localagent.workspace.context import resolve_workspace

_BLOCKED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brm\s+(-\w*f\w*\s+)?(-\w*r\w*\s+)?/\s*$", re.I), "禁止删除根目录"),
    (re.compile(r"\brm\s+(-\w*f\w*\s+)?(-\w*r\w*\s+)?/\*", re.I), "禁止删除根目录"),
    (re.compile(r"\bmkfs\.", re.I), "禁止格式化磁盘"),
    (re.compile(r"\bdd\s+.*\bof=/dev/", re.I), "禁止直接写入块设备"),
    (re.compile(r">\s*/dev/sd[a-z]", re.I), "禁止覆写磁盘设备"),
    (re.compile(r":\(\)\s*\{.*:\|:.*\}.*;", re.I), "禁止 fork bomb"),
]

_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_OUTPUT = 12_000


def _shell_timeout() -> float:
    return config.SHELL_TIMEOUT


def _shell_max_output() -> int:
    return config.SHELL_MAX_OUTPUT


def _check_blocked(command: str) -> str | None:
    for pattern, reason in _BLOCKED_PATTERNS:
        if pattern.search(command):
            return reason
    return None


def _truncate(text: str, *, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    half = limit // 2
    return (
        text[:half]
        + f"\n…（输出已截断，共 {len(text)} 字符，仅显示前后各 {half} 字符）…\n"
        + text[-half:],
        True,
    )


def run_shell_command(
    command: str,
    *,
    cwd: str | None = None,
    timeout: float | None = None,
    max_output: int | None = None,
) -> str:
    """Execute a shell command in the workspace and return combined output."""
    cmd = command.strip()
    if not cmd:
        return "错误: 命令不能为空。"

    blocked = _check_blocked(cmd)
    if blocked:
        return f"错误: {blocked}。"

    workspace = resolve_workspace(cwd)
    if not workspace.is_dir():
        return f"错误: 工作区目录不存在: {workspace}"

    effective_timeout = timeout if timeout is not None else _shell_timeout()
    output_limit = max_output if max_output is not None else _shell_max_output()

    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"错误: 命令超时（>{effective_timeout:.0f}s）: {cmd}"
    except OSError as exc:
        return f"错误: 无法执行命令: {exc}"

    parts: list[str] = [f"$ {cmd}", f"cwd: {workspace}"]
    if proc.returncode != 0:
        parts.append(f"exit: {proc.returncode}")

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    if stdout:
        body, truncated = _truncate(stdout.rstrip("\n"), limit=output_limit)
        parts.append(f"stdout:\n{body}")
        if truncated:
            parts[-1] += "\n（stdout 已截断）"
    if stderr:
        body, truncated = _truncate(stderr.rstrip("\n"), limit=output_limit)
        parts.append(f"stderr:\n{body}")
        if truncated:
            parts[-1] += "\n（stderr 已截断）"
    if not stdout and not stderr:
        parts.append("（无输出）")

    return "\n".join(parts)


def run_shell_tool(
    command: str,
    *,
    cwd: str | None = None,
    timeout: float | None = None,
) -> str:
    """Agent tool entry point."""
    return run_shell_command(command, cwd=cwd, timeout=timeout)
