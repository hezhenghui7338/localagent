"""Pin durable personal facts into the Hot-layer core profile."""

from __future__ import annotations

import re

from localagent.memory.core_profile import load_core_profile, save_core_profile

_LOCATION_FACT = re.compile(
    r"(?:我)?(?:居住在|住在|位于)(?P<place>[^。，,；;\n]{2,20})"
)
_NAME_FACT = re.compile(
    r"(?:我(?:的名字)?叫|我是|姓名[:：]\s*)(?P<name>[\u4e00-\u9fffA-Za-z]{2,12})"
)


def maybe_pin_fact_to_profile(fact: str) -> None:
    """Update core profile when a fact encodes durable identity attributes."""
    text = fact.strip()
    if not text:
        return

    profile = load_core_profile()
    changed = False

    location = _LOCATION_FACT.search(text)
    if location:
        place = location.group("place").strip(" 。，,的")
        if place and profile.preferences.get("居住地") != place:
            profile.preferences["居住地"] = place
            changed = True

    name = _NAME_FACT.search(text)
    if name and not profile.name:
        candidate = name.group("name").strip()
        if candidate and candidate not in {"用户", "LocalAgent"}:
            profile.name = candidate
            changed = True

    if changed:
        save_core_profile(profile)
