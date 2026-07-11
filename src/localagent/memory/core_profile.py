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


def save_core_profile(profile: CoreProfile) -> None:
    config.ensure_data_dirs()
    profile.updated_at = datetime.now().isoformat(timespec="seconds")
    config.CORE_PROFILE_FILE.write_text(
        json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def default_core_profile() -> CoreProfile:
    """Create a starter profile if none exists."""
    profile = load_core_profile()
    if profile.name or profile.life_anchors:
        return profile
    profile = CoreProfile(
        name="",
        current_status="LocalAgent 用户",
        life_anchors=[],
    )
    save_core_profile(profile)
    return profile
