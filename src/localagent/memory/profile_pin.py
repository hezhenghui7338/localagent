"""Pin durable personal facts into the Hot-layer core profile.

Primary path: LLM structured decisions (LA_PROFILE_PIN_LLM=1).
Fallback: regex heuristics when LLM fails or is disabled.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from localagent import config
from localagent.memory.core_profile import (
    CoreProfile,
    LifeAnchor,
    load_core_profile,
    save_core_profile,
)

logger = logging.getLogger(__name__)

# Occupation / role words that must not be treated as a personal name.
_ROLE_WORDS = (
    "开发",
    "工程师",
    "程序员",
    "设计师",
    "产品",
    "经理",
    "学生",
    "老师",
    "医生",
    "律师",
    "老板",
    "创始人",
    "自由职业",
    "用户",
    "LocalAgent",
)

_LOCATION_FACT = re.compile(
    r"(?:我)?(?:居住在|住在|现居(?:于|在)?|位于|家在|来自)(?P<place>[^。，,；;\n]{2,20})"
)
_NAME_FACT = re.compile(
    r"(?:我(?:的名字)?叫|姓名[:：]\s*|我的名字是)(?P<name>[\u4e00-\u9fffA-Za-z]{2,12})"
)
# "我是张三" — only when the capture is a plausible name, not a role.
_NAME_IS_FACT = re.compile(
    r"我是(?P<name>[\u4e00-\u9fffA-Za-z]{2,4})(?![工程师开发程序员设计师产品经理学生老师医生])"
)
_OCCUPATION_FACT = re.compile(
    r"(?:"
    r"(?:我是(?:一名|一个|个)?(?P<role1>[^。，,；;\n]{2,20}?(?:工程师|开发者|程序员|设计师|经理|学生|医生|律师|老师)))"
    r"|(?:(?:我的?)?(?:职业|工作)(?:是|为)(?P<role2>[^。，,；;\n]{2,20}))"
    r"|(?:我(?:在做|从事)(?P<role3>[^。，,；;\n]{2,20}))"
    r")"
)
_FAMILY_FACT = re.compile(
    r"(?:"
    r"(?:我)?有(?P<count>[一两二三四五六七八九十\d]+)个?(?P<who>儿子|女儿|孩子|小孩)"
    r"|(?:我的?)(?P<rel>儿子|女儿|孩子|老婆|丈夫|太太|父母|家人)(?P<detail>[^。，,；;\n]{0,30})"
    r")"
)
_PREFERENCE_FACT = re.compile(
    r"(?:我)?(?:喜欢|偏好|习惯|不喜欢|讨厌)(?P<item>[^。，,；;\n]{2,24})"
)

_PREF_FIELD_ALIASES = {
    "location": "居住地",
    "居住地": "居住地",
    "occupation": "职业",
    "职业": "职业",
    "工作": "职业",
    "family": "家庭",
    "家庭": "家庭",
    "preference": "偏好",
    "偏好": "偏好",
    "喜欢": "喜欢",
}


def _looks_like_role(text: str) -> bool:
    return any(word in text for word in _ROLE_WORDS)


def _set_pref(profile: CoreProfile, key: str, value: str) -> bool:
    value = value.strip(" 。，,的了")
    if not value:
        return False
    if profile.preferences.get(key) == value:
        return False
    profile.preferences[key] = value
    return True


def _confidence_ok(item: dict[str, Any]) -> bool:
    try:
        conf = float(item.get("confidence", 1.0))
    except (TypeError, ValueError):
        conf = 1.0
    return conf >= config.PROFILE_PIN_MIN_CONFIDENCE


def apply_profile_updates(updates: list[dict[str, Any]], *, profile: CoreProfile | None = None) -> bool:
    """Apply structured pin updates to core_profile. Returns True if saved."""
    if not updates:
        return False
    profile = profile or load_core_profile()
    changed = False

    for item in updates:
        if not _confidence_ok(item):
            continue
        field = str(item.get("field") or "").strip().lower()
        value = str(item.get("value") or "").strip()
        if not value and field != "life_anchor":
            continue

        if field == "name":
            candidate = value.strip()
            if candidate and candidate not in {"用户", "LocalAgent"} and not _looks_like_role(candidate):
                if profile.name != candidate:
                    profile.name = candidate
                    changed = True
            continue

        if field in {"current_status", "status"}:
            if value and profile.current_status != value:
                profile.current_status = value
                changed = True
            continue

        if field in {"preference", "preferences", "pref"}:
            key_raw = str(item.get("key") or "偏好").strip() or "偏好"
            key = _PREF_FIELD_ALIASES.get(key_raw, key_raw)
            if _set_pref(profile, key, value):
                changed = True
                if key == "职业" and (
                    not profile.current_status or profile.current_status == "LocalAgent 用户"
                ):
                    profile.current_status = value
            continue

        # Convenience: allow field to be a known preference key directly.
        if field in _PREF_FIELD_ALIASES or field in {"居住地", "职业", "家庭", "喜欢", "偏好"}:
            key = _PREF_FIELD_ALIASES.get(field, field)
            if _set_pref(profile, key, value):
                changed = True
                if key == "职业" and (
                    not profile.current_status or profile.current_status == "LocalAgent 用户"
                ):
                    profile.current_status = value
            continue

        if field in {"life_anchor", "life_anchors", "anchor"}:
            label = str(item.get("label") or value or "").strip()
            start = str(item.get("start") or "").strip()
            if not label or not start:
                continue
            end_raw = item.get("end")
            end = None if end_raw in (None, "", "null", "None") else str(end_raw).strip()
            description = str(item.get("description") or value or "").strip()
            # Upsert by label+start.
            existing = next(
                (a for a in profile.life_anchors if a.label == label and a.start == start),
                None,
            )
            if existing:
                if end is not None and existing.end != end:
                    existing.end = end
                    changed = True
                if description and existing.description != description:
                    existing.description = description
                    changed = True
            else:
                profile.life_anchors.append(
                    LifeAnchor(label=label, start=start, end=end, description=description)
                )
                changed = True
            continue

    if changed:
        save_core_profile(profile)
    return changed


def pin_fact_with_regex(fact: str, *, profile: CoreProfile | None = None) -> bool:
    """Regex fallback pin. Returns True if profile was saved."""
    text = fact.strip()
    if not text:
        return False

    own_profile = profile is None
    profile = profile or load_core_profile()
    changed = False

    location = _LOCATION_FACT.search(text)
    if location:
        place = location.group("place").strip(" 。，,的")
        if place and _set_pref(profile, "居住地", place):
            changed = True

    occupation = _OCCUPATION_FACT.search(text)
    if occupation:
        role = (
            occupation.group("role1")
            or occupation.group("role2")
            or occupation.group("role3")
            or ""
        ).strip(" 。，,的")
        if role:
            if _set_pref(profile, "职业", role):
                changed = True
            if not profile.current_status or profile.current_status == "LocalAgent 用户":
                if profile.current_status != role:
                    profile.current_status = role
                    changed = True

    family = _FAMILY_FACT.search(text)
    if family:
        count = family.groupdict().get("count")
        who = family.groupdict().get("who")
        if count and who:
            cn = {"一": "1", "两": "2", "二": "2", "三": "3", "四": "4", "五": "5"}
            num = cn.get(count, count)
            summary = f"有{num}个{who}"
        else:
            rel = (family.groupdict().get("rel") or "").strip()
            detail = (family.groupdict().get("detail") or "").strip(" 。，,的是")
            summary = f"{rel}{detail}".strip() if detail else rel
        if summary and _set_pref(profile, "家庭", summary):
            changed = True

    pref = _PREFERENCE_FACT.search(text)
    if pref:
        item = pref.group("item").strip(" 。，,的了")
        verb_match = re.search(r"(喜欢|偏好|习惯|不喜欢|讨厌)", text)
        verb = verb_match.group(1) if verb_match else "偏好"
        if item and _set_pref(profile, verb, item):
            changed = True

    name = _NAME_FACT.search(text)
    candidate = ""
    if name:
        candidate = name.group("name").strip()
    else:
        name_is = _NAME_IS_FACT.search(text)
        if name_is:
            candidate = name_is.group("name").strip()
            if _looks_like_role(candidate):
                candidate = ""
    if candidate and candidate not in {"用户", "LocalAgent"} and not _looks_like_role(candidate):
        if not profile.name:
            profile.name = candidate
            changed = True

    if changed and own_profile:
        save_core_profile(profile)
    return changed


def _pin_with_llm(facts: list[str]) -> bool:
    from localagent.models.router import get_model_router

    profile = load_core_profile()
    updates = get_model_router().extract_profile_updates(
        facts,
        current_profile=profile.format_for_prompt(),
    )
    if not updates:
        return False
    return apply_profile_updates(updates, profile=profile)


def pin_facts_to_profile(facts: list[str]) -> None:
    """Pin durable identity facts into core_profile (LLM primary, regex fallback)."""
    cleaned = [f.strip() for f in facts if f and f.strip()]
    if not cleaned:
        return

    if config.PROFILE_PIN_LLM:
        try:
            _pin_with_llm(cleaned)
            return  # LLM path succeeded (applied updates or decided none)
        except Exception as exc:
            logger.warning("profile pin LLM failed, falling back to regex: %s", exc)
            if not config.PROFILE_PIN_REGEX_FALLBACK:
                return

    # Regex: LLM disabled, or LLM raised and fallback enabled.
    profile = load_core_profile()
    changed = False
    for fact in cleaned:
        if pin_fact_with_regex(fact, profile=profile):
            changed = True
    if changed:
        save_core_profile(profile)


def maybe_pin_fact_to_profile(fact: str) -> None:
    """Pin a single fact (compat wrapper around pin_facts_to_profile)."""
    pin_facts_to_profile([fact])


_CITY_UTTERANCE = re.compile(
    r"(?:"
    r"北京|上海|广州|深圳|杭州|南京|成都|重庆|武汉|西安|苏州|天津|长沙|郑州|"
    r"青岛|大连|厦门|福州|宁波|无锡|合肥|济南|昆明|贵阳|南宁|海口|三亚|"
    r"哈尔滨|长春|沈阳|石家庄|太原|兰州|南昌|台北|香港|澳门|"
    r"东莞|佛山|珠海|中山|惠州|温州|嘉兴|金华|绍兴|"
    r"[\u4e00-\u9fff]{2,10}(?:市|区|县)"
    r")"
)


def pin_location_from_utterance(text: str) -> str:
    """Pin 居住地 from a short reply like「深圳」or「查一下北京」. Returns city or ''."""
    raw = (text or "").strip()
    if not raw:
        return ""
    match = _CITY_UTTERANCE.search(raw)
    if not match:
        return ""
    city = match.group(0).rstrip("市区县")
    if not city:
        return ""
    maybe_pin_fact_to_profile(f"现居{city}")
    from localagent.memory.core_profile import home_location

    return home_location() or city
