"""Tests for news sniff (RSS sync, rank, brief links, notify, schedule helpers)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from localagent.news.brief import build_brief, format_brief
from localagent.news.links import format_article_link_block, hyperlink
from localagent.news.mark import mark_article
from localagent.news.notify import (
    maybe_print_news_ready,
    news_ready_message,
    past_sync_time,
    should_notify_news_ready,
)
from localagent.news.profile import NewsProfile, load_news_profile, save_news_profile
from localagent.news.rank import rank_articles
from localagent.news.rss import parse_feed
from localagent.news.store import (
    Article,
    NewsStore,
    article_id_for_url,
    mark_ready_notified,
    mark_sync_success,
    normalize_url,
    ready_already_notified,
    today_synced,
)
from localagent.news.sync import sync_news


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>BestBlogs AI</title>
    <item>
      <title>Claude Agent 工程实践</title>
      <link>https://example.com/claude-agent</link>
      <description>一句话：本地 Agent 如何编排工具与记忆。评分 92</description>
      <author>Alice</author>
      <pubDate>Thu, 16 Jul 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>招聘：AI 工程师</title>
      <link>https://example.com/job-ai</link>
      <description>急招广告</description>
      <pubDate>Thu, 16 Jul 2026 11:00:00 GMT</pubDate>
    </item>
    <item>
      <title>RAG 评测新基准</title>
      <link>https://example.com/rag-bench/</link>
      <description>介绍 RTEB 与检索质量。</description>
      <pubDate>Wed, 15 Jul 2026 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
""".encode("utf-8")


def test_normalize_url_strips_tracking_and_slash():
    assert normalize_url("https://Example.com/a/b/?utm_source=x&id=1") == (
        "https://example.com/a/b?id=1"
    )
    assert article_id_for_url("https://example.com/a") == article_id_for_url(
        "https://example.com/a/"
    )


def test_parse_feed_extracts_items():
    items = parse_feed(SAMPLE_RSS)
    assert len(items) == 3
    assert items[0].title.startswith("Claude")
    assert items[0].url == "https://example.com/claude-agent"
    assert items[0].score_hint == 92.0


def test_sync_upserts_and_dedups(isolated_data, monkeypatch):
    monkeypatch.setattr(
        "localagent.news.sync.fetch_feed_bytes",
        lambda url, timeout=30.0: SAMPLE_RSS,
    )
    store = NewsStore()
    r1 = sync_news(rss_url="https://example.com/feed", store=store)
    assert r1.ok
    assert r1.fetched == 3
    assert r1.inserted == 3
    r2 = sync_news(rss_url="https://example.com/feed", store=store)
    assert r2.ok
    assert r2.inserted == 0
    assert r2.updated == 3
    assert today_synced()


def test_rank_prefers_interests_and_mutes_jobs(isolated_data):
    profile = NewsProfile(
        interests=["Agent", "RAG"],
        boost_keywords=["Claude"],
        mute_keywords=["招聘"],
        daily_brief_size=10,
    )
    articles = [
        Article(
            id="n1",
            source_id="t",
            url="https://example.com/a",
            title="Claude Agent 工程",
            rss_summary="工具编排",
            published_at="2026-07-16T10:00:00Z",
        ),
        Article(
            id="n2",
            source_id="t",
            url="https://example.com/b",
            title="招聘：AI 工程师",
            rss_summary="广告",
            published_at="2026-07-16T11:00:00Z",
        ),
        Article(
            id="n3",
            source_id="t",
            url="https://example.com/c",
            title="无关天气",
            rss_summary="晴",
            published_at="2026-07-10T10:00:00Z",
        ),
    ]
    ranked = rank_articles(articles, profile=profile, limit=5)
    ids = [r.article.id for r in ranked]
    assert "n2" not in ids
    assert ids[0] == "n1"


def test_brief_contains_clickable_urls(isolated_data, monkeypatch):
    monkeypatch.setattr(
        "localagent.news.sync.fetch_feed_bytes",
        lambda url, timeout=30.0: SAMPLE_RSS,
    )
    store = NewsStore()
    sync_news(store=store)
    text, ranked = build_brief(store=store, plain_links=True, limit=5)
    assert "https://example.com/claude-agent" in text
    assert "原文:" in text
    assert ranked
    # muted job should not dominate
    assert all("招聘" not in r.article.title for r in ranked)


def test_hyperlink_plain_and_osc8():
    plain = hyperlink("标题", "https://example.com/x", force_plain=True)
    assert plain == "[标题](https://example.com/x)"
    block = format_article_link_block(
        title="T", url="https://example.com/x", plain=True
    )
    assert "https://example.com/x" in block


def test_mark_skip_adds_mute(isolated_data):
    store = NewsStore()
    art = Article(
        id=article_id_for_url("https://example.com/skip-me"),
        source_id="t",
        url="https://example.com/skip-me",
        title="广告Spam 内容",
    )
    store.upsert_article(art)
    got, msg = mark_article(art.id, "skip", store=store)
    assert got and got.status == "skipped"
    assert "跳过" in msg
    profile = load_news_profile()
    assert any(k for k in profile.mute_keywords)


def test_notify_once_per_day(isolated_data, capsys):
    mark_sync_success(count=3, source_url="https://example.com/feed")
    now = datetime(2026, 7, 17, 9, 0, 0)
    assert past_sync_time(now=now)
    assert should_notify_news_ready(now=now)
    assert maybe_print_news_ready(now=now) is True
    out = capsys.readouterr().out
    assert "今日更新已准备好" in out
    assert news_ready_message() in out
    assert ready_already_notified()
    assert maybe_print_news_ready(now=now) is False


def test_notify_before_sync_hour_silent(isolated_data):
    mark_sync_success(count=1, source_url="https://example.com/feed")
    early = datetime(2026, 7, 17, 7, 0, 0)
    assert not should_notify_news_ready(now=early)


def test_schedule_plist_body_contains_hour():
    from localagent.news.schedule import _plist_body

    body = _plist_body(hour=8, minute=0, la_bin="/usr/local/bin/la")
    assert "<integer>8</integer>" in body
    assert "news" in body
    assert "sync" in body


def test_cli_news_brief_smoke(isolated_data, monkeypatch):
    from localagent.cli import build_parser

    monkeypatch.setattr(
        "localagent.news.sync.fetch_feed_bytes",
        lambda url, timeout=30.0: SAMPLE_RSS,
    )
    parser = build_parser()
    args = parser.parse_args(["news", "sync"])
    assert args.func(args) == 0
    args = parser.parse_args(["news", "brief", "--no-ui", "--plain", "--limit", "5"])
    assert args.func(args) == 0


def test_format_brief_empty():
    text = format_brief([], brief_date="2026-07-17", plain_links=True)
    assert "暂无条目" in text


def test_nav_move_and_remove():
    from localagent.news.nav import BriefNavState
    from localagent.news.rank import RankedArticle

    items = [
        RankedArticle(
            article=Article(id="a", source_id="t", url="https://a.example", title="A"),
            score=1,
            reasons=["x"],
        ),
        RankedArticle(
            article=Article(id="b", source_id="t", url="https://b.example", title="B"),
            score=2,
            reasons=["y"],
        ),
        RankedArticle(
            article=Article(id="c", source_id="t", url="https://c.example", title="C"),
            score=3,
            reasons=["z"],
        ),
    ]
    state = BriefNavState(items=items, day="2026-07-17")
    assert state.position_label() == "1/3"
    state.move(1)
    assert state.current().article.id == "b"
    state.move(-1)
    assert state.current().article.id == "a"
    state.move(-1)  # wrap
    assert state.current().article.id == "c"
    removed = state.remove_current()
    assert removed and removed.article.id == "c"
    assert state.total == 2


def test_render_browser_shows_current_only():
    from localagent.news.browser import render_browser_text
    from localagent.news.nav import BriefNavState
    from localagent.news.rank import RankedArticle

    items = [
        RankedArticle(
            article=Article(
                id="a",
                source_id="t",
                url="https://a.example/x",
                title="标题甲",
                rss_summary="摘要甲很长" * 5,
            ),
            score=1,
            reasons=["兴趣:Agent"],
        ),
        RankedArticle(
            article=Article(
                id="b",
                source_id="t",
                url="https://b.example/y",
                title="标题乙",
                rss_summary="摘要乙",
            ),
            score=1,
            reasons=["默认"],
        ),
    ]
    state = BriefNavState(items=items, day="2026-07-17")
    text = render_browser_text(state, plain_links=True)
    assert "标题甲" in text
    assert "https://a.example/x" in text
    assert "1/2" in text
    assert "键位" in text


def test_open_in_browser_mocked(monkeypatch):
    from localagent.news import open_url

    called: list[str] = []

    monkeypatch.setattr(
        open_url.webbrowser,
        "open",
        lambda url, new=2: called.append(url) or True,
    )
    assert open_url.open_in_browser("https://example.com/z") is True
    assert called == ["https://example.com/z"]
    assert open_url.open_in_browser("") is False


def test_read_result_to_summarize(isolated_data, tmp_path):
    from localagent.news.chat_bridge import read_result_to_summarize
    from localagent.news.read import ReadResult

    cache = tmp_path / "n_test.md"
    cache.write_text("# Hello\n\nbody text here", encoding="utf-8")
    art = Article(
        id="n_test",
        source_id="t",
        url="https://example.com/hello",
        title="Hello",
        fetched_text_path=str(cache),
    )
    result = ReadResult(
        markdown="## 总结\n一句话。\n",
        article=art,
        warnings=[],
    )
    summary = read_result_to_summarize(result)
    assert summary.filename == "Hello"
    assert "一句话" in summary.markdown
    assert "body text" in summary.annotated_text


def test_should_enter_news_browser(monkeypatch):
    from localagent.news.browser import should_enter_news_browser

    assert should_enter_news_browser(no_ui=True) is False
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert should_enter_news_browser(no_ui=False) is True
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert should_enter_news_browser(no_ui=False) is False


def test_cmd_brief_enters_browser_when_tty(isolated_data, monkeypatch):
    from localagent.cli import build_parser
    import localagent.news.browser as browser_mod

    monkeypatch.setattr(
        "localagent.news.sync.fetch_feed_bytes",
        lambda url, timeout=30.0: SAMPLE_RSS,
    )
    called: dict[str, object] = {}

    def fake_run(ranked, *, day="", provider="auto", store=None):
        called["n"] = len(ranked)
        called["day"] = day
        return 0

    monkeypatch.setattr(browser_mod, "run_news_browser", fake_run)
    monkeypatch.setattr(
        browser_mod, "should_enter_news_browser", lambda *, no_ui: not no_ui
    )

    parser = build_parser()
    assert parser.parse_args(["news", "sync"]).func(
        parser.parse_args(["news", "sync"])
    ) == 0
    args = parser.parse_args(["news", "brief", "--limit", "3"])
    assert args.func(args) == 0
    assert called.get("n", 0) >= 1

    # --no-ui must dump, not enter browser
    called.clear()
    args = parser.parse_args(["news", "brief", "--no-ui", "--limit", "3"])
    assert args.func(args) == 0
    assert "n" not in called
