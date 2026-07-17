"""Cross-platform clipboard helpers (no extra dependencies)."""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Callable


def _run_copy(cmd: list[str], text: str) -> bool:
    try:
        completed = subprocess.run(
            cmd,
            input=text.encode("utf-8"),
            check=False,
            capture_output=True,
            timeout=5,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _mac_copy(text: str) -> bool:
    return _run_copy(["pbcopy"], text)


def _windows_copy(text: str) -> bool:
    # ``clip`` expects the console code page; UTF-16LE is more reliable for Unicode.
    try:
        completed = subprocess.run(
            ["clip"],
            input=text.encode("utf-16le"),
            check=False,
            capture_output=True,
            timeout=5,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _linux_copy(text: str) -> bool:
    if shutil.which("wl-copy"):
        return _run_copy(["wl-copy"], text)
    if shutil.which("xclip"):
        return _run_copy(["xclip", "-selection", "clipboard"], text)
    if shutil.which("xsel"):
        return _run_copy(["xsel", "--clipboard", "--input"], text)
    return False


def copy_text(text: str) -> bool:
    """Copy ``text`` to the system clipboard. Returns True on success."""
    payload = text if text is not None else ""
    system = platform.system()
    copiers: list[Callable[[str], bool]]
    if system == "Darwin":
        copiers = [_mac_copy]
    elif system == "Windows":
        copiers = [_windows_copy]
    else:
        copiers = [_linux_copy]
    for copier in copiers:
        if copier(payload):
            return True
    return False
