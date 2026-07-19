"""Git repo poll-diff sensor."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from localagent.aware.profile import SourceGrant
from localagent.aware.types import AwareEvent
from localagent.workspace.context import resolve_workspace


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10.0,
        check=False,
    )


class GitSensor:
    name = "git"

    def __init__(self, grant: SourceGrant) -> None:
        self.grant = grant

    def _repos(self) -> list[Path]:
        repos: list[Path] = []
        for raw in self.grant.repos:
            p = Path(raw).expanduser()
            if p.is_dir():
                repos.append(p.resolve())
        ws = resolve_workspace()
        if ws.is_dir() and ws not in repos:
            probe = _run_git(["rev-parse", "--is-inside-work-tree"], ws)
            if probe.returncode == 0:
                top = _run_git(["rev-parse", "--show-toplevel"], ws)
                if top.returncode == 0 and top.stdout.strip():
                    root = Path(top.stdout.strip()).resolve()
                    if root not in repos:
                        repos.append(root)
        return repos

    def describe_access(self) -> list[str]:
        repos = self._repos()
        if repos:
            return [str(r) for r in repos]
        return [f"工作区（若为 git 仓库）: {resolve_workspace()}"]

    def collect(self, cursor: dict[str, Any]) -> tuple[list[AwareEvent], dict[str, Any]]:
        events: list[AwareEvent] = []
        state: dict[str, Any] = dict(cursor.get("repos") or {})
        new_state: dict[str, Any] = {}

        for repo in self._repos():
            key = str(repo)
            head = _run_git(["rev-parse", "HEAD"], repo)
            branch = _run_git(["branch", "--show-current"], repo)
            status = _run_git(["status", "--porcelain"], repo)
            if head.returncode != 0:
                continue
            head_hash = head.stdout.strip()
            branch_name = branch.stdout.strip() or "HEAD"
            dirty = bool(status.stdout.strip()) if status.returncode == 0 else False
            fingerprint = f"{head_hash}|{branch_name}|{dirty}|{status.stdout.strip()[:200]}"
            prev = state.get(key) or {}
            new_state[key] = {
                "head": head_hash,
                "branch": branch_name,
                "dirty": dirty,
                "fp": fingerprint,
            }
            if not prev:
                # Seed baseline without flooding events on first grant.
                continue
            if prev.get("head") != head_hash:
                subj = _run_git(["log", "-1", "--format=%s"], repo)
                events.append(
                    AwareEvent(
                        source="git",
                        kind="git.commit",
                        title=(subj.stdout.strip() or head_hash[:12])[:120],
                        data={
                            "repo": key,
                            "head": head_hash[:12],
                            "branch": branch_name,
                            "prev_head": str(prev.get("head") or "")[:12],
                        },
                    )
                )
            if prev.get("branch") != branch_name:
                events.append(
                    AwareEvent(
                        source="git",
                        kind="git.branch",
                        title=f"{prev.get('branch')} → {branch_name}",
                        data={"repo": key, "branch": branch_name},
                    )
                )
            if bool(prev.get("dirty")) != dirty:
                events.append(
                    AwareEvent(
                        source="git",
                        kind="git.dirty",
                        title="工作区有未提交变更" if dirty else "工作区已干净",
                        data={"repo": key, "dirty": dirty, "branch": branch_name},
                    )
                )

        return events, {"repos": new_state}
