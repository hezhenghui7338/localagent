"""Tests for session-recall query detection."""

from localagent.agent.runtime import is_session_recall_query


def test_is_session_recall_query():
    assert is_session_recall_query("今天的聊天记录") is True
    assert is_session_recall_query("我今天问了啥?") is True
    assert is_session_recall_query("最近有什么新闻?") is False
