"""Read-only workspace introspection for git, file activity, and todos."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from localagent.i18n import t

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
        # Diagnostic scan: skip noise-heavy trees (managed tasks are the product queue).
        "tests",
        "test",
        "docs",
        "benchmarks",
        "data",
        ".cursor",
        "examples",
    }
)
_SKIP_PATH_PREFIXES = (
    "src/localagent/workspace/",
    "localagent/workspace/",
)
_SKIP_SUFFIXES = frozenset({".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".o"})
# Word-boundary markers + required separator + substantive description (min ~3 chars).
_TODO_LINE = re.compile(
    r"(?<![A-Za-z])(?:TODO|FIXME|HACK|XXX)(?![A-Za-z])\s*[:\-]\s*(\S.{2,})$",
    re.IGNORECASE,
)
_CHECKBOX = re.compile(r"^\s*-\s*\[\s\]\s+(\S.{2,})$")
_MIN_DIAG_TEXT = 3
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
            return t("workspace.git_error", error=self.error)
        if not self.is_repo:
            return t("workspace.git_not_repo")
        lines = [t("workspace.git_branch", branch=self.branch or "unknown")]
        if self.clean:
            lines.append(t("workspace.git_clean"))
        else:
            parts = []
            if self.staged_count:
                parts.append(t("workspace.git_staged", n=self.staged_count))
            if self.unstaged_count:
                parts.append(t("workspace.git_unstaged", n=self.unstaged_count))
            if self.untracked_count:
                parts.append(t("workspace.git_untracked", n=self.untracked_count))
            lines.append(t("workspace.git_dirty", parts=", ".join(parts)))
        if self.recent_commits:
            lines.append(t("workspace.git_recent"))
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
    rel = path.as_posix().lower()
    for prefix in _SKIP_PATH_PREFIXES:
        if rel.startswith(prefix):
            return True
    # Skip README / PRD noise that historically caused false positives.
    name = path.name.lower()
    if name.startswith("readme") or name in {"prd.md", "tdd.md", "changelog.md"}:
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
    """Diagnostic scan for TODO/FIXME / unchecked checkboxes (does NOT enqueue tasks)."""
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
            rel_path = path.relative_to(root)
            if _should_skip_path(rel_path):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = rel_path.as_posix()
            for line_no, line in enumerate(text.splitlines(), start=1):
                checkbox = _CHECKBOX.match(line)
                todo_match = None if checkbox else _TODO_LINE.search(line)
                match = checkbox or todo_match
                if not match:
                    continue
                desc = match.group(1).strip()
                if len(desc) < _MIN_DIAG_TEXT:
                    continue
                # Prefer readable description; keep a short line snippet as fallback context.
                snippet = line.strip()
                if len(snippet) > 160:
                    snippet = snippet[:157] + "..."
                todos.append(
                    {
                        "path": rel,
                        "line": str(line_no),
                        "kind": "checkbox" if checkbox else "todo",
                        "text": desc[:200],
                        "snippet": snippet,
                    }
                )
                if len(todos) >= limit:
                    return todos
    return todos


def format_diagnostic_todos(
    workspace: Path | None = None,
    *,
    limit: int = 80,
) -> str:
    """Format diagnostic scan results (not the managed task queue)."""
    root = workspace or resolve_workspace()
    todos = scan_todos(root, limit=limit)
    lines = [
        t("workspace.diag_header", root=root),
        t("workspace.diag_note"),
    ]
    if not todos:
        lines.append(t("workspace.diag_empty"))
        return "\n".join(lines)
    for item in todos:
        lines.append(
            f"  [{item['kind']}] {item['path']}:{item['line']}  {item['text']}"
        )
    lines.append(t("workspace.diag_hits", n=len(todos)))
    return "\n".join(lines)


def format_workspace_summary(
    *,
    days: int = 7,
    workspace: Path | None = None,
    include_diagnostic: bool = False,
) -> str:
    """Human-readable workspace overview for CLI and agent tools."""
    root = workspace or resolve_workspace()
    lines = [t("workspace.root", root=root), t("workspace.recent_files", days=days)]
    files = recent_files(root, days=days)
    if not files:
        lines.append(t("workspace.no_recent"))
    else:
        for item in files[:15]:
            lines.append(f"  - {item['modified']}  {item['path']}")
        if len(files) > 15:
            lines.append(t("workspace.files_more", n=len(files)))

    lines.append("")
    lines.append(git_summary(root).to_text())

    lines.append("")
    from localagent.workspace.tasks import format_tasks_for_summary

    lines.append(format_tasks_for_summary(root, limit=10))

    if include_diagnostic:
        diag = scan_todos(root, limit=20)
        lines.append("")
        if diag:
            lines.append(t("workspace.diag_summary_hits", n=len(diag)))
            for item in diag[:5]:
                lines.append(
                    f"  - [{item['kind']}] {item['path']}:{item['line']}  {item['text']}"
                )
        else:
            lines.append(t("workspace.diag_summary_empty"))

    return "\n".join(lines)


def workspace_context(*, days: int = 7, workspace: Path | None = None) -> str:
    """Alias used by agent tools."""
    return format_workspace_summary(days=days, workspace=workspace)

