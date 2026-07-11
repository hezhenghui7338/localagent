"""Agent runtime behavior tests."""

from __future__ import annotations

from unittest.mock import patch

from localagent.agent.runtime import (
    _build_system_prompt,
    _parse_tool_call,
    _prefetch_personal_context,
    _prefetch_web_context,
    run_agent_turn,
)


def test_parse_tool_call_accepts_tool_fence():
    text = '```tool\n{"name": "search_memory", "arguments": {"query": "我是谁"}}\n```'
    assert _parse_tool_call(text) == {
        "name": "search_memory",
        "arguments": {"query": "我是谁"},
    }


def test_parse_tool_call_accepts_json_fence():
    text = '```json\n{"name": "search_knowledge", "arguments": {"query": "几年前的关注点"}}\n```'
    assert _parse_tool_call(text) == {
        "name": "search_knowledge",
        "arguments": {"query": "几年前的关注点"},
    }


def test_parse_tool_call_accepts_bare_json():
    text = '{"name": "web_search", "arguments": {"query": "今日新闻"}}'
    assert _parse_tool_call(text) == {
        "name": "web_search",
        "arguments": {"query": "今日新闻"},
    }


def test_parse_tool_call_rejects_unknown_tool():
    assert _parse_tool_call('{"name": "delete_everything", "arguments": {}}') is None


def test_run_agent_turn_executes_json_fenced_tool_call(isolated_data):
    tool_reply = (
        '```json\n{"name": "search_knowledge", "arguments": {"query": "几年前"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [tool_reply, "你几年前关注 AI 视频工具。"]

    with patch(
        "localagent.tools.search_knowledge",
        return_value="[1] 用户关注 AI 视频工具",
    ) as search:
        result = run_agent_turn("几年前我关心什么?", provider="ollama")

    assert result.response == "你几年前关注 AI 视频工具。"
    assert result.tool_calls == [
        {"name": "search_knowledge", "arguments": {"query": "几年前"}}
    ]
    search.assert_called_once_with("几年前")
    assert isolated_data["router"].chat.call_count == 2


def test_prefetch_personal_context_for_identity_question():
    with patch("localagent.tools.search_memory", return_value="未找到相关记忆。") as search:
        ctx = _prefetch_personal_context("我是谁?")
    assert ctx
    assert "已预加载" in ctx
    assert "未找到相关记忆" in ctx
    search.assert_called_once_with("我是谁?")


def test_prefetch_memory_browse_question():
    with patch("localagent.tools.browse_memories", return_value="记忆库共 3 条，展示最近 3 条") as browse:
        ctx = _prefetch_personal_context("我的记忆库里有什么有趣的东西吗?")
    assert ctx
    assert "已预加载" in ctx
    assert "记忆库共 3 条" in ctx
    browse.assert_called_once()


def test_prefetch_skips_generic_question():
    assert _prefetch_personal_context("今天天气怎么样?") == ""


def test_prefetch_web_context_for_news_question():
    with patch("localagent.tools.web_search", return_value="摘要: 今日要闻\n- 新闻A") as search:
        ctx = _prefetch_web_context("最近有什么新闻?")
    assert ctx
    assert "已预加载" in ctx
    assert "今日要闻" in ctx
    search.assert_called_once_with("最近有什么新闻?")


def test_prefetch_web_skips_non_time_sensitive_question():
    assert _prefetch_web_context("Python 怎么写装饰器?") == ""


def test_build_system_prompt_includes_prefetched_context():
    prompt = _build_system_prompt(
        personal_context="[个人上下文]\n姓名: 测试",
        web_context="[联网搜索结果]\n摘要: 新闻",
    )
    assert "姓名: 测试" in prompt
    assert "摘要: 新闻" in prompt
    assert "search_memory" in prompt


def test_run_agent_turn_prefetches_without_tool_round(isolated_data, monkeypatch):
    isolated_data["router"].chat.return_value = "你是 LocalAgent 用户。"

    with patch("localagent.tools.search_memory", return_value="未找到相关记忆。") as search:
        result = run_agent_turn("我是谁?", provider="ollama")

    assert result.response == "你是 LocalAgent 用户。"
    assert result.tool_calls == []
    search.assert_called_once()
    system_prompt = isolated_data["router"].chat.call_args.args[0][0].content
    assert "已预加载" in system_prompt


def test_run_agent_turn_prefetches_memory_browse(isolated_data):
    isolated_data["router"].chat.return_value = "你的记忆库里有不少有趣的内容。"

    with patch(
        "localagent.tools.browse_memories",
        return_value="记忆库共 5 条，展示最近 5 条",
    ) as browse:
        result = run_agent_turn("我的记忆库里有什么有趣的东西吗?", provider="ollama")

    assert "有趣" in result.response
    assert result.tool_calls == []
    browse.assert_called_once()
    system_prompt = isolated_data["router"].chat.call_args.args[0][0].content
    assert "已预加载" in system_prompt
    assert "记忆库共 5 条" in system_prompt


def test_run_agent_turn_prefetches_web_for_news(isolated_data):
    isolated_data["router"].chat.return_value = "以下是最近新闻。"

    with patch("localagent.tools.web_search", return_value="摘要: 今日要闻") as search:
        result = run_agent_turn("最近有什么新闻?", provider="ollama")

    assert result.response == "以下是最近新闻。"
    assert result.tool_calls == []
    search.assert_called_once_with("最近有什么新闻?")
    system_prompt = isolated_data["router"].chat.call_args.args[0][0].content
    assert "联网搜索结果" in system_prompt
    assert "今日要闻" in system_prompt
