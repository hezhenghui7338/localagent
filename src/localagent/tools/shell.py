"""Run shell commands in the workspace for the agent."""

from __future__ import annotations

import subprocess

from localagent import config
from localagent.i18n import resolve_lang
from localagent.tools.approval import classify_shell_command, denied_message
from localagent.workspace.context import resolve_workspace

_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_OUTPUT = 12_000


def _shell_timeout() -> float:
    return config.SHELL_TIMEOUT


def _shell_max_output() -> int:
    return config.SHELL_MAX_OUTPUT


def _check_blocked(command: str) -> str | None:
    risk = classify_shell_command(command)
    if risk.level == "blocked":
        return risk.reason
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
        return (
            "Error: command must not be empty."
            if resolve_lang() == "en"
            else "错误: 命令不能为空。"
        )

    blocked = _check_blocked(cmd)
    if blocked:
        return denied_message(blocked=True, reason=blocked)

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
