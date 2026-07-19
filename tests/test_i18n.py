"""Language resolution and message catalog."""

from __future__ import annotations

import localagent.i18n as i18n
from localagent.i18n import default_news_rss_url, reset_lang_cache, resolve_lang, t


def test_resolve_lang_explicit_en(monkeypatch):
    monkeypatch.setenv("LA_LANG", "en")
    reset_lang_cache()
    assert resolve_lang() == "en"


def test_resolve_lang_explicit_zh(monkeypatch):
    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    assert resolve_lang() == "zh"


def test_resolve_lang_auto_follows_lang_env(monkeypatch):
    monkeypatch.setenv("LA_LANG", "auto")
    monkeypatch.setenv("LC_ALL", "")
    monkeypatch.setenv("LC_MESSAGES", "")
    monkeypatch.setenv("LANG", "zh_CN.UTF-8")
    reset_lang_cache()
    assert resolve_lang() == "zh"

    monkeypatch.setenv("LANG", "en_US.UTF-8")
    reset_lang_cache()
    assert resolve_lang() == "en"


def test_resolve_lang_c_locale_falls_back_to_en(monkeypatch):
    monkeypatch.delenv("LA_LANG", raising=False)
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.setenv("LC_MESSAGES", "C")
    monkeypatch.setenv("LANG", "C")
    monkeypatch.setattr(i18n.locale, "getlocale", lambda: (None, None))
    reset_lang_cache()
    assert resolve_lang() == "en"


def test_t_english_banner_not_chinese(monkeypatch):
    monkeypatch.setenv("LA_LANG", "en")
    reset_lang_cache()
    text = t("banner.tips_title")
    assert text == "Getting started"
    assert "入门" not in text


def test_t_chinese_banner(monkeypatch):
    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    assert t("banner.tips_title") == "入门提示"


def test_default_news_rss_url_by_lang():
    assert "/zh/" in default_news_rss_url("zh")
    assert "/en/" in default_news_rss_url("en")


def test_t_english_daily_and_chat_status_no_chinese(monkeypatch):
    monkeypatch.setenv("LA_LANG", "en")
    reset_lang_cache()
    assert "新闻" not in t("daily.news_unsynced")
    assert t("daily.news_unsynced") == "today's news not synced"
    assert "连接" not in t("chat.status_connecting", hint="auto")
    assert "Connecting model" in t("chat.status_connecting", hint="auto")
    assert "Generating reply" in t("chat.status_generate")
    assert "Detected" in t(
        "ollama.ram_choose", ram="16 GB", model="qwen3.5:4b", label="Recommended", size="~3.4 GB"
    )


def test_t_english_aware_chrome_no_chinese(monkeypatch):
    monkeypatch.setenv("LA_LANG", "en")
    reset_lang_cache()
    assert t("aware.title_overview") == "LocalAgent · Aware · Overview"
    assert "概览" not in t("aware.title_overview")
    assert "主注意力" not in t("aware.section_focus")
    assert t("aware.section_focus") == "Primary focus"
    assert "傍晚" not in t("aware.period_evening")
    assert t("aware.period_evening") == "evening"
    assert "今日" not in t("aware.input_active", minutes=12)


def test_t_english_news_memory_keys(monkeypatch):
    monkeypatch.setenv("LA_LANG", "en")
    reset_lang_cache()
    # Keys added in wave2 — must resolve without falling back to the raw key name.
    for key in (
        "news.brief_title",
        "memory.status_title",
        "workspace.added",
        "summarize.entered",
        "polish.tag_primary",
    ):
        text = t(key)
        assert text != key, key
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in text), (key, text)


def test_H_helper_follows_lang(monkeypatch):
    from localagent.i18n import H

    monkeypatch.setenv("LA_LANG", "en")
    reset_lang_cache()
    assert H("命令", "commands") == "commands"
    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    assert H("命令", "commands") == "命令"


def test_render_summary_view_english_chrome(monkeypatch, isolated_data):
    monkeypatch.setenv("LA_LANG", "en")
    reset_lang_cache()
    from localagent.aware.summary import render_summary_view

    text = render_summary_view(mode="now", use_llm=False)
    for token in ("概览", "主注意力", "当前状态", "傍晚", "今日输入活跃", "已授权", "提示:"):
        assert token not in text, token
    assert "Overview" in text
    assert "Primary focus" in text
    assert "Current state" in text
    assert "System" in text
