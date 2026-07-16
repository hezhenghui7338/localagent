"""Workspace file read / write / edit helpers for the agent."""

from __future__ import annotations

from pathlib import Path

from localagent.workspace.context import resolve_workspace

_DEFAULT_READ_LIMIT = 400
_MAX_READ_CHARS = 80_000


def resolve_workspace_path(path: str, *, workspace: Path) -> Path | str:
    """Resolve ``path`` under ``workspace``; return an error string on failure."""
    raw = path.strip()
    if not raw:
        return "错误: 文件路径不能为空。"

    candidate = Path(raw)
    target = candidate.resolve() if candidate.is_absolute() else (workspace / candidate).resolve()

    try:
        target.relative_to(workspace)
    except ValueError:
        return f"错误: 路径必须位于工作区内: {workspace}"
    return target


# Back-compat alias used by older call sites / tests.
_resolve_workspace_path = resolve_workspace_path


def read_file_tool(
    path: str,
    *,
    offset: int | None = None,
    limit: int | None = None,
    cwd: str | None = None,
) -> str:
    """Read a text file inside the workspace (1-based line offset, optional limit)."""
    workspace = resolve_workspace(cwd)
    if not workspace.is_dir():
        return f"错误: 工作区目录不存在: {workspace}"

    resolved = resolve_workspace_path(path, workspace=workspace)
    if isinstance(resolved, str):
        return resolved
    if not resolved.exists():
        rel = resolved.relative_to(workspace).as_posix()
        return f"错误: 文件不存在: {rel}"
    if not resolved.is_file():
        rel = resolved.relative_to(workspace).as_posix()
        return f"错误: 不是普通文件: {rel}"

    try:
        text = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        rel = resolved.relative_to(workspace).as_posix()
        return f"错误: 无法以 UTF-8 读取（可能是二进制文件）: {rel}"
    except OSError as exc:
        return f"错误: 无法读取文件 {resolved}: {exc}"

    lines = text.splitlines(keepends=True)
    total = len(lines)
    start = 1
    if offset is not None:
        try:
            start = int(offset)
        except (TypeError, ValueError):
            return "错误: offset 必须是整数（从 1 开始的行号）。"
        if start < 1:
            return "错误: offset 必须 ≥ 1。"
    end = total
    if limit is not None:
        try:
            lim = int(limit)
        except (TypeError, ValueError):
            return "错误: limit 必须是整数。"
        if lim < 1:
            return "错误: limit 必须 ≥ 1。"
        end = min(total, start - 1 + lim)
    elif offset is None:
        # Default: first N lines for large files
        end = min(total, _DEFAULT_READ_LIMIT)
    else:
        end = min(total, start - 1 + _DEFAULT_READ_LIMIT)

    if start > total and total > 0:
        rel = resolved.relative_to(workspace).as_posix()
        return f"错误: offset {start} 超出文件行数 {total}: {rel}"

    selected = lines[start - 1 : end]
    body_parts: list[str] = []
    chars = 0
    truncated_by_chars = False
    for i, line in enumerate(selected, start=start):
        numbered = f"{i:>6}|{line.rstrip(chr(10) + chr(13))}"
        # +1 for joining newline below
        if chars + len(numbered) + 1 > _MAX_READ_CHARS and body_parts:
            truncated_by_chars = True
            break
        body_parts.append(numbered)
        chars += len(numbered) + 1

    rel = resolved.relative_to(workspace).as_posix()
    header = f"文件: {rel}（共 {total} 行"
    shown_end = start - 1 + len(body_parts) if body_parts else start - 1
    if start > 1 or shown_end < total or truncated_by_chars:
        header += f"，显示 {start}-{shown_end}"
    header += "）"
    body = "\n".join(body_parts)
    out = f"{header}\n{body}" if body else f"{header}\n"
    if truncated_by_chars or shown_end < total:
        out += f"\n…（已截断，可用 offset/limit 继续读取；下一行从 {shown_end + 1} 起）"
    return out


def edit_file_tool(
    path: str,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
    cwd: str | None = None,
) -> str:
    """Exact string replace inside a workspace file (unique match unless replace_all)."""
    workspace = resolve_workspace(cwd)
    if not workspace.is_dir():
        return f"错误: 工作区目录不存在: {workspace}"

    resolved = resolve_workspace_path(path, workspace=workspace)
    if isinstance(resolved, str):
        return resolved
    if not resolved.exists():
        rel = resolved.relative_to(workspace).as_posix()
        return f"错误: 文件不存在: {rel}（新建请用 write_file）"
    if not resolved.is_file():
        rel = resolved.relative_to(workspace).as_posix()
        return f"错误: 不是普通文件: {rel}"
    if old_string == "":
        return "错误: old_string 不能为空。"
    if old_string == new_string:
        return "错误: old_string 与 new_string 相同，无需修改。"

    try:
        text = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        rel = resolved.relative_to(workspace).as_posix()
        return f"错误: 无法以 UTF-8 读取（可能是二进制文件）: {rel}"
    except OSError as exc:
        return f"错误: 无法读取文件 {resolved}: {exc}"

    count = text.count(old_string)
    if count == 0:
        return "错误: old_string 在文件中未找到（须与文件内容完全一致，含空白与缩进）。"
    if count > 1 and not replace_all:
        return (
            f"错误: old_string 在文件中出现 {count} 次；"
            "请提供更长上下文使匹配唯一，或设 replace_all=true。"
        )

    if replace_all:
        updated = text.replace(old_string, new_string)
        n = count
    else:
        updated = text.replace(old_string, new_string, 1)
        n = 1

    try:
        resolved.write_text(updated, encoding="utf-8")
    except OSError as exc:
        return f"错误: 无法写入文件 {resolved}: {exc}"

    rel = resolved.relative_to(workspace).as_posix()
    preview_old = old_string if len(old_string) <= 80 else f"{old_string[:80]}…"
    preview_new = new_string if len(new_string) <= 80 else f"{new_string[:80]}…"
    return (
        f"已编辑文件: {rel}（替换 {n} 处）\n"
        f"- old: {preview_old}\n"
        f"- new: {preview_new}"
    )


def write_file_tool(
    path: str,
    content: str,
    *,
    mode: str = "overwrite",
    cwd: str | None = None,
) -> str:
    """Create or update a file inside the workspace."""
    workspace = resolve_workspace(cwd)
    if not workspace.is_dir():
        return f"错误: 工作区目录不存在: {workspace}"

    resolved = resolve_workspace_path(path, workspace=workspace)
    if isinstance(resolved, str):
        return resolved

    write_mode = (mode or "overwrite").strip().lower()
    if write_mode not in {"overwrite", "append"}:
        return "错误: mode 仅支持 overwrite 或 append。"

    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        if write_mode == "append":
            with resolved.open("a", encoding="utf-8") as handle:
                handle.write(content)
        else:
            resolved.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"错误: 无法写入文件 {resolved}: {exc}"

    rel = resolved.relative_to(workspace).as_posix()
    action = "追加" if write_mode == "append" else "写入"
    preview = content if len(content) <= 200 else f"{content[:200]}…"
    return f"已{action}文件: {rel}\n内容预览:\n{preview}"
