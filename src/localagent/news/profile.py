"""Local news interest profile (independent of Hot core_profile)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from localagent import config


@dataclass
class NewsProfile:
    interests: list[str] = field(
        default_factory=lambda: ["LLM Agent", "RAG", "本地模型", "评测"]
    )
    boost_keywords: list[str] = field(
        default_factory=lambda: ["Agent", "Claude", "Ollama", "RAG"]
    )
    mute_keywords: list[str] = field(default_factory=lambda: ["招聘", "广告"])
    prefer_languages: list[str] = field(default_factory=lambda: ["zh", "en"])
    daily_brief_size: int = 15
    deep_read_suggest: int = 3
    auto_sync_enabled: bool = True
    auto_sync_hour: int = 8
    auto_sync_minute: int = 0
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NewsProfile:
        defaults = cls()
        return cls(
            interests=list(data.get("interests") or defaults.interests),
            boost_keywords=list(data.get("boost_keywords") or defaults.boost_keywords),
            mute_keywords=list(data.get("mute_keywords") or defaults.mute_keywords),
            prefer_languages=list(
                data.get("prefer_languages") or defaults.prefer_languages
            ),
            daily_brief_size=int(
                data.get("daily_brief_size") or config.NEWS_BRIEF_SIZE
            ),
            deep_read_suggest=int(data.get("deep_read_suggest") or 3),
            auto_sync_enabled=bool(
                data.get("auto_sync_enabled", config.NEWS_AUTO_SYNC)
            ),
            auto_sync_hour=int(
                data.get("auto_sync_hour", config.NEWS_AUTO_SYNC_HOUR)
            ),
            auto_sync_minute=int(
                data.get("auto_sync_minute", config.NEWS_AUTO_SYNC_MINUTE)
            ),
            updated_at=str(data.get("updated_at") or ""),
        )


def _default_profile() -> NewsProfile:
    return NewsProfile(
        daily_brief_size=config.NEWS_BRIEF_SIZE,
        auto_sync_enabled=config.NEWS_AUTO_SYNC,
        auto_sync_hour=config.NEWS_AUTO_SYNC_HOUR,
        auto_sync_minute=config.NEWS_AUTO_SYNC_MINUTE,
    )


def load_news_profile() -> NewsProfile:
    path = config.NEWS_PROFILE_FILE
    if not path.exists():
        return _default_profile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return NewsProfile.from_dict(data if isinstance(data, dict) else {})
    except Exception:
        return _default_profile()


def save_news_profile(profile: NewsProfile) -> None:
    config.ensure_data_dirs()
    profile.updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    config.NEWS_PROFILE_FILE.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def add_mute_keyword(keyword: str) -> NewsProfile:
    profile = load_news_profile()
    kw = (keyword or "").strip()
    if kw and kw not in profile.mute_keywords:
        profile.mute_keywords.append(kw)
        save_news_profile(profile)
    return profile
