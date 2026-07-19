"""Shared types for aware sensors and events."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

ALL_SOURCES = (
    "fs",
    "git",
    "terminal",
    "browser",
    "apps",
    "wechat",
    "calendar",
    "email",
)

IMPLEMENTED_SOURCES = frozenset({"fs", "git", "terminal", "browser", "apps"})

SENSITIVE_SOURCES = frozenset(
    {"browser", "terminal", "wechat", "apps", "calendar", "email"}
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AwareEvent:
    source: str
    kind: str
    title: str
    ts: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AwareEvent:
        return cls(
            source=str(raw.get("source") or ""),
            kind=str(raw.get("kind") or ""),
            title=str(raw.get("title") or ""),
            ts=str(raw.get("ts") or ""),
            data=dict(raw.get("data") or {}),
        )


class Sensor(Protocol):
    name: str

    def describe_access(self) -> list[str]:
        """Paths / resources that will be read (for grant UX)."""
        ...

    def collect(self, cursor: dict[str, Any]) -> tuple[list[AwareEvent], dict[str, Any]]:
        """Return new events and updated cursor. Must not read if not granted (caller checks)."""
        ...
