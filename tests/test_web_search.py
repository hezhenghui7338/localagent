"""Web search helper and Tavily payload tests."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from localagent.tools import augment_web_query, derive_search_params, web_search


def test_augment_web_query_adds_current_month():
    today = date.today()
    assert today.strftime("%Y年%m月") in augment_web_query("最近科技新闻")


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


def test_web_search_sends_recency_payload(monkeypatch):
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

    with patch("localagent.tools.httpx.Client", return_value=mock_client):
        result = web_search("最近的新闻")

    payload = mock_client.post.call_args.kwargs["json"]
    assert payload["topic"] == "news"
    assert payload["days"] == 7
    assert payload["include_answer"] is True
    assert date.today().strftime("%Y年%m月") in payload["query"]
    assert "今日要闻摘要" in result
    assert "2026-07-11" in result
