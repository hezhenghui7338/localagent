"""read_file / grep / glob result validators."""

from __future__ import annotations

import re

from localagent.agent.validation.types import ValidationContext, ValidationResult

_ERROR_PREFIXES = ("错误:", "Error:")


def _is_tool_error(raw: str) -> bool:
    text = (raw or "").strip()
    return any(text.startswith(prefix) for prefix in _ERROR_PREFIXES)


def validate_read_file(ctx: ValidationContext) -> ValidationResult:
    raw = ctx.raw or ""
    if _is_tool_error(raw):
        return ValidationResult.fail(
            "文件读取失败。",
            retry_hint="确认 path 正确后重试 read_file，或先用 glob 定位文件。",
            tool_error=True,
        )

    if re.search(r"共\s*0\s*行", raw):
        return ValidationResult.warn(
            "文件为空。",
            retry_hint="若不应为空，请检查 path 或改用其他文件。",
            empty_file=True,
        )

    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if len(lines) <= 1:
        return ValidationResult.warn(
            "read_file 结果几乎没有内容。",
            retry_hint="确认 offset/limit 或 path 是否正确。",
            empty_content=True,
        )

    return ValidationResult.ok()


def validate_grep(ctx: ValidationContext) -> ValidationResult:
    raw = ctx.raw or ""
    if _is_tool_error(raw):
        return ValidationResult.fail(
            "grep 执行失败。",
            retry_hint="检查 pattern/path 语法后重试 grep。",
            tool_error=True,
        )
    if raw.strip().startswith("未找到匹配"):
        return ValidationResult.warn(
            "grep 无匹配结果。",
            retry_hint="放宽 pattern、扩大 path 范围，或改用 glob 定位文件。",
            no_matches=True,
        )
    return ValidationResult.ok()


def validate_glob(ctx: ValidationContext) -> ValidationResult:
    raw = ctx.raw or ""
    if _is_tool_error(raw):
        return ValidationResult.fail(
            "glob 执行失败。",
            retry_hint="检查 pattern/path 后重试 glob。",
            tool_error=True,
        )
    if raw.strip().startswith("未找到匹配文件"):
        return ValidationResult.warn(
            "glob 无匹配文件。",
            retry_hint="放宽 pattern 或扩大搜索目录后重试 glob。",
            no_matches=True,
        )
    return ValidationResult.ok()
