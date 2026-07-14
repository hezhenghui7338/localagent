"""Hot-layer core profile (pinned facts)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from localagent import config


@dataclass
class LifeAnchor:
    label: str
    start: str
    end: str | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LifeAnchor:
        return cls(
            label=data["label"],
            start=data["start"],
            end=data.get("end"),
            description=data.get("description", ""),
        )


@dataclass
class CoreProfile:
    name: str = ""
    preferences: dict[str, str] = field(default_factory=dict)
    current_status: str = ""
    life_anchors: list[LifeAnchor] = field(default_factory=list)
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "preferences": self.preferences,
            "current_status": self.current_status,
            "life_anchors": [a.to_dict() for a in self.life_anchors],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoreProfile:
        return cls(
            name=data.get("name", ""),
            preferences=dict(data.get("preferences", {})),
            current_status=data.get("current_status", ""),
            life_anchors=[LifeAnchor.from_dict(a) for a in data.get("life_anchors", [])],
            updated_at=data.get("updated_at", ""),
        )

    def format_for_prompt(self) -> str:
        lines = ["[Core Profile]"]
        if self.name:
            lines.append(f"姓名: {self.name}")
        if self.current_status:
            lines.append(f"当前状态: {self.current_status}")
        for key, val in self.preferences.items():
            lines.append(f"{key}: {val}")
        if self.life_anchors:
            lines.append("人生阶段锚点:")
            for anchor in self.life_anchors:
                end = anchor.end or "至今"
                lines.append(f"  - {anchor.label} ({anchor.start} ~ {end}): {anchor.description}")
        return "\n".join(lines)


def load_core_profile() -> CoreProfile:
    if not config.CORE_PROFILE_FILE.exists():
        return CoreProfile()
    try:
        data = json.loads(config.CORE_PROFILE_FILE.read_text(encoding="utf-8"))
        return CoreProfile.from_dict(data)
    except Exception:
        return CoreProfile()


def home_location() -> str:
    """Return pinned 居住地 from the core profile, if any."""
    place = (load_core_profile().preferences.get("居住地") or "").strip()
    return place


def resolve_home_location(*, pin_from_memory: bool = True) -> str:
    """Resolve 居住地: profile first, then scan memory and pin if found."""
    place = home_location()
    if place:
        return place
    if not pin_from_memory:
        return ""
    try:
        from localagent.memory.profile_pin import _LOCATION_FACT, pin_fact_with_regex
        from localagent.memory.store import get_memory_store

        texts = [
            (fact.text or "").strip()
            for fact in get_memory_store().all_facts()
            if (fact.text or "").strip()
        ]
        # Prefer newer facts (typically appended later).
        for text in reversed(texts):
            if not _LOCATION_FACT.search(text):
                continue
            if pin_fact_with_regex(text):
                place = home_location()
                if place:
                    return place
            place = home_location()
            if place:
                return place
    except Exception:
        return home_location()
    return home_location()


def save_core_profile(profile: CoreProfile) -> None:
    """Persist profile without accidentally wiping existing preferences."""
    config.ensure_data_dirs()
    if config.CORE_PROFILE_FILE.exists():
        try:
            existing = load_core_profile()
        except Exception:
            existing = None
        if existing and existing.preferences:
            # Merge: never drop existing keys when incoming preferences is empty
            # or missing keys (guards against blank starter overwrites).
            merged = dict(existing.preferences)
            merged.update({k: v for k, v in profile.preferences.items() if str(v).strip()})
            profile.preferences = merged
            if not profile.name and existing.name:
                profile.name = existing.name
            if (
                (not profile.current_status or profile.current_status == "LocalAgent 用户")
                and existing.current_status
                and existing.current_status != "LocalAgent 用户"
            ):
                profile.current_status = existing.current_status
            if not profile.life_anchors and existing.life_anchors:
                profile.life_anchors = list(existing.life_anchors)
    profile.updated_at = datetime.now().isoformat(timespec="seconds")
    config.CORE_PROFILE_FILE.write_text(
        json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def default_core_profile() -> CoreProfile:
    """Ensure a starter profile exists without wiping pinned preferences."""
    profile = load_core_profile()
    if profile.name or profile.life_anchors or profile.preferences:
        if not profile.current_status:
            profile.current_status = "LocalAgent 用户"
            # Direct write to avoid merge recursion edge cases on status-only fill.
            profile.updated_at = datetime.now().isoformat(timespec="seconds")
            config.ensure_data_dirs()
            config.CORE_PROFILE_FILE.write_text(
                json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return profile
    if not config.CORE_PROFILE_FILE.exists():
        profile = CoreProfile(current_status="LocalAgent 用户")
        profile.updated_at = datetime.now().isoformat(timespec="seconds")
        config.ensure_data_dirs()
        config.CORE_PROFILE_FILE.write_text(
            json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return profile
    if not profile.current_status:
        profile.current_status = "LocalAgent 用户"
        profile.updated_at = datetime.now().isoformat(timespec="seconds")
        config.ensure_data_dirs()
        config.CORE_PROFILE_FILE.write_text(
            json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    return profile