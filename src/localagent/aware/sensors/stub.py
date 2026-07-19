"""Placeholder sensors for not-yet-implemented sources."""

from __future__ import annotations

from typing import Any

from localagent.aware.types import AwareEvent


class StubSensor:
    def __init__(self, name: str) -> None:
        self.name = name

    def describe_access(self) -> list[str]:
        return [f"（{self.name} 传感器尚未实现）"]

    def collect(self, cursor: dict[str, Any]) -> tuple[list[AwareEvent], dict[str, Any]]:
        return [], dict(cursor)
