"""Open article URLs in the system browser."""

from __future__ import annotations

import webbrowser


def open_in_browser(url: str) -> bool:
    """Open ``url`` in the default browser. Returns True on success."""
    href = (url or "").strip()
    if not href:
        return False
    try:
        return bool(webbrowser.open(href, new=2))
    except Exception:
        return False
