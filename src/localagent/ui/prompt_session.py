"""prompt_toolkit-based REPL line input (Unicode-safe; replaces raw ANSI editor)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.shortcuts.prompt import CompleteStyle

if TYPE_CHECKING:
    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document

_SESSION: PromptSession[str] | None = None


def _token_before_cursor(text_before: str) -> tuple[str, int]:
    """Return ``(token, start_index)`` for the word under the cursor (whitespace-delimited)."""
    start = len(text_before)
    while start > 0 and not text_before[start - 1].isspace():
        start -= 1
    return text_before[start:], start


class SessionSlashCompleter(Completer):
    """Adapt ``suggest_session_slash_completions`` for prompt_toolkit Tab completion."""

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        from localagent.completion import suggest_session_slash_completions

        before = document.text_before_cursor
        token, _start = _token_before_cursor(before)
        # Full line so arg completion sees trailing spaces / prior tokens.
        line = document.text
        hits = suggest_session_slash_completions(line, token)
        for hit in hits:
            yield Completion(hit, start_position=-len(token))


def clear_history() -> None:
    """Test helper: reset in-memory input history."""
    global _SESSION
    if _SESSION is not None:
        _SESSION.history = InMemoryHistory()


def get_repl_session() -> PromptSession[str]:
    """Return a module-level PromptSession (shared history + completer)."""
    global _SESSION
    if _SESSION is None:
        _SESSION = PromptSession(
            history=InMemoryHistory(),
            completer=SessionSlashCompleter(),
            complete_while_typing=False,
            multiline=False,
            complete_style=CompleteStyle.MULTI_COLUMN,
        )
    return _SESSION


def read_line_prompt_toolkit(prompt: str = "> ") -> str:
    """Read one line with prompt_toolkit. Requires an interactive TTY."""
    return get_repl_session().prompt(prompt)
