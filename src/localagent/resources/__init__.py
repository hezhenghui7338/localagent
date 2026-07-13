"""Bundled templates for first-run bootstrap (works after pip install)."""

from __future__ import annotations

from importlib.resources import files


def read_text(name: str) -> str | None:
    """Return packaged resource text, or None if missing."""
    try:
        return files(__name__).joinpath(name).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, ModuleNotFoundError, TypeError):
        return None
