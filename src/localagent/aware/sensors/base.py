"""Shared helpers for sensors."""

from __future__ import annotations

import re
from typing import Any

_SECRET_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|bearer|akia)[=:\s]+\S+"
)


def redact_secrets(text: str) -> str:
    return _SECRET_RE.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=***", text)


def int_cursor(cursor: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(cursor.get(key, default) or default)
    except (TypeError, ValueError):
        return default
