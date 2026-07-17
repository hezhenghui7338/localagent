"""Terminal / markdown link helpers for news articles."""

from __future__ import annotations

import os
import sys


def _use_osc8() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    # Most modern terminals (iTerm, Cursor, VS Code, Ghostty) support OSC 8.
    return True


def hyperlink(label: str, url: str, *, force_plain: bool = False) -> str:
    """Render a clickable label; always appends bare URL for copy-paste safety."""
    text = (label or url or "").strip() or url
    href = (url or "").strip()
    if not href:
        return text
    if force_plain or not _use_osc8():
        return f"[{text}]({href})"
    # OSC 8: ESC ] 8 ; ; URL ST  text ESC ] 8 ; ; ST
    return f"\033]8;;{href}\033\\{text}\033]8;;\033\\"


def format_article_link_block(
    *,
    title: str,
    url: str,
    plain: bool = False,
) -> str:
    """Title as hyperlink + bare URL line (always browsable / copyable)."""
    link = hyperlink(title or url, url, force_plain=plain)
    return f"{link}\n  原文: {url}"
