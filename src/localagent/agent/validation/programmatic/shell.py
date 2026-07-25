"""run_shell result validation."""

from __future__ import annotations

import re

from localagent.agent.validation.types import ValidationContext, ValidationResult

_EXIT_RE = re.compile(r"^exit:\s*(-?\d+)\s*$", re.MULTILINE)
_STDOUT_RE = re.compile(r"^stdout:\n", re.MULTILINE)
_STDERR_RE = re.compile(r"^stderr:\n", re.MULTILINE)

_TEST_FAIL_PATTERNS = (
    re.compile(r"=+\s*FAILURES\s*=+", re.IGNORECASE),
    re.compile(r"=+\s*\d+\s+failed", re.IGNORECASE),
    re.compile(r"\bFAILED\b.*\[", re.IGNORECASE),
    re.compile(r"Tests?\s+\d+\s+failed", re.IGNORECASE),
    re.compile(r"npm ERR!", re.IGNORECASE),
    re.compile(r"Test Suites:\s+\d+\s+failed", re.IGNORECASE),
    re.compile(r"error:\s*test\s+failed", re.IGNORECASE),
    re.compile(r"failures:\s*\d+", re.IGNORECASE),
)


def _tool_error(raw: str) -> bool:
    text = (raw or "").strip()
    return text.startswith("错误:") or text.startswith("Error:")


def _parse_exit_code(raw: str) -> int | None:
    match = _EXIT_RE.search(raw or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _has_test_failure(raw: str) -> bool:
    return any(p.search(raw or "") for p in _TEST_FAIL_PATTERNS)


def _stderr_only_output(raw: str) -> bool:
    text = raw or ""
    has_stdout = bool(_STDOUT_RE.search(text))
    has_stderr = bool(_STDERR_RE.search(text))
    return has_stderr and not has_stdout


def validate_shell(ctx: ValidationContext) -> ValidationResult:
    raw = ctx.raw or ""

    if _tool_error(raw):
        return ValidationResult.fail(
            "命令未成功执行（工具层错误）。",
            retry_hint="检查命令语法、路径与权限后重试。",
            tool_error=True,
        )

    exit_code = _parse_exit_code(raw)
    if exit_code is not None and exit_code != 0:
        return ValidationResult.fail(
            f"命令退出码非零 (exit: {exit_code})。",
            retry_hint="检查命令输出中的错误信息，修正命令或参数后重试。",
            exit_code=exit_code,
        )

    if _has_test_failure(raw):
        return ValidationResult.fail(
            "测试输出显示失败。",
            retry_hint="查看失败详情，修复代码或测试后再运行。",
            test_failed=True,
            exit_code=exit_code,
        )

    if _stderr_only_output(raw):
        return ValidationResult.warn(
            "命令仅有 stderr 输出，请核对是否为预期警告。",
            retry_hint="确认 stderr 内容后再继续。",
            exit_code=exit_code or 0,
        )

    return ValidationResult.ok(exit_code=exit_code if exit_code is not None else 0)
