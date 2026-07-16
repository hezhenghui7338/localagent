"""Workspace glob / grep helpers for the agent (pure Python, no ripgrep required)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from localagent.tools.files import resolve_workspace_path
from localagent.workspace.context import resolve_workspace

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".tox",
        "chroma",
        ".cursor",
    }
)
_DEFAULT_GLOB_CAP = 100
_DEFAULT_GREP_HEAD = 50
_MAX_GREP_LINE = 400
_DOTFILE_ALLOW = frozenset({".env.example", ".gitignore", ".editorconfig"})


def _resolve_root(path: str | None, *, workspace: Path) -> Path | str:
    if not path or not str(path).strip():
        return workspace
    resolved = resolve_workspace_path(str(path).strip(), workspace=workspace)
    if isinstance(resolved, str):
        return resolved
    if not resolved.exists():
        rel = resolved.relative_to(workspace).as_posix()
        return f"错误: 路径不存在: {rel}"
    return resolved


def _should_skip_dir(name: str) -> bool:
    return name in _SKIP_DIR_NAMES


def _collect_files(root: Path, *, workspace: Path) -> list[Path]:
    files: list[Path] = []
    if root.is_file():
        try:
            root.resolve().relative_to(workspace.resolve())
        except ValueError:
            return []
        return [root]

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        base = Path(dirpath)
        for name in filenames:
            if name.startswith(".") and name not in _DOTFILE_ALLOW:
                continue
            path = base / name
            if not path.is_file():
                continue
            try:
                path.resolve().relative_to(workspace.resolve())
            except ValueError:
                continue
            files.append(path)
    return files


def _path_matches_glob(file_path: Path, *, workspace: Path, glob_pat: str) -> bool:
    rel = file_path.relative_to(workspace).as_posix()
    candidates = (glob_pat, f"**/{glob_pat}" if not glob_pat.startswith("**/") else glob_pat)
    for candidate in candidates:
        try:
            if file_path.match(candidate) or Path(rel).match(candidate) or Path(file_path.name).match(candidate):
                return True
        except ValueError:
            continue
    return False


def glob_tool(
    pattern: str,
    *,
    path: str | None = None,
    cwd: str | None = None,
    max_results: int = _DEFAULT_GLOB_CAP,
) -> str:
    """Find files by glob pattern under the workspace (sorted by mtime, newest first)."""
    workspace = resolve_workspace(cwd)
    if not workspace.is_dir():
        return f"错误: 工作区目录不存在: {workspace}"

    raw = (pattern or "").strip()
    if not raw:
        return "错误: pattern 不能为空。"

    root = _resolve_root(path, workspace=workspace)
    if isinstance(root, str):
        return root

    glob_pat = raw
    if "**" not in glob_pat and "/" not in glob_pat and not glob_pat.startswith("*"):
        glob_pat = f"**/{glob_pat}"
    elif not any(ch in glob_pat for ch in "*?["):
        glob_pat = f"**/{glob_pat}"

    try:
        matches = [p for p in root.glob(glob_pat) if p.is_file()]
    except ValueError as exc:
        return f"错误: 无效的 glob 模式: {exc}"

    workspace_resolved = workspace.resolve()
    filtered: list[Path] = []
    for match in matches:
        try:
            match.resolve().relative_to(workspace_resolved)
        except ValueError:
            continue
        if any(part in _SKIP_DIR_NAMES for part in match.parts):
            continue
        filtered.append(match)

    def _mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    filtered.sort(key=_mtime, reverse=True)
    try:
        cap = max(1, int(max_results))
    except (TypeError, ValueError):
        cap = _DEFAULT_GLOB_CAP
    truncated = len(filtered) > cap
    shown = filtered[:cap]

    if not shown:
        scope = path.strip() if path and str(path).strip() else "."
        return f"未找到匹配文件: pattern={raw!r} path={scope}"

    lines = [item.resolve().relative_to(workspace_resolved).as_posix() for item in shown]
    out = "\n".join(lines)
    if truncated:
        out += f"\n…（已截断，共 {len(filtered)} 个匹配，仅显示前 {cap} 个；请缩小 pattern）"
    return out


def grep_tool(
    pattern: str,
    *,
    path: str | None = None,
    glob: str | None = None,
    output_mode: str = "content",
    head_limit: int = _DEFAULT_GREP_HEAD,
    case_insensitive: bool = False,
    cwd: str | None = None,
) -> str:
    """Search file contents with a regex (workspace-scoped)."""
    workspace = resolve_workspace(cwd)
    if not workspace.is_dir():
        return f"错误: 工作区目录不存在: {workspace}"

    raw = (pattern or "").strip()
    if not raw:
        return "错误: pattern 不能为空。"

    root = _resolve_root(path, workspace=workspace)
    if isinstance(root, str):
        return root

    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(raw, flags)
    except re.error as exc:
        return f"错误: 无效的正则表达式: {exc}"

    mode = (output_mode or "content").strip().lower()
    if mode not in {"content", "files_with_matches", "count"}:
        return "错误: output_mode 仅支持 content / files_with_matches / count。"

    files = _collect_files(root, workspace=workspace)
    if glob and str(glob).strip():
        g = str(glob).strip()
        files = [f for f in files if _path_matches_glob(f, workspace=workspace, glob_pat=g)]

    try:
        cap = max(1, int(head_limit))
    except (TypeError, ValueError):
        cap = _DEFAULT_GREP_HEAD

    content_lines: list[str] = []
    file_hits: list[str] = []
    counts: list[tuple[str, int]] = []
    total_matches = 0
    truncated = False

    for file_path in sorted(files, key=lambda p: p.as_posix()):
        try:
            text = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = file_path.relative_to(workspace).as_posix()
        file_match_count = 0
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not regex.search(line):
                continue
            file_match_count += 1
            total_matches += 1
            if mode == "content":
                if len(content_lines) >= cap:
                    truncated = True
                    break
                snippet = line if len(line) <= _MAX_GREP_LINE else f"{line[:_MAX_GREP_LINE]}…"
                content_lines.append(f"{rel}:{line_no}:{snippet}")
        if file_match_count:
            file_hits.append(rel)
            counts.append((rel, file_match_count))
        if mode == "content" and truncated:
            break
        if mode == "files_with_matches" and len(file_hits) >= cap:
            truncated = True
            break

    if mode == "content":
        if not content_lines:
            return f"未找到匹配: pattern={raw!r}"
        out = "\n".join(content_lines)
        if truncated:
            out += f"\n…（已截断，仅显示前 {cap} 行匹配；请缩小范围或提高 head_limit）"
        return out

    if mode == "files_with_matches":
        if not file_hits:
            return f"未找到匹配: pattern={raw!r}"
        shown = file_hits[:cap]
        out = "\n".join(shown)
        if len(file_hits) > cap or truncated:
            out += f"\n…（已截断，共 {len(file_hits)}+ 个文件）"
        return out

    if not counts:
        return f"未找到匹配: pattern={raw!r}"
    lines = [f"{rel}:{n}" for rel, n in counts[:cap]]
    lines.append(f"合计: {total_matches}")
    out = "\n".join(lines)
    if len(counts) > cap:
        out += f"\n…（已截断文件列表，仅显示前 {cap} 个文件）"
    return out
