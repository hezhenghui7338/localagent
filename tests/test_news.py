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


def test_brief_size_env_overrides_persisted_profile(isolated_data, monkeypatch):
    """LA_NEWS_BRIEF_SIZE must win over news_profile.json (saved on mute/schedule)."""
    monkeypatch.delenv("LA_NEWS_BRIEF_SIZE", raising=False)
    profile = load_news_profile()
    profile.daily_brief_size = 15
    save_news_profile(profile)
    assert load_news_profile().daily_brief_size == 15

    monkeypatch.setenv("LA_NEWS_BRIEF_SIZE", "30")
    assert load_news_profile().daily_brief_size == 30


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
    assert "滚动" in text
    # Title must not be a markdown link; URL only in footer.
    assert "](https://" not in text
    assert "【当前】标题甲" in text
    assert "一句话:" not in text
    assert text.index("标题甲") < text.index("https://a.example/x")
    assert "入选  兴趣:Agent" in text
    assert "编号  a" in text
    assert "原文  https://a.example/x" in text


def test_parse_bestblogs_rss_summary():
    from localagent.news.summary_parse import parse_rss_summary

    raw = (
        "📌 一句话摘要 这是一句话总结。 "
        "📝 详细摘要 这是详细摘要的第一句。这是第二句补充说明。 "
        "💡 主要观点 短观点甲。 "
        "这是对观点甲的较长阐述，用来解释背景与因果，并且字数明显超过观点本身很多。 "
        "短观点乙。 "
        "这是对观点乙的较长阐述内容，同样比观点标题更长也更详细一些，便于配对。 "
        "💬 文章金句 金句一。 金句二。 "
        "📊 文章信息 AI 初评： 88 来源： 量子位 作者： 闻乐 "
        "分类： 人工智能 语言： 中文 阅读时间： 16 分钟 字数： 3923 阅读完整文章"
    )
    parsed = parse_rss_summary(raw)
    assert parsed.one_liner == "这是一句话总结。"
    assert "详细摘要的第一句" in parsed.detail
    assert "阅读完整文章" not in parsed.detail
    assert len(parsed.viewpoints) == 2
    assert parsed.viewpoints[0].startswith("短观点甲")
    assert "较长阐述" in parsed.viewpoint_notes[0]
    assert parsed.quotes[0].startswith("金句一")
    assert parsed.meta["ai_score"] == "88"
    assert parsed.meta["source"] == "量子位"
    assert parsed.meta["read_mins"] == "16"


def test_display_summary_is_one_liner_only():
    art = Article(
        id="x",
        source_id="t",
        url="https://x.example",
        title="T",
        rss_summary=(
            "📌 一句话摘要 只看这一句。 "
            "📝 详细摘要 后面大段详细内容不该出现在一句话里。"
        ),
    )
    assert art.display_summary() == "只看这一句。"
    assert "详细内容" not in art.display_summary()
    assert "详细内容" in art.resolved_detail()


def test_format_article_detail_and_skim_layout():
    from localagent.news.brief import format_article_detail, format_skim_card

    art = Article(
        id="n_demo",
        source_id="t",
        url="https://example.com/a",
        title="演示标题",
        published_at="2026-07-16T10:00:00Z",
        rss_summary=(
            "📌 一句话摘要 核心结论一句话。 "
            "📝 详细摘要 " + ("详细段落内容填充。" * 50) + " "
            "💡 主要观点 观点一。 "
            "观点一的详细展开说明明显更长一些，用来补充论证与背景材料。 "
            "观点二。 "
            "观点二的详细展开说明也明显更长一些，继续补充更多上下文。 "
            "📊 文章信息 AI 初评： 90 来源： 测试源 阅读时间： 5 分钟"
        ),
    )
    summary = format_article_detail(art, mode="summary", reasons=["兴趣:RAG", "加权:Agent"])
    assert summary.startswith("【当前】演示标题")
    assert "](https://" not in summary
    assert "# " not in summary
    assert "## " not in summary
    assert "核心结论一句话" in summary
    assert "详细摘要" in summary
    assert "主要观点" in summary
    assert "入选  兴趣:RAG · 加权:Agent" in summary
    assert "AI初评 90" in summary
    assert summary.strip().endswith("原文  https://example.com/a")
    # Truncated in summary mode
    assert "…" in summary
    assert summary.count("详细段落内容填充。") < 50

    skim = format_skim_card(art, reasons=["兴趣:RAG"])
    assert skim.startswith("【速读】演示标题")
    assert "# 速读" not in skim
    assert "## " not in skim
    assert "精读:" not in skim
    assert "核心结论一句话" in skim
    assert skim.count("详细段落内容填充。") >= 40
    assert "观点一的详细展开" in skim
    assert skim.strip().endswith("原文  https://example.com/a")


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


def test_run_news_browser_read_uses_activity_indicator(isolated_data, monkeypatch, capsys):
    """Pressing r must construct ActivityIndicator(prefix, message) and enter deep-chat."""
    from localagent.news.browser import run_news_browser
    from localagent.news.rank import RankedArticle
    from localagent.news.read import ReadResult
    import localagent.news.browser as browser_mod
    import localagent.ui.console as console_mod

    art = Article(
        id="n_read_test",
        source_id="t",
        url="https://example.com/read-me",
        title="精读测试文",
        rss_summary="摘要",
    )
    store = NewsStore()
    store.upsert_article(art)
    ranked = [
        RankedArticle(article=art, score=1.0, reasons=["兴趣:Agent"]),
    ]

    actions = iter(["read", "quit"])
    monkeypatch.setattr(
        browser_mod,
        "_run_one_session",
        lambda state, store=None: next(actions),
    )

    ai_calls: list[tuple[str, str]] = []
    real_ai = console_mod.ActivityIndicator

    class TrackingAI(real_ai):
        def __init__(self, prefix: str, message: str) -> None:
            ai_calls.append((prefix, message))
            super().__init__(prefix, message)

    monkeypatch.setattr(console_mod, "ActivityIndicator", TrackingAI)

    read_calls: list[str] = []
    chat_calls: list[str] = []

    def fake_read(id_or_url, **kwargs):
        read_calls.append(id_or_url)
        return ReadResult(
            markdown="## 总结\n一句话精读。\n",
            article=store.get(art.id) or art,
            warnings=[],
        )

    def fake_chat(result, *, provider="auto"):
        chat_calls.append(result.article.id)
        return 0

    monkeypatch.setattr("localagent.news.read.read_article", fake_read)
    monkeypatch.setattr("localagent.news.chat_bridge.run_article_chat", fake_chat)

    assert run_news_browser(ranked, day="2026-07-17", store=store) == 0
    assert read_calls == ["n_read_test"]
    assert chat_calls == ["n_read_test"]
    assert ai_calls == [("news", "抓取并总结原文…")]
    out = capsys.readouterr().out
    assert "精读: 精读测试文" in out
    assert "已返回简报浏览器" in out


def test_cli_news_skim_and_read(isolated_data, monkeypatch, capsys):
    from localagent.cli import build_parser
    from localagent.news.read import ReadResult

    monkeypatch.setattr(
        "localagent.news.sync.fetch_feed_bytes",
        lambda url, timeout=30.0: SAMPLE_RSS,
    )
    parser = build_parser()
    assert parser.parse_args(["news", "sync"]).func(
        parser.parse_args(["news", "sync"])
    ) == 0

    store = NewsStore()
    arts = store.list_recent(limit=10)
    assert arts
    art = next(a for a in arts if "Claude" in a.title)

    args = parser.parse_args(["news", "skim", art.id, "--plain"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert art.title.split()[0] in out or "Claude" in out
    refreshed = store.get(art.id)
    assert refreshed and refreshed.status == "skimmed"

    def fake_read(target, **kwargs):
        return ReadResult(
            markdown="## 总结\nCLI 精读卡\n",
            article=store.get(art.id) or art,
        )

    monkeypatch.setattr("localagent.news.commands.read_article", fake_read)
    args = parser.parse_args(["news", "read", art.id, "--heuristic", "--plain"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "CLI 精读卡" in out

    args = parser.parse_args(["news", "read", "missing-id-xyz", "--heuristic"])
    monkeypatch.setattr(
        "localagent.news.commands.read_article",
        lambda *a, **k: ReadResult(
            markdown="",
            article=Article(id="", source_id="", url=""),
            error="未找到文章: missing-id-xyz",
        ),
    )
    assert args.func(args) == 1
    out = capsys.readouterr().out
    assert "read 失败" in out


def test_cli_news_mark_interests_status_sources(isolated_data, monkeypatch, capsys):
    from localagent.cli import build_parser

    monkeypatch.setattr(
        "localagent.news.sync.fetch_feed_bytes",
        lambda url, timeout=30.0: SAMPLE_RSS,
    )
    parser = build_parser()
    assert parser.parse_args(["news", "sync"]).func(
        parser.parse_args(["news", "sync"])
    ) == 0
    store = NewsStore()
    art = store.list_recent(limit=1)[0]

    args = parser.parse_args(["news", "mark", art.id, "bookmark"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "[news]" in out
    assert store.get(art.id).status == "bookmarked"

    args = parser.parse_args(["news", "interests", "--add", "Agent"])
    assert args.func(args) == 0
    profile = load_news_profile()
    assert "Agent" in profile.interests

    args = parser.parse_args(["news", "interests", "--mute", "招聘"])
    assert args.func(args) == 0
    profile = load_news_profile()
    assert "招聘" in profile.mute_keywords

    args = parser.parse_args(["news", "status"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "上次 sync" in out or "RSS" in out

    args = parser.parse_args(["news", "sources"])
    assert args.func(args) == 0
    out = capsys.readouterr().out
    assert "BestBlogs" in out or "RSS" in out


def test_body_quality_ok_and_extract_origin_urls():
    from localagent.news.fetch import body_quality_ok, extract_origin_urls

    assert body_quality_ok("短") is False
    assert body_quality_ok("字" * 600) is True
    assert body_quality_ok("字" * 200, expected_word_count=2000) is False

    html = """
    <html><body>
      <a href="/about">关于</a>
      <a href="https://mp.weixin.qq.com/s/abc123">阅读原文</a>
      <a href="https://www.bestblogs.dev/article/x">本站</a>
    </body></html>
    """
    urls = extract_origin_urls(
        html, page_url="https://www.bestblogs.dev/article/72ea7f2efd"
    )
    assert any("weixin" in u for u in urls)
    assert not any("bestblogs.dev" in u for u in urls)


def test_fetch_article_falls_back_to_origin(monkeypatch):
    from localagent.news import fetch as fetch_mod

    html_agg = (
        "<html><body><p>短导语</p>"
        '<a href="https://publisher.example.com/full/post">阅读原文</a>'
        "</body></html>"
    )
    html_origin = "<html><body><article>" + ("完整正文段落。" * 80) + "</article></body></html>"

    def fake_download(url, *, timeout):
        if "bestblogs" in url:
            return url, html_agg
        if "publisher.example.com" in url:
            return url, html_origin
        raise AssertionError(url)

    monkeypatch.setattr(fetch_mod, "_download_html", fake_download)
    monkeypatch.setattr(fetch_mod.config, "NEWS_FETCH_USE_JINA", False)
    monkeypatch.setattr(fetch_mod.config, "NEWS_FETCH_MIN_CHARS", 500)

    def fake_extract(html, *, url):
        if "publisher" in url:
            return "Full Title", "完整正文段落。" * 80
        return "Teaser", "短导语而已"

    monkeypatch.setattr(fetch_mod, "_extract_with_trafilatura", fake_extract)

    result = fetch_mod.fetch_article("https://www.bestblogs.dev/article/x")
    assert result.ok
    assert result.strategy == "origin"
    assert "完整正文" in result.text
    assert any("原文站" in w for w in result.warnings)


def test_extract_origin_urls_skips_schema_org():
    from localagent.news.fetch import extract_origin_urls

    html = """
    <html><body>
      <a href="https://schema.org">Schema</a>
      <a href="https://mp.weixin.qq.com/s/abc123">阅读原文</a>
    </body></html>
    """
    urls = extract_origin_urls(
        html, page_url="https://www.bestblogs.dev/article/72ea7f2efd"
    )
    assert any("weixin" in u for u in urls)
    assert not any("schema.org" in u for u in urls)


def test_read_article_refetches_short_cache(isolated_data, monkeypatch):
    from localagent.news.read import read_article
    from localagent.news.store import Article, NewsStore
    from localagent.summarize.document import SummarizeResult
    from localagent import config

    store = NewsStore()
    art = Article(
        id="n_shortcache",
        source_id="t",
        url="https://example.com/long-article",
        title="Long",
        rss_summary=(
            "📌 一句话摘要 导语。 📝 详细摘要 这是较长的 RSS 详细摘要内容。"
            " 📊 文章信息 字数：3000"
        ),
    )
    store.upsert_article(art)
    cache = config.NEWS_CACHE_DIR / f"{art.id}.md"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        "# Long\n\n来源: https://example.com/long-article\n\n短",
        encoding="utf-8",
    )

    calls: list[str] = []

    def fake_fetch(url, *, expected_word_count=None, origin_hints=None, timeout=45.0):
        calls.append(url)
        from localagent.news.fetch import FetchResult

        return FetchResult(
            url=url,
            title="Long",
            text=("正文内容。" * 100),
            strategy="direct",
        )

    def fake_summarize(doc, use_llm=True, allow_long=False):
        return SummarizeResult(
            markdown=(
                "## 总结（最多三句话）\n一句话。\n\n"
                "## 结构化要点\n- **点**：x — 依据：〔§全文〕\n"
            ),
            path=cache,
            filename=f"{art.id}.md",
            char_count=len(doc.text or ""),
            annotated_text=doc.text or "",
            used_llm=False,
        )

    monkeypatch.setattr("localagent.news.read.fetch_article", fake_fetch)
    monkeypatch.setattr("localagent.news.read.summarize_loaded", fake_summarize)
    monkeypatch.setattr(
        "localagent.summarize.session_index.index_document_session",
        lambda *a, **k: 1,
    )

    result = read_article(art.id, use_llm=False, store=store)
    assert not result.error
    assert calls, "short cache should trigger refetch"
    assert "缓存正文过短" in "；".join(result.warnings or [])
    assert result.session_source_key == f"news:{art.id}"
