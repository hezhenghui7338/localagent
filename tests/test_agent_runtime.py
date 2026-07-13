"""Agent runtime behavior tests."""

from __future__ import annotations

from unittest.mock import patch

from localagent.agent.runtime import (
    _build_system_prompt,
    _looks_incomplete_reply,
    _looks_like_tool_attempt,
    _needs_file_tool_retry,
    _parse_tool_call,
    _prefetch_personal_context,
    _prefetch_session_context,
    _prefetch_web_context,
    _strip_tool_blocks,
    _truncate_for_llm,
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


def test_parse_tool_call_accepts_xml_format():
    text = (
        "让我搜索记忆库。"
        "<tool_call>search_memory"
        "<arg_key>query</arg_key><arg_value>Memory System 研究 去年</arg_value>"
        "</tool_call>"
    )
    assert _parse_tool_call(text) == {
        "name": "search_memory",
        "arguments": {"query": "Memory System 研究 去年"},
    }


def test_strip_tool_blocks():
    text = '先说一段\n```tool\n{"name": "query_memories", "arguments": {"since": "2023-01-01"}}\n```'
    assert "query_memories" not in _strip_tool_blocks(text)
    assert "先说一段" in _strip_tool_blocks(text)


def test_strip_tool_blocks_removes_xml_tool_call():
    text = (
        "让我搜索。"
        "<tool_call>search_memory"
        "<arg_key>query</arg_key><arg_value>去年研究</arg_value>"
        "</tool_call>"
    )
    assert _strip_tool_blocks(text) == "让我搜索。"


def test_looks_like_tool_attempt_detects_truncated_fence():
    text = (
        '```tool\n{"name": "run_shell", "arguments": {"command": "find . -name \'*.py\''
    )
    assert _looks_like_tool_attempt(text)
    assert _parse_tool_call(text) is None
    assert _strip_tool_blocks(text) == ""


def test_run_agent_turn_retries_truncated_tool_call(isolated_data):
    truncated = (
        '```tool\n{"name": "run_shell", "arguments": {"command": "find . -name \'*.py\''
    )
    fixed = (
        '```tool\n{"name": "run_shell", "arguments": '
        '{"command": "find src -name \'*.py\' | xargs wc -l"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [
        truncated,
        fixed,
        "业务代码合计约 3200 行。",
    ]

    with patch(
        "localagent.tools.run_shell",
        return_value="3200 total",
    ) as shell:
        result = run_agent_turn("好,重新统计下业务代码行数", provider="ollama")

    assert result.response == "业务代码合计约 3200 行。"
    assert result.tool_calls == [
        {
            "name": "run_shell",
            "arguments": {"command": "find src -name '*.py' | xargs wc -l"},
        }
    ]
    shell.assert_called_once()
    assert isolated_data["router"].chat.call_count == 3


def test_run_agent_turn_empty_reply_gets_fallback(isolated_data):
    isolated_data["router"].chat.side_effect = ["", "", ""]

    result = run_agent_turn("你好", provider="ollama")

    assert "未返回有效内容" in result.response
    assert result.tool_calls == []
    assert isolated_data["router"].chat.call_count == 3


def test_looks_incomplete_reply_detects_truncated_synthesis():
    assert _looks_incomplete_reply("根据", had_tools=True)
    assert _looks_incomplete_reply("根据工具结果，", had_tools=True)
    assert not _looks_incomplete_reply("根据", had_tools=False)
    assert not _looks_incomplete_reply(
        "业务代码合计约 3200 行，已排除 .venv 与依赖目录。",
        had_tools=True,
    )


def test_truncate_for_llm_keeps_head_and_tail():
    text = "A" * 2000 + "MID" + "B" * 2000
    out = _truncate_for_llm(text, limit=500)
    assert len(out) < len(text)
    assert "截断" in out
    assert out.startswith("A")
    assert out.endswith("B")


def test_run_agent_turn_retries_incomplete_synthesis(isolated_data):
    tool_reply = (
        '```tool\n{"name": "run_shell", "arguments": '
        '{"command": "wc -l src/**/*.py"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [
        tool_reply,
        "根据",
        "业务代码合计约 3200 行。",
    ]

    with patch("localagent.tools.run_shell", return_value="3200 total"):
        result = run_agent_turn("统计当前项目的代码行数", provider="ollama")

    assert result.response == "业务代码合计约 3200 行。"
    assert isolated_data["router"].chat.call_count == 3


def test_run_agent_turn_executes_xml_tool_call(isolated_data):
    tool_reply = (
        "我来查一下。"
        "<tool_call>search_memory"
        "<arg_key>query</arg_key><arg_value>Memory System 研究 去年</arg_value>"
        "</tool_call>"
    )
    isolated_data["router"].chat.side_effect = [tool_reply, "你去年研究了 Hindsight 和 Mem0。"]

    with patch(
        "localagent.tools.search_memory",
        return_value="[1] Hindsight 记忆系统\n[2] Mem0",
    ) as search:
        result = run_agent_turn("我去年研究过哪些 Memory System？", provider="openrouter")

    assert result.response == "你去年研究了 Hindsight 和 Mem0。"
    assert result.tool_calls == [
        {"name": "search_memory", "arguments": {"query": "Memory System 研究 去年"}}
    ]
    search.assert_called_once_with("Memory System 研究 去年")
    assert isolated_data["router"].chat.call_count == 2


def test_run_agent_turn_returns_final_answer_after_tool(isolated_data):
    first = (
        '```tool\n{"name": "query_memories", "arguments": {"query": "家庭", "tags": ["家庭"]}}\n```'
    )
    isolated_data["router"].chat.side_effect = [first, "你的妻子求职中，你会帮她盯简历。"]

    with patch(
        "localagent.tools.query_memories_tool",
        return_value="### 1. 妻子求职\n妻子在找工作",
    ):
        result = run_agent_turn("关于我的家庭", provider="ollama")

    assert result.response == "你的妻子求职中，你会帮她盯简历。"
    assert len(result.tool_calls) == 1
    assert isolated_data["router"].chat.call_count == 2


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
    search.assert_called_once_with("我是谁?", top_k=10)


def test_prefetch_memory_browse_question():
    with patch(
        "localagent.tools.query_memories_tool",
        return_value="记忆库共 3 条，返回 3 条",
    ) as browse:
        ctx = _prefetch_personal_context("我的记忆库里有什么有趣的东西吗?")
    assert ctx
    assert "已预加载" in ctx
    assert "记忆库共 3 条" in ctx
    browse.assert_called_once_with(
        query="我的记忆库里有什么有趣的东西吗?",
        sort="relevance",
        limit=25,
    )


def test_prefetch_family_question_uses_tag_search():
    with (
        patch(
            "localagent.tools.query_memories_tool",
            return_value="找到 2 条相关记忆",
        ) as query,
        patch(
            "localagent.tools.search_memory",
            return_value="妻子相关记忆",
        ) as search,
    ):
        ctx = _prefetch_personal_context("关于我的家庭,你都知道些什么?深入搜索我的记忆库.")
    assert ctx
    assert "已预加载" in ctx
    query.assert_called_once()
    assert query.call_args.kwargs.get("tags") == ["家庭"]
    search.assert_called_once()


def test_prefetch_skips_generic_question():
    assert _prefetch_personal_context("今天天气怎么样?") == ""


def test_prefetch_web_context_for_news_question():
    with patch("localagent.tools.web_search", return_value="摘要: 今日要闻\n- 新闻A") as search:
        ctx = _prefetch_web_context("最近有什么新闻?")
    assert ctx
    assert "已预加载" in ctx
    assert "今日要闻" in ctx
    search.assert_called_once_with("最近有什么新闻?")


def test_prefetch_web_context_for_current_time_question():
    """Regression: '现在几点了' must prefetch web search, not rely on model knowledge."""
    with patch("localagent.tools.web_search", return_value="摘要: 当前时间约为 11:12") as search:
        ctx = _prefetch_web_context("say hi,现在几点了")
    assert ctx
    assert "已预加载" in ctx
    assert "当前时间约为 11:12" in ctx
    search.assert_called_once_with("say hi,现在几点了")


def test_prefetch_web_context_for_几点了():
    with patch("localagent.tools.web_search", return_value="摘要: 北京时间 11:12") as search:
        ctx = _prefetch_web_context("现在几点了")
    assert ctx
    search.assert_called_once_with("现在几点了")


def test_prefetch_web_skips_non_time_sensitive_question():
    assert _prefetch_web_context("Python 怎么写装饰器?") == ""


def test_prefetch_web_skips_session_recall_question():
    with patch("localagent.tools.web_search") as search:
        assert _prefetch_web_context("今天的聊天记录") == ""
    search.assert_not_called()


def test_prefetch_session_context_loads_today_messages(isolated_data):
    from localagent.persist.conversations import append_message

    session_id = "s-recall-test"
    append_message(session_id, "user", "介绍一下我的军事策略")
    append_message(session_id, "assistant", "根据记忆库…")

    ctx = _prefetch_session_context(
        "今天的聊天记录",
        history=[{"role": "user", "content": "我今天问了啥?"}],
        session_id=session_id,
    )
    assert "已预加载" in ctx
    assert "介绍一下我的军事策略" in ctx
    assert "我今天问了啥?" in ctx


def test_run_agent_turn_prefetches_session_recall_without_web(isolated_data):
    isolated_data["router"].chat.return_value = "你今天问了军事策略等问题。"

    with (
        patch("localagent.tools.web_search") as search,
        patch(
            "localagent.agent.runtime._prefetch_session_context",
            return_value="[对话记录（已预加载）]\n用户: 介绍一下我的军事策略",
        ),
    ):
        result = run_agent_turn("今天的聊天记录", provider="ollama")

    assert "军事策略" in result.response
    search.assert_not_called()
    system_prompt = isolated_data["router"].chat.call_args.args[0][0].content
    assert "对话记录" in system_prompt


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
        "localagent.tools.query_memories_tool",
        return_value="记忆库共 5 条，返回 5 条",
    ) as browse:
        result = run_agent_turn("我的记忆库里有什么有趣的东西吗?", provider="ollama")

    assert "有趣" in result.response
    assert result.tool_calls == []
    browse.assert_called_once_with(
        query="我的记忆库里有什么有趣的东西吗?",
        sort="relevance",
        limit=25,
    )
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


def test_run_agent_turn_prefetches_web_for_current_time(isolated_data):
    """Regression: asking the current time must trigger web search prefetch."""
    isolated_data["router"].chat.return_value = "现在大约是上午 11:12。"

    with patch("localagent.tools.web_search", return_value="摘要: 当前本地时间 11:12") as search:
        result = run_agent_turn("say hi,现在几点了", provider="ollama")

    assert result.response == "现在大约是上午 11:12。"
    assert result.tool_calls == []
    search.assert_called_once_with("say hi,现在几点了")
    system_prompt = isolated_data["router"].chat.call_args.args[0][0].content
    assert "联网搜索结果" in system_prompt
    assert "当前本地时间 11:12" in system_prompt


def test_needs_file_tool_retry_detects_hallucinated_write():
    assert _needs_file_tool_retry(
        "内容写:这是我的测试文本",
        "已为你更新 `test.txt` 文件，当前内容为：hello",
        [],
    )


def test_needs_file_tool_retry_detects_append_hallucination():
    assert _needs_file_tool_retry(
        "追加内容:第二行内容是这样的,闲杂时间",
        '已成功将"第二行内容"追加到 `test.txt` 文件中。当前文件完整内容为：\n\n',
        [],
    )


def test_needs_file_tool_retry_detects_direct_write_without_claim():
    assert _needs_file_tool_retry(
        "追加内容:第二行",
        "好的。",
        [],
    )


def test_needs_file_tool_retry_ignores_clarification():
    assert not _needs_file_tool_retry(
        "修改根目录下的test.txt文件",
        "请告诉我具体的修改内容或目标要求。",
        [],
    )


def test_needs_file_tool_retry_ignores_when_tool_called():
    assert not _needs_file_tool_retry(
        "内容写:这是我的测试文本",
        "已为你更新 test.txt",
        [{"name": "write_file", "arguments": {"path": "test.txt", "content": "hello"}}],
    )


def test_run_agent_turn_retries_when_file_write_claimed_without_tool(isolated_data):
    hallucinated = "已为你更新 `test.txt` 文件，当前内容为：新内容"
    tool_reply = (
        '```tool\n{"name": "write_file", "arguments": {"path": "test.txt", '
        '"content": "新内容"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [hallucinated, tool_reply, "文件已更新。"]

    with patch(
        "localagent.tools.write_file",
        return_value="已写入文件: test.txt\n内容预览:\n新内容",
    ) as write:
        result = run_agent_turn("内容写:新内容", provider="ollama")

    assert result.response == "文件已更新。"
    assert result.tool_calls == [
        {"name": "write_file", "arguments": {"path": "test.txt", "content": "新内容"}}
    ]
    write.assert_called_once_with("test.txt", "新内容", mode="overwrite", cwd=None)
    assert isolated_data["router"].chat.call_count == 3


def test_run_agent_turn_retries_append_hallucination(isolated_data):
    hallucinated = (
        '已成功将"第二行"追加到 `test.txt` 文件中。当前文件完整内容为：\n\n'
    )
    tool_reply = (
        '```tool\n{"name": "write_file", "arguments": {"path": "test.txt", '
        '"content": "第二行内容是这样的,闲杂时间\\n", "mode": "append"}}\n```'
    )
    isolated_data["router"].chat.side_effect = [hallucinated, tool_reply, "已追加第二行。"]

    with patch(
        "localagent.tools.write_file",
        return_value="已追加文件: test.txt\n内容预览:\n第二行内容是这样的,闲杂时间\n",
    ) as write:
        result = run_agent_turn("追加内容:第二行内容是这样的,闲杂时间", provider="ollama")

    assert result.response == "已追加第二行。"
    assert result.tool_calls[0]["arguments"]["mode"] == "append"
    write.assert_called_once_with(
        "test.txt",
        "第二行内容是这样的,闲杂时间\n",
        mode="append",
        cwd=None,
    )


def test_run_agent_turn_fails_gracefully_after_retry_exhausted(isolated_data):
    hallucinated = (
        '已成功将"第二行"追加到 `test.txt` 文件中。当前文件完整内容为：\n\n'
    )
    isolated_data["router"].chat.side_effect = [hallucinated, hallucinated, hallucinated]

    result = run_agent_turn("追加内容:第二行内容", provider="ollama")

    assert "未能实际写入文件" in result.response
    assert result.tool_calls == []


def test_parse_write_file_tool_call():
    text = (
        '```tool\n{"name": "write_file", "arguments": {"path": "test.txt", '
        '"content": "hello"}}\n```'
    )
    assert _parse_tool_call(text) == {
        "name": "write_file",
        "arguments": {"path": "test.txt", "content": "hello"},
    }


def test_run_agent_turn_none_reply_treated_as_empty(isolated_data):
    isolated_data["router"].chat.side_effect = [None, "你好，我是 LocalAgent"]

    result = run_agent_turn("你好", provider="ollama")

    assert result.response == "你好，我是 LocalAgent"
    assert isolated_data["router"].chat.call_count == 2


