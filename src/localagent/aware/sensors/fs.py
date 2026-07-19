"""Filesystem poll-diff sensor with hard scan budgets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from localagent import config
from localagent.aware.platform_paths import default_fs_watch_paths
from localagent.aware.profile import SourceGrant
from localagent.aware.types import AwareEvent

_SKIP_NAMES = frozenset({".DS_Store", "Thumbs.db", ".git", "__pycache__", "node_modules"})
_MAX_FILES_PER_TICK = 80
_MAX_FILE_BYTES = 200 * 1024 * 1024
_NOISE_SUFFIXES = set(getattr(config, "AWARE_NOISE_SUFFIXES", set()))


def _budget_int(name: str, default: int) -> int:
    return int(getattr(config, name, default) or default)


def walk_watch_files(
    roots: list[Path],
    *,
    max_depth: int | None = None,
    max_scan: int | None = None,
    skip_names: frozenset[str] = _SKIP_NAMES,
    noise_suffixes: set[str] | None = None,
    max_file_bytes: int | None = _MAX_FILE_BYTES,
) -> tuple[list[tuple[Path, os.stat_result]], int, bool]:
    """Walk roots with depth/scan caps. Never follows symlinks.

    Returns (hits, scanned_files, truncated).
    """
    depth_cap = max_depth if max_depth is not None else _budget_int("AWARE_FS_MAX_DEPTH", 8)
    scan_cap = max_scan if max_scan is not None else _budget_int("AWARE_FS_MAX_SCAN_FILES", 5000)
    noise = noise_suffixes if noise_suffixes is not None else _NOISE_SUFFIXES
    hits: list[tuple[Path, os.stat_result]] = []
    scanned = 0
    truncated = False

    for root in roots:
        if truncated:
            break
        if not root.is_dir():
            continue
        root = root.expanduser()
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            if truncated:
                break
            rel = Path(dirpath).relative_to(root) if Path(dirpath) != root else Path()
            depth = 0 if rel == Path() else len(rel.parts)
            # Prune directories that would exceed depth or are skip names / symlinks.
            keep: list[str] = []
            for name in dirnames:
                if name in skip_names:
                    continue
                child = Path(dirpath) / name
                try:
                    if child.is_symlink():
                        continue
                except OSError:
                    continue
                if depth + 1 > depth_cap:
                    continue
                keep.append(name)
            dirnames[:] = keep

            if depth > depth_cap:
                dirnames[:] = []
                continue

            for name in filenames:
                if name in skip_names:
                    continue
                path = Path(dirpath) / name
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                except OSError:
                    continue
                # Count every regular file examined (including noise) toward the budget.
                scanned += 1
                if scanned > scan_cap:
                    truncated = True
                    break
                suffix = path.suffix.lower()
                if suffix in noise:
                    continue
                try:
                    st = path.stat()
                except OSError:
                    continue
                if max_file_bytes is not None and st.st_size > max_file_bytes:
                    continue
                hits.append((path, st))

    return hits, scanned, truncated


class FsSensor:
    name = "fs"

    def __init__(self, grant: SourceGrant) -> None:
        self.grant = grant

    def _roots(self) -> list[Path]:
        if self.grant.paths:
            roots = [Path(p).expanduser() for p in self.grant.paths]
        else:
            roots = default_fs_watch_paths()
        return [r for r in roots if r.is_dir()]

    def describe_access(self) -> list[str]:
        return [str(p) for p in self._roots()] or [str(p) for p in default_fs_watch_paths()]

    def collect(self, cursor: dict[str, Any]) -> tuple[list[AwareEvent], dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = dict(cursor.get("files") or {})
        primed = bool(cursor.get("primed"))
        events: list[AwareEvent] = []
        new_seen: dict[str, dict[str, Any]] = {}

        hits, _scanned, truncated = walk_watch_files(self._roots())

        for path, st in hits:
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            meta = {
                "mtime": st.st_mtime,
                "size": st.st_size,
                "ino": getattr(st, "st_ino", 0),
            }
            new_seen[key] = meta
            if not primed:
                continue
            if len(events) >= _MAX_FILES_PER_TICK:
                continue
            prev = seen.get(key)
            if prev is None:
                events.append(
                    AwareEvent(
                        source="fs",
                        kind="file.created",
                        title=path.name,
                        data={
                            "path": key,
                            "suffix": path.suffix.lower(),
                            "size": st.st_size,
                            "size_delta": st.st_size,
                            "chars_approx": _chars_approx(path, st.st_size),
                        },
                    )
                )
            elif (
                float(prev.get("mtime") or 0) != meta["mtime"]
                or int(prev.get("size") or 0) != meta["size"]
            ):
                prev_size = int(prev.get("size") or 0)
                delta = st.st_size - prev_size
                events.append(
                    AwareEvent(
                        source="fs",
                        kind="file.modified",
                        title=path.name,
                        data={
                            "path": key,
                            "suffix": path.suffix.lower(),
                            "size": st.st_size,
                            "prev_size": prev_size,
                            "size_delta": delta,
                            "chars_approx": _chars_approx(path, abs(delta)),
                        },
                    )
                )

        if len(new_seen) > 5000:
            items = sorted(
                new_seen.items(),
                key=lambda kv: float(kv[1].get("mtime") or 0),
                reverse=True,
            )
            new_seen = dict(items[:4000])

        return events, {"files": new_seen, "primed": True, "truncated": truncated}


_TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".rs",
        ".go",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".css",
        ".html",
        ".htm",
        ".csv",
        ".rtf",
    }
)


def _chars_approx(path: Path, size_hint: int) -> int | None:
    """Approximate edited text volume; None for binary / non-text suffixes."""
    if path.suffix.lower() not in _TEXT_SUFFIXES:
        return None
    return max(0, int(size_hint))
