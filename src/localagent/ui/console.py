"""Lightweight terminal feedback and REPL line input."""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Iterator


def emit(prefix: str, message: str, *, end: str = "\n") -> None:
    print(f"[{prefix}] {message}", flush=True, end=end)


def prepare_for_input() -> None:
    """Reset terminal attributes before prompt_toolkit / input()."""
    if sys.stdout.isatty():
        sys.stdout.write("\x1b[0m")
        sys.stdout.flush()


def use_prompt_toolkit_repl() -> bool:
    """True when chat REPL should use prompt_toolkit (interactive TTY)."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return False
    try:
        import prompt_toolkit  # noqa: F401
    except ImportError:
        return False
    return True


def read_repl_line(prompt: str = "> ") -> str:
    """Read a REPL line with Unicode-safe editing on TTYs.

    Interactive TTYs use prompt_toolkit (wcwidth, history, Tab completion).
    Non-TTY / missing-toolkit fallbacks keep ``input()``; the prompt must still
    be passed into ``input()`` so libedit cannot erase a separately printed ``>``.
    """
    if use_prompt_toolkit_repl():
        from localagent.ui.prompt_session import read_line_prompt_toolkit

        try:
            return read_line_prompt_toolkit(prompt)
        except EOFError:
            raise
        except OSError:
            pass
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
