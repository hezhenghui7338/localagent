"""Aware sensor implementations."""

from __future__ import annotations

from typing import Any

from localagent.aware.profile import AwareProfile, SourceGrant
from localagent.aware.sensors.apps import AppsSensor
from localagent.aware.sensors.browser import BrowserSensor
from localagent.aware.sensors.fs import FsSensor
from localagent.aware.sensors.git import GitSensor
from localagent.aware.sensors.stub import StubSensor
from localagent.aware.sensors.terminal import TerminalSensor
from localagent.aware.types import IMPLEMENTED_SOURCES


def build_sensor(source: str, grant: SourceGrant):
    if source == "fs":
        return FsSensor(grant)
    if source == "git":
        return GitSensor(grant)
    if source == "terminal":
        return TerminalSensor(grant)
    if source == "browser":
        return BrowserSensor(grant)
    if source == "apps":
        return AppsSensor(grant)
    return StubSensor(source)


def iter_active_sensors(profile: AwareProfile) -> list[tuple[str, Any]]:
    out = []
    for name in IMPLEMENTED_SOURCES:
        if profile.is_granted(name):
            out.append((name, build_sensor(name, profile.grant_for(name))))
    return out
