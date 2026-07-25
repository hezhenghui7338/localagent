"""Tests for session-recall and Cold archive-recall query detection."""

from unittest.mock import MagicMock, patch

from localagent.agent.runtime import (
    _prefetch_archive_context,
    archive_search_query,
    archive_time_window,
    is_archive_recall_query,
    is_last_session_recall_query,
    is_session_recall_query,
    is_weak_archive_topic,
)


def test_is_session_recall_query():
    assert is_session_recall_query("今天的聊天记录") is True
    assert is_session_recall_query("我今天问了啥?") is True
    assert is_session_recall_query("What did we talk about today?") is True
    assert is_session_recall_query("What did I talk about today?") is True
    assert is_session_recall_query("我上次对话问了啥?") is True
    assert is_session_recall_query("上一场聊了什么") is True
    assert is_session_recall_query("What did I ask in the last conversation?") is True
    assert is_last_session_recall_query("我上次对话问了啥?") is True
    assert is_last_session_recall_query("我今天问了啥?") is False
    assert is_session_recall_query("最近有什么新闻?") is False
    assert is_session_recall_query("我上次去北京旅游了") is False


def test_is_archive_recall_query():
    assert is_archive_recall_query("我问过关于关羽的什么问题吗?") is True
    assert is_archive_recall_query("我以前聊过 Rust 吗") is True
    assert is_archive_recall_query("有没有问过三国的事") is True
    assert is_archive_recall_query("ChatGPT 历史对话里有什么关于住房的") is True
    assert is_archive_recall_query("我在2025年6月问过哪些问题?") is True
    assert is_archive_recall_query("2025年12月我问过什么") is True
    # STM session recall stays on session path, not archive.
    assert is_archive_recall_query("我今天问了啥?") is False
    assert is_archive_recall_query("我上次对话问了啥?") is False
    assert is_archive_recall_query("最近有什么新闻?") is False
    assert is_archive_recall_query("我喜欢喝什么?") is False


def test_weak_archive_strips_last_session_boilerplate():
    topic = archive_search_query("我上次对话问了啥?")
    assert is_weak_archive_topic(topic)


def test_archive_search_query_extracts_topic():
    assert archive_search_query("我问过关于关羽的什么问题吗?") == "关羽"
    assert "Rust" in archive_search_query("我以前聊过 Rust 吗")
    topic = archive_search_query("我在2025年6月问过哪些问题?")
    assert "2025" not in topic
    assert is_weak_archive_topic(topic)


def test_recent_questions_is_weak_range_browse():
    """「我最近问过什么」must browse by time, not semantic-search the boilerplate."""
    q = "我最近问过什么?"
    assert is_archive_recall_query(q) is True
    since, until = archive_time_window(q)
    assert since and until
    topic = archive_search_query(q)
    assert "最近" not in topic
    assert is_weak_archive_topic(topic)


def test_archive_time_window_june():
    since, until = archive_time_window("我在2025年6月问过哪些问题?")
    assert since == "2025-06-01"
    assert until == "2025-06-30"


def test_prefetch_archive_context_searches_cold():
    with patch(
        "localagent.context.retrieval.get_retrieval_gateway",
    ) as get_gw:
        gw = MagicMock()
        gw.search_cold.return_value = "- [0.03] [chatgpt] 关羽北伐"
        gw.recall_warm.return_value = "未找到相关记忆。"
        get_gw.return_value = gw
        ctx = _prefetch_archive_context("我问过关于关羽的什么问题吗?")
    assert ctx
    assert "对话归档" in ctx
    assert "关羽北伐" in ctx
    gw.search_cold.assert_called_once()
    assert gw.search_cold.call_args.args == ("关羽",)
    assert gw.search_cold.call_args.kwargs["top_k"] == 5
    assert gw.search_cold.call_args.kwargs["fallback"] is False
    gw.recall_warm.assert_called_once()
    assert gw.recall_warm.call_args.args == ("关羽",)
    assert gw.recall_warm.call_args.kwargs["top_k"] == 5
    assert gw.recall_warm.call_args.kwargs["fallback"] is False


def test_prefetch_archive_temporal_lists_by_range():
    with patch(
        "localagent.context.retrieval.get_retrieval_gateway",
    ) as get_gw:
        gw = MagicMock()
        gw.list_user_questions_in_range.return_value = (
            "- [chatgpt/2025-06-10] June talk about rust"
        )
        gw.query_warm.return_value = "未找到匹配记忆。"
        get_gw.return_value = gw
        ctx = _prefetch_archive_context("我在2025年6月问过哪些问题?")
    assert ctx
    assert "时间窗" in ctx
    assert "2025-06-01" in ctx
    assert "June talk" in ctx
    gw.list_user_questions_in_range.assert_called_once()
    kwargs = gw.list_user_questions_in_range.call_args.kwargs
    assert kwargs["since"] == "2025-06-01"
    assert kwargs["until"] == "2025-06-30"
    gw.query_warm.assert_called_once()
    assert gw.query_warm.call_args.kwargs["time_field"] == "recorded"
    gw.search_cold.assert_not_called()
    gw.recall_warm.assert_not_called()


def test_prefetch_recent_questions_lists_user_turns():
    with patch(
        "localagent.context.retrieval.get_retrieval_gateway",
    ) as get_gw:
        gw = MagicMock()
        gw.list_user_questions_in_range.return_value = (
            "- [chat/2026-07-16] 土星最近有什么动态吗"
        )
        gw.query_warm.return_value = "未找到匹配记忆。"
        get_gw.return_value = gw
        ctx = _prefetch_archive_context("我最近问过什么?")
    assert "土星" in ctx
    assert "时间窗" in ctx
    gw.list_user_questions_in_range.assert_called_once()
    gw.list_knowledge_in_range.assert_not_called()
    gw.search_cold.assert_not_called()


def test_prefetch_archive_temporal_empty_window():
    with patch(
        "localagent.context.retrieval.get_retrieval_gateway",
    ) as get_gw:
        gw = MagicMock()
        gw.list_user_questions_in_range.return_value = (
            "该时段无对话归档（自 2025-06-01 · 至 2025-06-30）。"
        )
        gw.query_warm.return_value = "未找到匹配记忆。"
        get_gw.return_value = gw
        ctx = _prefetch_archive_context("我在2025年6月问过哪些问题?")
    assert "该时段无对话归档" in ctx
    assert "禁止编造" in ctx


def test_prefetch_archive_skips_non_archive():
    assert _prefetch_archive_context("今天天气怎么样?") == ""
