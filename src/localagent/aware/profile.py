"""Aware grant/ungrant profile and watch paths."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from localagent import config
from localagent.aware.types import ALL_SOURCES, utc_now


@dataclass
class SourceGrant:
    granted: bool = False
    granted_at: str = ""
    paths: list[str] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)
    history_files: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> SourceGrant:
        raw = raw or {}
        return cls(
            granted=bool(raw.get("granted")),
            granted_at=str(raw.get("granted_at") or ""),
            paths=[str(p) for p in list(raw.get("paths") or [])],
            repos=[str(p) for p in list(raw.get("repos") or [])],
            history_files=[str(p) for p in list(raw.get("history_files") or [])],
            note=str(raw.get("note") or ""),
        )


@dataclass
class AwareProfile:
    sources: dict[str, SourceGrant] = field(default_factory=dict)
    schedule_enabled: bool = False
    interval_minutes: int = 15
    last_tick_at: str = ""
    updated_at: str = ""

    def grant_for(self, source: str) -> SourceGrant:
        if source not in self.sources:
            self.sources[source] = SourceGrant()
        return self.sources[source]

    def is_granted(self, source: str) -> bool:
        return bool(self.sources.get(source) and self.sources[source].granted)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": {k: v.to_dict() for k, v in self.sources.items()},
            "schedule_enabled": self.schedule_enabled,
            "interval_minutes": self.interval_minutes,
            "last_tick_at": self.last_tick_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AwareProfile:
        sources_raw = dict(raw.get("sources") or {})
        sources = {name: SourceGrant.from_dict(sources_raw.get(name)) for name in ALL_SOURCES}
        for name, grant in sources_raw.items():
            if name not in sources:
                sources[name] = SourceGrant.from_dict(grant)
        return cls(
            sources=sources,
            schedule_enabled=bool(raw.get("schedule_enabled")),
            interval_minutes=int(
                raw.get("interval_minutes") or config.AWARE_TICK_INTERVAL_MINUTES
            ),
            last_tick_at=str(raw.get("last_tick_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
        )


def _profile_path() -> Path:
    return Path(config.AWARE_PROFILE_FILE)


def default_profile() -> AwareProfile:
    profile = AwareProfile(
        interval_minutes=config.AWARE_TICK_INTERVAL_MINUTES,
        sources={name: SourceGrant() for name in ALL_SOURCES},
    )
    return profile


def load_profile() -> AwareProfile:
    path = _profile_path()
    if not path.exists():
        return default_profile()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_profile()
    if not isinstance(raw, dict):
        return default_profile()
    return AwareProfile.from_dict(raw)


def save_profile(profile: AwareProfile) -> None:
    config.ensure_data_dirs()
    path = _profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    profile.updated_at = utc_now()
    payload = profile.to_dict()
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        suffix=".tmp",
    ) as tmp:
        tmp.write(json.dumps(payload, ensure_ascii=False, indent=2))
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def grant_source(
    source: str,
    *,
    paths: list[str] | None = None,
    repos: list[str] | None = None,
    history_files: list[str] | None = None,
    note: str = "",
) -> AwareProfile:
    profile = load_profile()
    grant = profile.grant_for(source)
    grant.granted = True
    grant.granted_at = utc_now()
    if paths is not None:
        grant.paths = list(paths)
    if repos is not None:
        grant.repos = list(repos)
    if history_files is not None:
        grant.history_files = list(history_files)
    if note:
        grant.note = note
    save_profile(profile)
    return profile


def ungrant_source(source: str) -> AwareProfile:
    """Clear grant for one source or all."""
    profile = load_profile()
    if source == "all":
        for name in list(profile.sources):
            g = profile.grant_for(name)
            g.granted = False
            g.granted_at = ""
    else:
        g = profile.grant_for(source)
        g.granted = False
        g.granted_at = ""
    save_profile(profile)
    return profile
