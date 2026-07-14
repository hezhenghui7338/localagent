"""Tests for Hot-layer profile pinning."""

from __future__ import annotations

from argparse import Namespace

from localagent.cli import cmd_add
from localagent.memory.core_profile import load_core_profile
from localagent.memory.profile_pin import (
    apply_profile_updates,
    maybe_pin_fact_to_profile,
    pin_fact_with_regex,
    pin_facts_to_profile,
)
from localagent.memory.save import save_facts
from localagent.models.router import _parse_profile_updates_reply


def test_pin_location_occupation_family_preference(isolated_data):
    maybe_pin_fact_to_profile("我居住在深圳")
    maybe_pin_fact_to_profile("我有两个儿子")
    maybe_pin_fact_to_profile("我是一名开发工程师")
    maybe_pin_fact_to_profile("我喜欢喝美式咖啡")

    profile = load_core_profile()
    assert profile.preferences.get("居住地") == "深圳"
    assert profile.preferences.get("家庭") == "有2个儿子"
    assert profile.preferences.get("职业") == "开发工程师"
    assert profile.current_status == "开发工程师"
    assert profile.preferences.get("喜欢") == "喝美式咖啡"


def test_pin_name_and_reject_role_as_name(isolated_data):
    maybe_pin_fact_to_profile("我是开发工程师")
    profile = load_core_profile()
    assert profile.name == ""
    assert profile.preferences.get("职业") == "开发工程师"

    maybe_pin_fact_to_profile("我叫林晓")
    profile = load_core_profile()
    assert profile.name == "林晓"


def test_pin_alternate_location_phrases(isolated_data):
    maybe_pin_fact_to_profile("家在广州")
    assert load_core_profile().preferences.get("居住地") == "广州"

    maybe_pin_fact_to_profile("我来自杭州")
    assert load_core_profile().preferences.get("居住地") == "杭州"

    maybe_pin_fact_to_profile("现居深圳")
    assert load_core_profile().preferences.get("居住地") == "深圳"

    maybe_pin_fact_to_profile("我现居于成都高新区")
    assert load_core_profile().preferences.get("居住地") == "成都高新区"


def test_save_facts_pins_profile(isolated_data):
    save_facts(["用户住在深圳，有两个儿子"])
    profile = load_core_profile()
    assert profile.preferences.get("居住地") == "深圳"
    assert profile.preferences.get("家庭") == "有2个儿子"


def test_cmd_add_pins_profile(isolated_data):
    rc = cmd_add(Namespace(text="记住：我居住在深圳，职业是软件工程师"))
    assert rc == 0
    profile = load_core_profile()
    assert profile.preferences.get("居住地") == "深圳"
    assert profile.preferences.get("职业") == "软件工程师"


def test_parse_profile_updates_reply():
    updates = _parse_profile_updates_reply(
        '{"updates":[{"field":"preference","key":"居住地","value":"深圳","confidence":0.95}]}'
    )
    assert len(updates) == 1
    assert updates[0]["value"] == "深圳"

    wrapped = _parse_profile_updates_reply(
        '```json\n{"updates":[{"field":"name","value":"林晓","confidence":0.9}]}\n```'
    )
    assert wrapped[0]["field"] == "name"


def test_apply_profile_updates_and_life_anchor(isolated_data):
    assert apply_profile_updates(
        [
            {"field": "name", "value": "林晓", "confidence": 0.9},
            {"field": "preference", "key": "居住地", "value": "深圳", "confidence": 0.95},
            {"field": "preference", "key": "家庭", "value": "有两个儿子", "confidence": 0.9},
            {"field": "preference", "key": "职业", "value": "开发工程师", "confidence": 0.9},
            {
                "field": "life_anchor",
                "label": "深圳工作",
                "start": "2020",
                "end": None,
                "description": "在深圳做软件开发",
                "value": "在深圳做软件开发",
                "confidence": 0.8,
            },
        ]
    )
    profile = load_core_profile()
    assert profile.name == "林晓"
    assert profile.preferences["居住地"] == "深圳"
    assert profile.preferences["家庭"] == "有两个儿子"
    assert profile.preferences["职业"] == "开发工程师"
    assert profile.current_status == "开发工程师"
    assert len(profile.life_anchors) == 1
    assert profile.life_anchors[0].label == "深圳工作"
    assert profile.life_anchors[0].start == "2020"


def test_llm_pin_path(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.PROFILE_PIN_LLM", True)
    monkeypatch.setattr("localagent.config.PROFILE_PIN_REGEX_FALLBACK", False)
    isolated_data["router"].extract_profile_updates.return_value = [
        {"field": "preference", "key": "居住地", "value": "鹏城", "confidence": 0.9},
        {"field": "preference", "key": "家庭", "value": "有两个儿子", "confidence": 0.9},
        {"field": "preference", "key": "职业", "value": "写代码的开发者", "confidence": 0.85},
    ]

    # Paraphrase that regex would miss for 鹏城 / 写代码的.
    pin_facts_to_profile(["我在鹏城工作，带俩娃，平时写代码"])

    profile = load_core_profile()
    assert profile.preferences.get("居住地") == "鹏城"
    assert profile.preferences.get("家庭") == "有两个儿子"
    assert profile.preferences.get("职业") == "写代码的开发者"
    isolated_data["router"].extract_profile_updates.assert_called()


def test_llm_failure_falls_back_to_regex(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.PROFILE_PIN_LLM", True)
    monkeypatch.setattr("localagent.config.PROFILE_PIN_REGEX_FALLBACK", True)
    isolated_data["router"].extract_profile_updates.side_effect = RuntimeError("llm down")

    pin_facts_to_profile(["我居住在深圳"])
    assert load_core_profile().preferences.get("居住地") == "深圳"


def test_regex_helper_still_works(isolated_data):
    assert pin_fact_with_regex("我叫王芳")
    assert load_core_profile().name == "王芳"


def test_pin_location_from_utterance(isolated_data):
    from localagent.memory.profile_pin import pin_location_from_utterance

    assert pin_location_from_utterance("深圳") == "深圳"
    assert load_core_profile().preferences.get("居住地") == "深圳"


def test_default_core_profile_does_not_wipe_preferences(isolated_data):
    from localagent.memory.core_profile import CoreProfile, default_core_profile, save_core_profile

    save_core_profile(CoreProfile(preferences={"居住地": "深圳"}, current_status="LocalAgent 用户"))
    profile = default_core_profile()
    assert profile.preferences.get("居住地") == "深圳"


def test_save_core_profile_merges_existing_preferences(isolated_data):
    from localagent.memory.core_profile import CoreProfile, load_core_profile, save_core_profile

    save_core_profile(CoreProfile(preferences={"居住地": "深圳", "职业": "工程师"}))
    # Accidental blank starter must not wipe keys.
    save_core_profile(CoreProfile(current_status="LocalAgent 用户"))
    profile = load_core_profile()
    assert profile.preferences.get("居住地") == "深圳"
    assert profile.preferences.get("职业") == "工程师"


def test_resolve_home_location_from_memory(isolated_data):
    import json
    from datetime import datetime

    from localagent import config
    from localagent.memory.core_profile import home_location, resolve_home_location
    from localagent.memory.store import MemoryFact, get_memory_store

    store = get_memory_store()
    store._facts.append(
        MemoryFact(
            id="mem-home-1",
            text="现居深圳，已婚带俩娃",
            source_file="manual",
            section_heading="session_summary",
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
    )
    store.save()
    config.CORE_PROFILE_FILE.write_text(
        json.dumps(
            {
                "name": "",
                "preferences": {},
                "current_status": "LocalAgent 用户",
                "life_anchors": [],
                "updated_at": "",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert home_location() == ""
    assert resolve_home_location() == "深圳"
    assert home_location() == "深圳"
