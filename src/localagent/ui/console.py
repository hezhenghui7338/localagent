"""Lightweight terminal feedback without extra dependencies."""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Iterator


def emit(prefix: str, message: str, *, end: str = "\n") -> None:
    print(f"[{prefix}] {message}", flush=True, end=end)


def prepare_for_input() -> None:
    """Reset terminal attributes before readline/input()."""
    if sys.stdout.isatty():
        sys.stdout.write("\x1b[0m")
        sys.stdout.flush()


def _uses_libedit() -> bool:
    try:
        import readline
    except ImportError:
        return False
    doc = getattr(readline, "__doc__", "") or ""
    return "libedit" in doc


def read_repl_line(prompt: str = "> ") -> str:
    """Read a REPL line; keep prompt out of libedit's redraw buffer on macOS.

    Passing the prompt into ``input()`` lets libedit re-paint it after Tab
    completion lists, which can leave undeletable ghost characters (e.g. ``>``).
    """
    if sys.stdin.isatty() and _uses_libedit():
        sys.stdout.write(prompt)
        sys.stdout.flush()
        return input()
    return input(prompt)


class ActivityIndicator:
    """Status lines for long operations; always newline-based (no \\r overlays)."""

    def __init__(self, prefix: str, message: str) -> None:
        self.prefix = prefix
        self.message = message
        self._started_at = 0.0
        self._last_logged = ""
        self._streaming = False

    def begin_streaming(self) -> None:
        """Mark that streamed output follows; response prints on its own line."""
        self._streaming = True

    def update(self, message: str) -> None:
        self.message = message
        if message != self._last_logged:
            emit(self.prefix, message)
            self._last_logged = message

    def __enter__(self) -> ActivityIndicator:
        self._started_at = time.monotonic()
        emit(self.prefix, self.message)
        self._last_logged = self.message
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._streaming:
            return
        elapsed = time.monotonic() - self._started_at
        if exc is None:
            emit(self.prefix, f"✓ {self.message} ({elapsed:.1f}s)")
        else:
            emit(self.prefix, f"✗ {self.message}")


@contextmanager
def spinner(prefix: str, message: str) -> Iterator[None]:
    with ActivityIndicator(prefix, message):
        yield
