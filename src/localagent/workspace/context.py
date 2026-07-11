"""Read-only workspace introspection for git, file activity, and todos."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from localagent import config

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
    }
)
_SKIP_SUFFIXES = frozenset({".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".o"})
_TODO_LINE = re.compile(
    r"(?:^|\s)(?:TODO|FIXME|HACK|XXX)\s*[:\-]?\s*(.+)$",
    re.IGNORECASE,
)
_CHECKBOX = re.compile(r"^\s*-\s*\[\s\]\s+(.+)$")
_SCAN_EXTENSIONS = frozenset(
    {
        ".py",
        ".md",
        ".markdown",
        ".txt",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".sh",
    }
)


@dataclass
class GitSummary:
    is_repo: bool = False
    branch: str = ""
    clean: bool = True
    staged_count: int = 0
    unstaged_count: int = 0
    untracked_count: int = 0
    recent_commits: list[dict[str, str]] = field(default_factory=list)
    error: str = ""

    def to_text(self) -> str:
        if self.error:
            return f"Git: {self.error}"
        if not self.is_repo:
            return "Git: 当前目录不是 git 仓库"
        lines = [f"Git 分支: {self.branch or 'unknown'}"]
        if self.clean:
            lines.append("工作区: 干净（无未提交变更）")
        else:
            parts = []
            if self.staged_count:
                parts.append(f"已暂存 {self.staged_count}")
            if self.unstaged_count:
                parts.append(f"未暂存 {self.unstaged_count}")
            if self.untracked_count:
                parts.append(f"未跟踪 {self.untracked_count}")
            lines.append(f"工作区: {', '.join(parts)}")
        if self.recent_commits:
            lines.append("最近提交:")
            for commit in self.recent_commits[:5]:
                lines.append(f"  - {commit['hash']} {commit['date']} {commit['subject']}")
        return "\n".join(lines)


def resolve_workspace(cwd: str | Path | None = None) -> Path:
    """Resolve workspace root from explicit path, LA_WORKSPACE, or cwd."""
    if cwd is not None:
        return Path(cwd).expanduser().resolve()
    env = os.getenv("LA_WORKSPACE", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def _run_git(args: list[str], workspace: Path, *, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def git_summary(workspace: Path | None = None) -> GitSummary:
    """Read-only git status and recent commits."""
    root = workspace or resolve_workspace()
    summary = GitSummary()
    probe = _run_git(["rev-parse", "--is-inside-work-tree"], root)
    if probe.returncode != 0:
        summary.is_repo = False
        return summary

    summary.is_repo = True
    branch = _run_git(["branch", "--show-current"], root)
    summary.branch = branch.stdout.strip() or "HEAD"

    status = _run_git(["status", "--porcelain"], root)
    if status.returncode != 0:
        summary.error = status.stderr.strip() or "git status failed"
        return summary

    for line in status.stdout.splitlines():
        if len(line) < 3:
            continue
        index, worktree = line[0], line[1]
        if index == "?" and worktree == "?":
            summary.untracked_count += 1
            summary.clean = False
        elif index != " ":
            summary.staged_count += 1
            summary.clean = False
        elif worktree != " ":
            summary.unstaged_count += 1
            summary.clean = False

    log = _run_git(
        ["log", "--oneline", "--format=%h|%cs|%s", "-n", "8"],
        root,
    )
    if log.returncode == 0:
        for line in log.stdout.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                summary.recent_commits.append(
                    {"hash": parts[0], "date": parts[1], "subject": parts[2]}
                )
    return summary


def _should_skip_path(path: Path) -> bool:
    for part in path.parts:
        if part in _SKIP_DIR_NAMES:
            return True
    if path.suffix.lower() in _SKIP_SUFFIXES:
        return True
    return False


def recent_files(
    workspace: Path | None = None,
    *,
    days: int = 7,
    limit: int = 40,
) -> list[dict[str, Any]]:
    """List recently modified files under workspace."""
    root = workspace or resolve_workspace()
    if not root.is_dir():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    found: list[tuple[float, Path]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        base = Path(dirpath)
        if _should_skip_path(base.relative_to(root)) if base != root else False:
            continue
        for name in filenames:
            path = base / name
            if _should_skip_path(path.relative_to(root)):
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            modified = datetime.fromtimestamp(mtime, tz=timezone.utc)
            if modified >= cutoff:
                found.append((mtime, path))

    found.sort(key=lambda item: item[0], reverse=True)
    results: list[dict[str, Any]] = []
    for mtime, path in found[:limit]:
        rel = path.relative_to(root).as_posix()
        modified = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
        results.append({"path": rel, "modified": modified})
    return results


def scan_todos(
    workspace: Path | None = None,
    *,
    limit: int = 80,
) -> list[dict[str, str]]:
    """Scan workspace for TODO/FIXME comments and markdown checkboxes."""
    root = workspace or resolve_workspace()
    if not root.is_dir():
        return []

    todos: list[dict[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() not in _SCAN_EXTENSIONS:
                continue
            if _should_skip_path(path.relative_to(root)):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            for line_no, line in enumerate(text.splitlines(), start=1):
                match = _TODO_LINE.search(line) or _CHECKBOX.match(line)
                if not match:
                    continue
                todos.append(
                    {
                        "path": rel,
                        "line": str(line_no),
                        "kind": "checkbox" if _CHECKBOX.match(line) else "todo",
                        "text": match.group(1).strip()[:200],
                    }
                )
                if len(todos) >= limit:
                    return todos
    return todos


def format_workspace_summary(*, days: int = 7, workspace: Path | None = None) -> str:
    """Human-readable workspace overview for CLI and agent tools."""
    root = workspace or resolve_workspace()
    lines = [f"工作区: {root}", f"最近 {days} 天修改的文件:"]
    files = recent_files(root, days=days)
    if not files:
        lines.append("  （无近期变更，或目录不可访问）")
    else:
        for item in files[:15]:
            lines.append(f"  - {item['modified']}  {item['path']}")
        if len(files) > 15:
            lines.append(f"  … 共 {len(files)} 个文件")

    lines.append("")
    lines.append(git_summary(root).to_text())

    todos = scan_todos(root, limit=20)
    lines.append("")
    if todos:
        lines.append(f"待办项 ({len(todos)} 条，显示前 10):")
        for item in todos[:10]:
            lines.append(f"  - [{item['kind']}] {item['path']}:{item['line']}  {item['text']}")
        if len(todos) > 10:
            lines.append(f"  … 共 {len(todos)} 条")
    else:
        lines.append("待办项: 未扫描到 TODO/FIXME 或未勾选的 checkbox")

    return "\n".join(lines)


def workspace_context(*, days: int = 7, workspace: Path | None = None) -> str:
    """Alias used by agent tools."""
    return format_workspace_summary(days=days, workspace=workspace)

