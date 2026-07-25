"""write_file / edit_file read-back validation."""

from __future__ import annotations

import hashlib

from localagent import config
from localagent.agent.validation.types import ValidationContext, ValidationResult
from localagent.tools.files import resolve_workspace_path
from localagent.workspace.context import resolve_workspace


def _tool_error(raw: str) -> bool:
    text = (raw or "").strip()
    return text.startswith("错误:") or text.startswith("Error:")


def _readback_enabled() -> bool:
    return getattr(config, "VALIDATE_READBACK", True)


def _resolve_path(arguments: dict, *, cwd: str | None = None):
    path = str(arguments.get("path") or "").strip()
    if not path:
        return None, "missing path"
    workspace = resolve_workspace(cwd or arguments.get("cwd"))
    if not workspace.is_dir():
        return None, "workspace missing"
    resolved = resolve_workspace_path(path, workspace=workspace)
    if isinstance(resolved, str):
        return None, resolved
    return resolved, None


def validate_write_file(ctx: ValidationContext) -> ValidationResult:
    raw = ctx.raw or ""
    if _tool_error(raw):
        return ValidationResult.fail(
            "文件写入未成功（工具层错误）。",
            retry_hint="检查路径与权限后重试 write_file。",
            tool_error=True,
        )

    if not _readback_enabled():
        return ValidationResult.ok(readback_skipped=True)

    args = ctx.arguments or {}
    expected = str(args.get("content") or "")
    mode = str(args.get("mode") or "overwrite").strip().lower()
    resolved, err = _resolve_path(args, cwd=args.get("cwd"))
    if err or resolved is None:
        return ValidationResult.warn(
            f"无法 read-back 校验路径: {err}",
            readback_skipped=True,
        )

    if not resolved.is_file():
        return ValidationResult.fail(
            "写入后文件不存在。",
            retry_hint="确认路径正确后重试 write_file。",
            readback_failed=True,
        )

    try:
        actual = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        return ValidationResult.warn(
            f"写入成功但 read-back 读取失败: {exc}",
            readback_skipped=True,
        )

    if mode == "append":
        if expected and not actual.endswith(expected):
            return ValidationResult.fail(
                "追加写入后 read-back 内容与预期不符。",
                retry_hint="检查 append 内容与文件编码后重试。",
                readback_failed=True,
            )
    else:
        prefix_len = min(500, len(expected))
        if prefix_len == 0:
            if actual:
                return ValidationResult.fail(
                    "写入空内容但文件非空。",
                    retry_hint="确认写入意图后重试。",
                    readback_failed=True,
                )
        elif actual[:prefix_len] != expected[:prefix_len]:
            digest_expected = hashlib.sha256(expected.encode("utf-8")).hexdigest()[:12]
            digest_actual = hashlib.sha256(actual.encode("utf-8")).hexdigest()[:12]
            return ValidationResult.fail(
                "写入后 read-back 内容与预期不符。",
                retry_hint="检查 content 与 path 后重试 write_file。",
                readback_failed=True,
                expected_digest=digest_expected,
                actual_digest=digest_actual,
            )

    return ValidationResult.ok(readback_ok=True)


def validate_edit_file(ctx: ValidationContext) -> ValidationResult:
    raw = ctx.raw or ""
    if _tool_error(raw):
        return ValidationResult.fail(
            "文件编辑未成功（工具层错误）。",
            retry_hint="检查 old_string 是否与文件完全一致（含空白）后重试 edit_file。",
            tool_error=True,
        )

    if not _readback_enabled():
        return ValidationResult.ok(readback_skipped=True)

    args = ctx.arguments or {}
    old_string = str(args.get("old_string") or "")
    new_string = str(args.get("new_string") or "")
    replace_all = bool(args.get("replace_all"))
    resolved, err = _resolve_path(args, cwd=args.get("cwd"))
    if err or resolved is None:
        return ValidationResult.warn(
            f"无法 read-back 校验路径: {err}",
            readback_skipped=True,
        )

    if not resolved.is_file():
        return ValidationResult.fail(
            "编辑后文件不存在。",
            retry_hint="确认 path 正确后重试 edit_file。",
            readback_failed=True,
        )

    try:
        actual = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        return ValidationResult.warn(
            f"编辑成功但 read-back 读取失败: {exc}",
            readback_skipped=True,
        )

    if old_string and old_string in actual and not replace_all:
        return ValidationResult.fail(
            "编辑后 old_string 仍存在于文件中。",
            retry_hint="扩大 old_string 上下文或检查缩进/换行后重试 edit_file。",
            readback_failed=True,
        )

    if new_string and new_string not in actual:
        return ValidationResult.fail(
            "编辑后 new_string 未出现在文件中。",
            retry_hint="确认 new_string 与替换逻辑后重试 edit_file。",
            readback_failed=True,
        )

    return ValidationResult.ok(readback_ok=True)
