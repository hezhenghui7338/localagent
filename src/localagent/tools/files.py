"""Workspace file write helpers for the agent."""

from __future__ import annotations

from pathlib import Path

from localagent.workspace.context import resolve_workspace


def _resolve_workspace_path(path: str, *, workspace: Path) -> Path | str:
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

    resolved = _resolve_workspace_path(path, workspace=workspace)
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
