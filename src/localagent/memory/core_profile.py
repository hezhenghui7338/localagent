"""Hot-layer core profile (pinned facts)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from localagent import config

SCHEMA_VERSION = 2


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
class WorkEntry:
    company: str
    role: str = ""
    start: str = ""
    end: str | None = None
    highlights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "company": self.company,
            "role": self.role,
            "start": self.start,
            "end": self.end,
            "highlights": list(self.highlights),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkEntry:
        return cls(
            company=str(data.get("company") or "").strip(),
            role=str(data.get("role") or "").strip(),
            start=str(data.get("start") or "").strip(),
            end=data.get("end"),
            highlights=[str(h) for h in (data.get("highlights") or []) if str(h).strip()],
        )


@dataclass
class EducationEntry:
    school: str = ""
    degree: str = ""
    major: str = ""
    start: str = ""
    end: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "school": self.school,
            "degree": self.degree,
            "major": self.major,
            "start": self.start,
            "end": self.end,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EducationEntry:
        return cls(
            school=str(data.get("school") or "").strip(),
            degree=str(data.get("degree") or "").strip(),
            major=str(data.get("major") or "").strip(),
            start=str(data.get("start") or "").strip(),
            end=str(data.get("end") or "").strip(),
        )


@dataclass
class ProjectEntry:
    name: str
    description: str = ""
    role: str = ""
    start: str = ""
    end: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "role": self.role,
            "start": self.start,
            "end": self.end,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectEntry:
        return cls(
            name=str(data.get("name") or "").strip(),
            description=str(data.get("description") or "").strip(),
            role=str(data.get("role") or "").strip(),
            start=str(data.get("start") or "").strip(),
            end=str(data.get("end") or "").strip(),
        )


@dataclass
class CoreProfile:
    name: str = ""
    preferences: dict[str, str] = field(default_factory=dict)
    current_status: str = ""
    life_anchors: list[LifeAnchor] = field(default_factory=list)
    skills: dict[str, list[str]] = field(default_factory=dict)
    work_experience: list[WorkEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    projects: list[ProjectEntry] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)
    contact: dict[str, str] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "preferences": self.preferences,
            "current_status": self.current_status,
            "life_anchors": [a.to_dict() for a in self.life_anchors],
            "updated_at": self.updated_at,
        }
        if self.skills:
            payload["skills"] = self.skills
        if self.work_experience:
            payload["work_experience"] = [w.to_dict() for w in self.work_experience]
        if self.education:
            payload["education"] = [e.to_dict() for e in self.education]
        if self.projects:
            payload["projects"] = [p.to_dict() for p in self.projects]
        if self.goals:
            payload["goals"] = list(self.goals)
        if self.contact:
            payload["contact"] = dict(self.contact)
        if self.sources:
            payload["sources"] = list(self.sources)
        if self.schema_version != 1:
            payload["schema_version"] = self.schema_version
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CoreProfile:
        skills_raw = data.get("skills") or {}
        skills: dict[str, list[str]] = {}
        if isinstance(skills_raw, dict):
            for key, val in skills_raw.items():
                if isinstance(val, list):
                    skills[str(key)] = [str(item) for item in val if str(item).strip()]
                elif val:
                    skills[str(key)] = [str(val)]

        return cls(
            name=data.get("name", ""),
            preferences=dict(data.get("preferences", {})),
            current_status=data.get("current_status", ""),
            life_anchors=[LifeAnchor.from_dict(a) for a in data.get("life_anchors", [])],
            skills=skills,
            work_experience=[
                WorkEntry.from_dict(w) for w in data.get("work_experience", []) if isinstance(w, dict)
            ],
            education=[
                EducationEntry.from_dict(e) for e in data.get("education", []) if isinstance(e, dict)
            ],
            projects=[
                ProjectEntry.from_dict(p) for p in data.get("projects", []) if isinstance(p, dict)
            ],
            goals=[str(g) for g in data.get("goals", []) if str(g).strip()],
            contact={
                str(k): str(v)
                for k, v in (data.get("contact") or {}).items()
                if str(v).strip()
            },
            sources=[str(s) for s in data.get("sources", []) if str(s).strip()],
            schema_version=int(data.get("schema_version") or SCHEMA_VERSION),
            updated_at=data.get("updated_at", ""),
        )

    def format_for_prompt(self, max_chars: int | None = None) -> str:
        lines = ["[Core Profile]"]
        if self.name:
            lines.append(f"姓名: {self.name}")
        if self.current_status:
            lines.append(f"当前状态: {self.current_status}")
        for key, val in self.preferences.items():
            lines.append(f"{key}: {val}")
        if self.skills:
            lines.append("技能:")
            for category, items in self.skills.items():
                joined = "、".join(items[:8])
                lines.append(f"  - {category}: {joined}")
        if self.work_experience:
            lines.append("工作经历:")
            for entry in self.work_experience[:6]:
                end = entry.end or "至今"
                span = f" ({entry.start} ~ {end})" if entry.start or entry.end else ""
                role = f" · {entry.role}" if entry.role else ""
                lines.append(f"  - {entry.company}{role}{span}")
        if self.projects:
            lines.append("项目:")
            for project in self.projects[:6]:
                desc = f": {project.description}" if project.description else ""
                lines.append(f"  - {project.name}{desc}")
        if self.goals:
            lines.append(f"目标: {'；'.join(self.goals[:4])}")
        if self.life_anchors:
            lines.append("人生阶段锚点:")
            for anchor in self.life_anchors:
                end = anchor.end or "至今"
                lines.append(f"  - {anchor.label} ({anchor.start} ~ {end}): {anchor.description}")
        text = "\n".join(lines)
        if max_chars is not None and len(text) > max_chars:
            return text[: max(0, max_chars - 1)] + "…"
        return text


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
    profile = load_core_profile()
    place = (profile.preferences.get("居住地") or profile.contact.get("location") or "").strip()
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


def _merge_profile(existing: CoreProfile, incoming: CoreProfile) -> None:
    merged_prefs = dict(existing.preferences)
    merged_prefs.update({k: v for k, v in incoming.preferences.items() if str(v).strip()})
    incoming.preferences = merged_prefs

    if not incoming.name and existing.name:
        incoming.name = existing.name
    if (
        (not incoming.current_status or incoming.current_status == "LocalAgent 用户")
        and existing.current_status
        and existing.current_status != "LocalAgent 用户"
    ):
        incoming.current_status = existing.current_status
    if not incoming.life_anchors and existing.life_anchors:
        incoming.life_anchors = list(existing.life_anchors)
    if not incoming.skills and existing.skills:
        incoming.skills = dict(existing.skills)
    if not incoming.work_experience and existing.work_experience:
        incoming.work_experience = list(existing.work_experience)
    if not incoming.education and existing.education:
        incoming.education = list(existing.education)
    if not incoming.projects and existing.projects:
        incoming.projects = list(existing.projects)
    if not incoming.goals and existing.goals:
        incoming.goals = list(existing.goals)
    if not incoming.contact and existing.contact:
        incoming.contact = dict(existing.contact)
    if not incoming.sources and existing.sources:
        incoming.sources = list(existing.sources)


def save_core_profile(profile: CoreProfile) -> None:
    """Persist profile without accidentally wiping existing preferences."""
    config.ensure_data_dirs()
    if config.CORE_PROFILE_FILE.exists():
        try:
            existing = load_core_profile()
        except Exception:
            existing = None
        if existing:
            _merge_profile(existing, profile)
    profile.updated_at = datetime.now().isoformat(timespec="seconds")
    config.CORE_PROFILE_FILE.write_text(
        json.dumps(profile.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def default_core_profile() -> CoreProfile:
    """Ensure a starter profile exists without wiping pinned preferences."""
    profile = load_core_profile()
    if (
        profile.name
        or profile.life_anchors
        or profile.preferences
        or profile.skills
        or profile.work_experience
        or profile.projects
    ):
        if not profile.current_status:
            profile.current_status = "LocalAgent 用户"
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
