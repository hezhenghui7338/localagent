"""Web search helper and multi-provider tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from localagent.tools import augment_web_query, derive_search_params, web_search
from localagent.tools.web_search import (
    classify_result_freshness,
    extract_dates_from_text,
    format_search_output,
    query_recency_mode,
    resolve_web_search_provider,
    search_output_has_freshness_warning,
    today_label,
)


def test_augment_web_query_adds_current_month():
    today = date.today()
    assert f"{today.year}年{today.month:02d}月" in augment_web_query("最近科技新闻")


def test_augment_web_query_today_uses_full_date():
    today = date(2026, 7, 14)
    out = augment_web_query("今天有什么热点新闻", today=today)
    assert "2026年7月14日" in out


def test_inject_home_location_for_weather(isolated_data):
    from localagent.memory.core_profile import CoreProfile, save_core_profile
    from localagent.tools.web_search import inject_home_location_for_weather, prepare_web_query

    save_core_profile(CoreProfile(preferences={"居住地": "深圳"}))
    assert inject_home_location_for_weather("今天天气怎么样?") == "深圳 今天天气怎么样?"
    assert inject_home_location_for_weather("深圳今天天气") == "深圳今天天气"
    assert inject_home_location_for_weather("最近有什么新闻") == "最近有什么新闻"

    prepared = prepare_web_query("今天天气怎么样?", today=date(2026, 7, 14))
    assert prepared.startswith("深圳")
    assert "今天" in prepared
    assert "2026年" not in prepared


def test_weather_query_strips_year_date():
    """Full calendar dates in weather searches pull archives and fail freshness."""
    today = date(2026, 7, 14)
    out = augment_web_query("深圳 2026年7月14日 天气", today=today)
    assert "2026年" not in out
    assert "深圳" in out
    assert "今天" in out

    tomorrow = augment_web_query("明天北京天气怎么样", today=today)
    assert "2026年" not in tomorrow
    assert "明天" in tomorrow
    assert "北京" in tomorrow

    already = augment_web_query("深圳今天天气预报", today=today)
    assert already == "深圳今天天气预报"

def test_inject_home_skips_without_profile(isolated_data):
    from localagent.tools.web_search import inject_home_location_for_weather

    assert inject_home_location_for_weather("今天天气怎么样?") == "今天天气怎么样?"


def test_extract_searchable_query_unwraps_assume_block():
    from localagent.tools.web_search import extract_searchable_query

    wrapped = (
        "[用户问题]\n今天天气怎么样?\n\n"
        "[执行假设（请按此理解推进，并在回复开头用一句话说明假设）]\n"
        "- 按你档案中的居住地「深圳」查询天气"
    )
    assert extract_searchable_query(wrapped) == "今天天气怎么样?"


def test_augment_web_query_tomorrow_uses_next_day():
    today = date(2026, 7, 14)
    out = augment_web_query("明天有什么重要新闻", today=today)
    assert "2026年7月15日" in out
    assert "2026年7月14日" not in out


def test_query_target_date_tomorrow():
    from localagent.tools.web_search import query_target_date

    assert query_target_date("明天北京天气", today=date(2026, 7, 14)) == date(2026, 7, 15)
    assert query_target_date("北京今天天气", today=date(2026, 7, 14)) == date(2026, 7, 14)


def test_augment_web_query_keeps_explicit_year():
    assert augment_web_query("2024年科技新闻") == "2024年科技新闻"


def test_derive_search_params_news_recent():
    opts = derive_search_params("最近有什么新闻")
    assert opts["topic"] == "news"
    assert opts["days"] == 7


def test_derive_search_params_news_today():
    opts = derive_search_params("今天有什么新闻")
    assert opts["topic"] == "news"
    assert opts["days"] == 1


def test_derive_search_params_recent_non_news():
    opts = derive_search_params("最新 AI 进展")
    assert opts["time_range"] == "week"
    assert "topic" not in opts


def test_derive_search_params_current_time():
    opts = derive_search_params("say hi,现在几点了")
    assert opts["time_range"] == "day"
    assert "topic" not in opts


def test_derive_search_params_weather_uses_day():
    opts = derive_search_params("深圳天气预报")
    assert opts["time_range"] == "day"


def test_query_recency_mode_weather():
    assert query_recency_mode("深圳今天天气预报") == "day"


def test_resolve_provider_auto_prefers_tavily(monkeypatch):
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "auto")
    monkeypatch.setattr("localagent.config.TAVILY_API_KEY", "tvly-x")
    monkeypatch.setattr("localagent.config.SEARXNG_URL", "")
    assert resolve_web_search_provider() == "tavily"


def test_resolve_provider_auto_prefers_searxng_without_tavily(monkeypatch):
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "auto")
    monkeypatch.setattr("localagent.config.TAVILY_API_KEY", "")
    monkeypatch.setattr("localagent.config.SEARXNG_URL", "http://localhost:8080")
    assert resolve_web_search_provider() == "searxng"


def test_resolve_provider_auto_falls_back_to_ddgs(monkeypatch):
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "auto")
    monkeypatch.setattr("localagent.config.TAVILY_API_KEY", "")
    monkeypatch.setattr("localagent.config.SEARXNG_URL", "")
    assert resolve_web_search_provider() == "ddgs"


def test_resolve_provider_explicit_ddgs(monkeypatch):
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "ddgs")
    monkeypatch.setattr("localagent.config.TAVILY_API_KEY", "tvly-x")
    assert resolve_web_search_provider() == "ddgs"


def test_extract_dates_from_chinese_and_iso():
    dates = extract_dates_from_text("深圳2026年3月大雨，另见 2026-07-14 预报")
    assert date(2026, 3, 1) in dates
    assert date(2026, 7, 14) in dates


def test_classify_stale_march_weather_in_july():
    today = date(2026, 7, 14)
    label, hit = classify_result_freshness(
        {
            "title": "深圳天气",
            "content": "2026年3月大雨，气温14℃至20℃",
            "url": "https://example.com/weather",
            "published_date": "2026-03-15",
        },
        today=today,
        mode="day",
    )
    assert label == "stale"
    assert hit == date(2026, 3, 15)


def test_classify_fresh_july_weather():
    today = date(2026, 7, 14)
    label, hit = classify_result_freshness(
        {
            "title": "深圳今日天气",
            "content": "2026年7月14日多云，气温28℃至33℃",
            "url": "https://example.com/sz",
            "published_date": "2026-07-14",
        },
        today=today,
        mode="day",
    )
    assert label == "fresh"
    assert hit == date(2026, 7, 14)


def test_format_search_output_rejects_stale_as_current():
    today = date(2026, 7, 14)
    text = format_search_output(
        answer="今日大雨 14-20℃",
        results=[
            {
                "title": "深圳天气",
                "content": "2026年3月大雨，气温14℃至20℃",
                "url": "https://example.com/wx",
                "published_date": "2026-03-15",
            }
        ],
        query="深圳今天天气预报",
        today=today,
    )
    assert "【检索基准日】" in text
    assert today_label(today) in text
    assert "【核对失败】" in text
    assert search_output_has_freshness_warning(text)
    assert "今日大雨" not in text  # stale-derived answer dropped
    assert "过期结果" in text
    assert "禁止把过期结果当作当前事实" in text


def test_format_search_output_keeps_fresh_and_filters_stale():
    today = date(2026, 7, 14)
    text = format_search_output(
        answer="今日多云",
        results=[
            {
                "title": "过期页",
                "content": "2026年3月大雨",
                "url": "https://example.com/old",
                "published_date": "2026-03-01",
            },
            {
                "title": "新页",
                "content": "2026年7月14日多云 30℃",
                "url": "https://example.com/new",
                "published_date": "2026-07-14",
            },
        ],
        query="深圳今天天气",
        today=today,
    )
    assert "摘要: 今日多云" in text
    assert "新页" in text
    assert "【时效警告】" in text
    assert "已过滤的过期结果" in text
    assert "过期页" in text


def test_format_search_output():
    text = format_search_output(
        answer="摘要句",
        results=[
            {
                "title": "标题",
                "content": "正文" * 100,
                "url": "https://example.com",
                "published_date": "2026-07-11",
            }
        ],
        query="最近的新闻",
        today=date(2026, 7, 14),
    )
    assert "摘要: 摘要句" in text
    assert "标题" in text
    assert "2026-07-11" in text
    assert "https://example.com" in text
    assert "来源: 标题" in text
    assert "链接: https://example.com" in text
    assert "【引用要求】" in text
    assert len(text.split("正文")[1]) <= 200 + 40  # truncated content


def test_format_search_output_tomorrow_uses_target_date():
    today = date(2026, 7, 14)
    text = format_search_output(
        results=[
            {
                "title": "北京明日天气",
                "content": "2026年7月15日多云，气温20℃至28℃",
                "url": "https://example.com/bj-tomorrow",
                "published_date": "2026-07-14",
            }
        ],
        query="明天北京天气怎么样",
        today=today,
    )
    assert "【检索基准日】2026年7月15日" in text
    assert "【日历今天】2026年7月14日" in text
    assert "明天/次日" in text
    assert "链接: https://example.com/bj-tomorrow" in text
    assert "【引用要求】" in text


def test_web_search_sends_recency_payload(monkeypatch):
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.setattr("localagent.config.TAVILY_API_KEY", "test-key")
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "answer": "今日要闻摘要",
        "results": [
            {
                "title": "示例新闻",
                "content": "正文",
                "url": "https://example.com",
                "published_date": "2026-07-11",
            }
        ],
    }
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.post.return_value = mock_response

    import importlib

    web_search_mod = importlib.import_module("localagent.tools.web_search")
    with patch.object(web_search_mod.httpx, "Client", return_value=mock_client):
        result = web_search("最近的新闻")

    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["topic"] == "news"
    assert payload["days"] == 7
    assert payload["include_answer"] is True
    today = date.today()
    assert f"{today.year}年{today.month:02d}月" in payload["query"]
    assert "今日要闻摘要" in result
    assert "2026-07-11" in result


def test_web_search_ddgs_text(monkeypatch):
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "ddgs")
    monkeypatch.setattr("localagent.config.TAVILY_API_KEY", "")

    mock_ddgs = MagicMock()
    mock_ddgs.__enter__.return_value = mock_ddgs
    mock_ddgs.text.return_value = [
        {"title": "AI 进展", "href": "https://example.com/ai", "body": "模型发布"},
    ]

    with patch("ddgs.DDGS", return_value=mock_ddgs):
        result = web_search("最新 AI 进展")

    assert "AI 进展" in result
    assert "https://example.com/ai" in result
    assert "模型发布" in result
    kwargs = mock_ddgs.text.call_args.kwargs
    assert kwargs["max_results"] == 5
    assert kwargs.get("timelimit") == "w"


def test_web_search_ddgs_news(monkeypatch):
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "ddgs")
    mock_ddgs = MagicMock()
    mock_ddgs.__enter__.return_value = mock_ddgs
    mock_ddgs.news.return_value = [
        {
            "title": "今日头条",
            "url": "https://example.com/news",
            "body": "要闻内容",
            "date": "2026-07-13",
        },
    ]

    with patch("ddgs.DDGS", return_value=mock_ddgs):
        result = web_search("最近有什么新闻")

    assert "今日头条" in result
    assert "2026-07-13" in result
    mock_ddgs.news.assert_called_once()
    assert mock_ddgs.news.call_args.kwargs.get("timelimit") == "w"


def test_web_search_searxng(monkeypatch):
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr("localagent.config.SEARXNG_URL", "http://searx.local:8080")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {
                "title": "SearX 结果",
                "url": "https://example.com/sx",
                "content": "元搜索摘要",
                "publishedDate": "2026-07-12",
            }
        ],
    }
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.get.return_value = mock_response

    import importlib

    web_search_mod = importlib.import_module("localagent.tools.web_search")
    with patch.object(web_search_mod.httpx, "Client", return_value=mock_client):
        result = web_search("今天有什么新闻")

    assert "SearX 结果" in result
    assert "https://example.com/sx" in result
    call_kwargs = mock_client.get.call_args
    assert call_kwargs.args[0] == "http://searx.local:8080/search"
    params = call_kwargs.kwargs["params"]
    assert params["format"] == "json"
    assert params["categories"] == "news"
    assert params["time_range"] == "day"


def test_web_search_tavily_missing_key(monkeypatch):
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.setattr("localagent.config.TAVILY_API_KEY", "")
    result = web_search("hello")
    assert result.startswith("联网搜索未配置")
    assert "TAVILY_API_KEY" in result


def test_weather_search_unusable_detects_junk_and_failure():
    from localagent.tools.web_search import weather_search_unusable

    assert weather_search_unusable("【核对失败】没有匹配")
    assert weather_search_unusable(
        "【时效警告】\n- [日期未知] 歌词_今天天气怎么样.pdf: 儿歌"
    )
    assert not weather_search_unusable(
        "【时效核对】匹配 1 条\n- [匹配·2026-07-14] 深圳今日天气: 多云 28°C"
    )


def test_weather_retry_queries_include_forecast(isolated_data):
    from localagent.memory.core_profile import CoreProfile, save_core_profile
    from localagent.tools.web_search import weather_retry_queries

    save_core_profile(CoreProfile(preferences={"居住地": "深圳"}))
    alts = weather_retry_queries("今天天气怎么样?")
    assert any("深圳" in q and "天气预报" in q for q in alts)


def test_web_search_retries_unusable_weather(monkeypatch, isolated_data):
    from localagent.memory.core_profile import CoreProfile, save_core_profile

    save_core_profile(CoreProfile(preferences={"居住地": "深圳"}))
    monkeypatch.setattr("localagent.config.WEB_SEARCH_PROVIDER", "ddgs")

    bad = (
        "【检索基准日】2026年7月14日\n"
        "【核对失败】没有与检索基准日相符的结果。\n"
        "- [过期] 歌词_今天天气怎么样.pdf: 教学资源"
    )
    good = (
        "【检索基准日】2026年7月14日\n"
        "【时效核对】匹配 1 条 / 过期 0 条 / 日期未知 0 条\n"
        "- [匹配·2026-07-14] 深圳今天天气预报: 多云 28°C\n"
        "  链接: https://example.com/sz-weather"
    )
    calls: list[str] = []

    def fake_once(query: str, *, max_results: int = 5) -> str:
        calls.append(query)
        if len(calls) == 1:
            return bad
        return good

    with patch("localagent.tools.web_search._web_search_once", side_effect=fake_once):
        result = web_search("今天天气怎么样?")

    assert "深圳今天天气预报" in result or "多云" in result
    assert len(calls) >= 2
    assert "核对失败" not in result
