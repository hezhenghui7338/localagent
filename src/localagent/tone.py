"""Evening postscript tone: late-hour closing line after the main answer."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from localagent import config
from localagent.i18n import t

Surface = Literal["chat", "aware"]

_ENABLED = frozenset({"1", "true", "yes", "on"})


def evening_enabled() -> bool:
    """Whether LA_TONE_EVENING is on."""
    raw = str(getattr(config, "TONE_EVENING", "off") or "off").strip().lower()
    return raw in _ENABLED


def evening_late(now: datetime | None = None) -> bool:
    """True when local clock is in the late-night window (crosses midnight)."""
    dt = now if now is not None else datetime.now().astimezone()
    if dt.tzinfo is None:
        dt = dt.astimezone()
    else:
        dt = dt.astimezone()
    hour = dt.hour
    start = int(getattr(config, "TONE_EVENING_START", 23) or 23) % 24
    end = int(getattr(config, "TONE_EVENING_END", 6) or 6) % 24
    if start == end:
        return False
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


def evening_active(now: datetime | None = None) -> bool:
    """Enabled and currently in the late window."""
    return evening_enabled() and evening_late(now)


def evening_postscript_block(
    *,
    surface: Surface = "chat",
    now: datetime | None = None,
) -> str:
    """Prompt overlay for a one-line late-night closing; empty when inactive."""
    if not evening_active(now):
        return ""
    key = "prompt.tone_evening_aware" if surface == "aware" else "prompt.tone_evening_chat"
    return t(key)
