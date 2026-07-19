"""Evening postscript tone: late-hour closing line."""

from __future__ import annotations

from datetime import datetime, timezone

from localagent.i18n import reset_lang_cache
from localagent.tone import (
    evening_active,
    evening_enabled,
    evening_late,
    evening_postscript_block,
)


def _local(hour: int, *, minute: int = 0) -> datetime:
    """Build a timezone-aware datetime at the given local hour today."""
    tz = datetime.now().astimezone().tzinfo or timezone.utc
    now = datetime.now(tz)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def test_evening_late_default_window(monkeypatch):
    monkeypatch.setattr("localagent.config.TONE_EVENING_START", 23)
    monkeypatch.setattr("localagent.config.TONE_EVENING_END", 6)
    assert evening_late(_local(23)) is True
    assert evening_late(_local(2)) is True
    assert evening_late(_local(5, minute=59)) is True
    assert evening_late(_local(6)) is False
    assert evening_late(_local(10)) is False
    assert evening_late(_local(22)) is False


def test_evening_late_same_start_end_never(monkeypatch):
    monkeypatch.setattr("localagent.config.TONE_EVENING_START", 8)
    monkeypatch.setattr("localagent.config.TONE_EVENING_END", 8)
    assert evening_late(_local(8)) is False
    assert evening_late(_local(0)) is False


def test_evening_late_non_wrapping_window(monkeypatch):
    monkeypatch.setattr("localagent.config.TONE_EVENING_START", 21)
    monkeypatch.setattr("localagent.config.TONE_EVENING_END", 23)
    assert evening_late(_local(21)) is True
    assert evening_late(_local(22)) is True
    assert evening_late(_local(23)) is False
    assert evening_late(_local(1)) is False


def test_evening_enabled(monkeypatch):
    monkeypatch.setattr("localagent.config.TONE_EVENING", "off")
    assert evening_enabled() is False
    monkeypatch.setattr("localagent.config.TONE_EVENING", "on")
    assert evening_enabled() is True
    monkeypatch.setattr("localagent.config.TONE_EVENING", "1")
    assert evening_enabled() is True


def test_postscript_empty_when_off(monkeypatch):
    monkeypatch.setattr("localagent.config.TONE_EVENING", "off")
    monkeypatch.setattr("localagent.config.TONE_EVENING_START", 23)
    monkeypatch.setattr("localagent.config.TONE_EVENING_END", 6)
    assert evening_postscript_block(now=_local(23)) == ""
    assert evening_active(now=_local(23)) is False


def test_postscript_chat_zh_when_late(monkeypatch):
    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    monkeypatch.setattr("localagent.config.TONE_EVENING", "on")
    monkeypatch.setattr("localagent.config.TONE_EVENING_START", 23)
    monkeypatch.setattr("localagent.config.TONE_EVENING_END", 6)
    block = evening_postscript_block(surface="chat", now=_local(23, minute=30))
    assert "夜深收束" in block
    assert "早点休息哦" in block
    assert "不要加" in block
    assert evening_postscript_block(surface="chat", now=_local(10)) == ""


def test_postscript_aware_en_when_late(monkeypatch):
    monkeypatch.setenv("LA_LANG", "en")
    reset_lang_cache()
    monkeypatch.setattr("localagent.config.TONE_EVENING", "on")
    monkeypatch.setattr("localagent.config.TONE_EVENING_START", 23)
    monkeypatch.setattr("localagent.config.TONE_EVENING_END", 6)
    block = evening_postscript_block(surface="aware", now=_local(1))
    assert "Late-night closing" in block
    assert "wrapping up for rest" in block


def test_build_system_prompt_injects_evening(monkeypatch):
    from localagent.agent.runtime import _build_system_prompt
    from localagent.i18n import reset_lang_cache

    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    monkeypatch.setattr("localagent.config.TONE_EVENING", "on")
    monkeypatch.setattr("localagent.tone.evening_late", lambda now=None: True)
    prompt = _build_system_prompt()
    assert "夜深收束" in prompt
    assert "早点休息哦" in prompt

    monkeypatch.setattr("localagent.config.TONE_EVENING", "off")
    prompt_off = _build_system_prompt()
    assert "夜深收束" not in prompt_off


def test_build_system_prompt_no_evening_by_default(monkeypatch):
    from localagent.agent.runtime import _build_system_prompt
    from localagent.i18n import reset_lang_cache

    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    monkeypatch.setattr("localagent.config.TONE_EVENING", "off")
    monkeypatch.setattr("localagent.tone.evening_late", lambda now=None: True)
    prompt = _build_system_prompt()
    assert "夜深收束" not in prompt
