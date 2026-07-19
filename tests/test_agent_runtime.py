"""Agent runtime behavior tests."""

from __future__ import annotations

from unittest.mock import patch

from localagent.agent.runtime import (
    _build_system_prompt,
    _looks_incomplete_reply,
    _looks_like_tool_attempt,
    _make_answer_stream_gate,
    _needs_file_tool_retry,
    _parse_tool_call,
    _prefetch_archive_context,
    _prefetch_personal_context,
    _prefetch_session_context,
    _prefetch_web_context,
    _strip_tool_blocks,
    _tool_followup_instruction,
    _truncate_for_llm,
    run_agent_turn,
)


def test_answer_stream_gate_emits_prose():
    seen: list[str] = []
    gate = _make_answer_stream_gate(seen.append)
    assert gate is not None
    gate("你好")
    gate("，世界")
    assert "".join(seen) == "你好，世界"


def test_answer_stream_gate_mutes_tool_fence():
    seen: list[str] = []
    gate = _make_answer_stream_gate(seen.append)
    assert gate is not None
    gate("```tool\n")
    gate('{"name": "search_memory", "arguments": {"query": "x"}}\n```')
    assert seen == []


def test_answer_stream_gate_mutes_bare_json_tool():
    seen: list[str] = []
    gate = _make_answer_stream_gate(seen.append)
    assert gate is not None
    gate('{"name": "web_search", "arguments": {"query": "news"}}')
    assert seen == []


def test_answer_stream_gate_none():
    assert _make_answer_stream_gate(None) is None


def test_run_agent_turn_streams_final_answer_not_tool_json(isolated_data):
    seen: list[str] = []
    calls = {"n": 0}
    tool = '```tool\n{"name": "search_memory", "arguments": {"query": "家庭"}}\n```'
    answer = "根据记忆，你有一个温馨的家庭。"

    def fake_chat(messages, **kwargs):
        on_token = kwargs.get("on_token")
        calls["n"] += 1
        text = tool if calls["n"] == 1 else answer
        if on_token:
            mid = max(1, len(text) // 3)
            on_token(text[:mid])
            on_token(text[mid:])
        return text

    isolated_data["router"].chat.side_effect = fake_chat
    with patch(
        "localagent.tools.search_memory",
        return_value="家庭相关记忆",
    ):
        result = run_agent_turn(
            "关于我的家庭",
            provider="ollama",
            on_token=seen.append,
        )

    assert result.response == answer
    assert "".join(seen) == answer
    assert "```tool" not in "".join(seen)
    assert isolated_data["router"].chat.call_count == 2


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

    assert "业务代码合计约 3200 行。" in result.response
    assert "【Action receipt】" in result.response
    assert "run_shell: find src -name '*.py' | xargs wc -l" in result.response
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


def test_run_agent_turn_hints_ollama_cold_start(isolated_data):
    statuses: list[str] = []
    isolated_data["router"].should_hint_ollama_cold_start.return_value = True
    isolated_data["router"].chat.return_value = "你好"

    run_agent_turn("hi", provider="ollama", on_status=statuses.append)

    assert any("首次加载可能较慢" in s for s in statuses)


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

    assert "业务代码合计约 3200 行。" in result.response
    assert "【Action receipt】" in result.response
    assert "run_shell: wc -l src/**/*.py" in result.response
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


def test_run_agent_turn_compacts_prior_tool_observations(isolated_data):
    """Second tool round should leave older observations compressed in messages."""
    first = '```tool\n{"name": "search_memory", "arguments": {"query": "a"}}\n```'
    second = '```tool\n{"name": "web_search", "arguments": {"query": "b"}}\n```'
    replies = [first, second, "根据工具结果，这是完整综合答案。"]
    captured: list[list] = []
    state = {"n": 0}

    def chat_side_effect(messages, **_kwargs):
        captured.append(list(messages))
        reply = replies[state["n"]]
        state["n"] += 1
        return reply

    isolated_data["router"].chat.side_effect = chat_side_effect

    with (
        patch(
            "localagent.tools.search_memory",
            return_value="### 1. 旧记忆\n" + ("很长" * 40),
        ),
        patch(
            "localagent.tools.web_search",
            return_value="摘要: ok\n- [匹配] t: c\n  链接: https://ex.com",
        ),
        patch("localagent.agent.runtime._prefetch_web_context", return_value=""),
        patch("localagent.agent.runtime._prefetch_personal_context", return_value=""),
    ):
        result = run_agent_turn("随便问", provider="ollama")

    assert result.response == "根据工具结果，这是完整综合答案。"
    assert len(result.tool_calls) == 2
    assert len(captured) == 3
    third_msgs = captured[2]
    compacted = [
        m.content
        for m in third_msgs
        if getattr(m, "role", None) == "user" and "已压缩" in str(getattr(m, "content", ""))
    ]
    latest = [
        m.content
        for m in third_msgs
        if getattr(m, "role", None) == "user"
        and str(getattr(m, "content", "")).startswith("工具结果:")
    ]
    assert compacted
    assert "search_memory" in compacted[0]
    assert latest
    assert "https://ex.com" in latest[-1] or "摘要" in latest[-1]


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
    with (
        patch("localagent.tools.search_memory", return_value="未找到相关记忆。") as search,
        patch(
            "localagent.tools.search_knowledge",
            return_value="未找到相关知识。",
        ) as cold,
    ):
        ctx = _prefetch_personal_context("我是谁?")
    assert ctx
    assert "已预加载" in ctx
    assert "未找到相关记忆" in ctx
    assert "Cold" in ctx
    search.assert_called_once_with("我是谁?", top_k=8)
    cold.assert_called_once()
    assert cold.call_args.kwargs.get("conversation_only") is True


def test_prefetch_memory_browse_question():
    with (
        patch(
            "localagent.tools.query_memories_tool",
            return_value="记忆库共 3 条，返回 3 条",
        ) as browse,
        patch(
            "localagent.tools.search_knowledge",
            return_value="- [0.02] [chatgpt] 用户讨论 Rust 与葡萄酒品鉴",
        ) as cold,
    ):
        ctx = _prefetch_personal_context("我的记忆库里有什么有趣的东西吗?")
    assert ctx
    assert "已预加载" in ctx
    assert "记忆库共 3 条" in ctx
    assert "Warm" in ctx
    assert "Cold" in ctx
    assert "葡萄酒品鉴" in ctx
    browse.assert_called_once_with(
        query="我的记忆库里有什么有趣的东西吗?",
        sort="relevance",
        limit=8,
    )
    cold.assert_called_once()
    assert cold.call_args.kwargs.get("top_k") == 5
    assert cold.call_args.kwargs.get("fallback") is False
    assert cold.call_args.kwargs.get("conversation_only") is not True


def test_browse_cold_query_strips_boilerplate():
    from localagent.agent.runtime import _browse_cold_query

    assert (
        _browse_cold_query("搜索我的记忆库,我之前主要感兴趣的事情在哪些方面?")
        == "我之前主要感兴趣的事情在哪些方面"
    )
    assert _browse_cold_query("我的记忆库里有什么有趣的东西吗?") == (
        "有什么有趣的东西吗"
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
        patch(
            "localagent.tools.search_knowledge",
            return_value="- [chatgpt] 家庭相关对话",
        ) as cold,
    ):
        ctx = _prefetch_personal_context("关于我的家庭,你都知道些什么?深入搜索我的记忆库.")
    assert ctx
    assert "已预加载" in ctx
    assert "Cold" in ctx
    query.assert_called_once()
    assert query.call_args.kwargs.get("tags") == ["家庭"]
    search.assert_called_once()
    cold.assert_called_once()
    assert cold.call_args.kwargs.get("conversation_only") is True


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


def test_prefetch_web_stale_results_allow_research():
    stale = (
        "【检索基准日】2026年7月14日\n"
        "【核对失败】没有与检索基准日相符的结果。\n"
        "过期结果（仅供排查，不可当作当前事实）:\n"
        "- [过期·2026-03-15] 深圳天气: 大雨"
    )
    with patch("localagent.tools.web_search", return_value=stale):
        ctx = _prefetch_web_context("深圳今天天气怎么样")
    assert "时效核对未通过" in ctx
    assert "再调用 web_search" in ctx
    assert "勿再调用 web_search" not in ctx


def test_tool_followup_allows_research_on_freshness_failure():
    result = "【核对失败】没有与检索基准日相符的结果。"
    text = _tool_followup_instruction("web_search", result)
    assert "再调用一次 web_search" in text
    assert "禁止在未重试的情况下" in text


def test_tool_followup_checks_basics_on_ok_search():
    text = _tool_followup_instruction("web_search", "摘要: 今日多云\n- [匹配] 深圳天气")
    assert "时间/地点" in text
    assert "不要再次调用工具" in text
    assert "完整链接" in text


def test_prefetch_web_requires_source_citation():
    with patch(
        "localagent.tools.web_search",
        return_value="摘要: 今日多云\n链接: https://example.com/wx\n【引用要求】须标注来源",
    ):
        ctx = _prefetch_web_context("北京今天天气怎么样")
    assert "标题与完整链接" in ctx
    assert "勿再调用 web_search" in ctx


def test_prefetch_weather_injects_home_location(isolated_data):
    from localagent.memory.core_profile import CoreProfile, save_core_profile

    save_core_profile(CoreProfile(preferences={"居住地": "深圳"}))
    with patch("localagent.tools.web_search", return_value="摘要: 深圳多云") as search:
        ctx = _prefetch_web_context("今天天气怎么样?")
    assert ctx
    search.assert_called_once_with("深圳 今天天气怎么样?")
    assert "其他城市" not in ctx


def test_prefetch_weather_without_home_still_searches(isolated_data):
    with patch("localagent.tools.web_search", return_value="摘要: 今日多云") as search:
        ctx = _prefetch_web_context("今天天气怎么样?")
    assert ctx
    search.assert_called_once_with("今天天气怎么样?")
    assert "其他城市" not in ctx


def test_prefetch_session_context_loads_today_messages(isolated_data):
    from localagent.persist.conversations import append_message

    # Other session in STM window (current session uses in-memory history).
    append_message("s-other-today", "user", "介绍一下我的军事策略")
    append_message("s-other-today", "assistant", "根据记忆库…")

    ctx = _prefetch_session_context(
        "今天的聊天记录",
        history=[
            {"role": "user", "content": "介绍一下我的军事策略"},
            {"role": "assistant", "content": "根据记忆库…"},
            {"role": "user", "content": "我今天问了啥?"},
        ],
        session_id="s-recall-test",
    )
    assert "已预加载" in ctx
    assert "介绍一下我的军事策略" in ctx
    assert "我今天问了啥?" in ctx


def test_prefetch_session_context_prefers_recent_over_lexicographic(isolated_data, monkeypatch):
    """Newest sessions must survive budget; id sort must not bury them."""
    import time

    from localagent.persist.conversations import (
        _append_to_mapping,
        _empty_conversation,
        _save_raw,
    )

    monkeypatch.setattr("localagent.config.PREFETCH_BUDGET_CHARS", 400)
    monkeypatch.setattr("localagent.config.STM_WINDOW_HOURS", 24.0)

    now = time.time()
    # Lexicographically first id, older, padded to burn budget if sorted by id.
    old = _empty_conversation("s-aaa-old", now=now - 3600)
    for i in range(8):
        _append_to_mapping(
            old,
            role="user" if i % 2 == 0 else "assistant",
            content=("旧会话填充内容-" * 8) + f"-{i}",
            create_time=now - 3600 + i,
        )
    _save_raw("s-aaa-old", old)

    recent = _empty_conversation("s-zzz-wine", now=now - 60)
    _append_to_mapping(
        recent,
        role="user",
        content="借问酒家何处有",
        create_time=now - 60,
    )
    _append_to_mapping(
        recent,
        role="assistant",
        content="附近有粤菜馆。",
        create_time=now - 50,
    )
    _save_raw("s-zzz-wine", recent)

    ctx = _prefetch_session_context("我今天问了什么", history=None, session_id="s-current")
    assert "借问酒家何处有" in ctx


def test_prefetch_session_context_respects_stm_window_hours(isolated_data, monkeypatch):
    import time

    from localagent.persist.conversations import (
        _append_to_mapping,
        _empty_conversation,
        _save_raw,
    )

    monkeypatch.setattr("localagent.config.STM_WINDOW_HOURS", 1.0)
    now = time.time()

    inside = _empty_conversation("s-inside", now=now - 600)
    _append_to_mapping(
        inside, role="user", content="窗内话题爬山", create_time=now - 600
    )
    _save_raw("s-inside", inside)

    outside = _empty_conversation("s-outside", now=now - 7200)
    _append_to_mapping(
        outside, role="user", content="窗外话题相机", create_time=now - 7200
    )
    _save_raw("s-outside", outside)

    ctx = _prefetch_session_context("我今天聊了啥", history=None, session_id=None)
    assert "爬山" in ctx
    assert "相机" not in ctx


def test_prefetch_last_session_loads_previous_not_archive(isolated_data):
    import time

    from localagent.persist.conversations import (
        _append_to_mapping,
        _empty_conversation,
        _save_raw,
    )

    now = time.time()
    prev = _empty_conversation("s-prev", now=now - 120)
    _append_to_mapping(
        prev, role="user", content="借问酒家何处有", create_time=now - 120
    )
    _save_raw("s-prev", prev)

    older = _empty_conversation("s-older", now=now - 86400 * 3)
    _append_to_mapping(
        older, role="user", content="卧室怎么摆家具", create_time=now - 86400 * 3
    )
    _save_raw("s-older", older)

    ctx = _prefetch_session_context(
        "我上次对话问了啥?",
        history=[{"role": "user", "content": "我上次对话问了啥?"}],
        session_id="s-current-new",
    )
    assert "上一场" in ctx or "借问酒家" in ctx
    assert "借问酒家何处有" in ctx
    assert "卧室" not in ctx
    assert _prefetch_archive_context("我上次对话问了啥?") == ""


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


def test_build_system_prompt_includes_prefetched_context(monkeypatch):
    from localagent.i18n import reset_lang_cache

    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    prompt = _build_system_prompt(
        personal_context="[个人上下文]\n姓名: 测试",
        web_context="[联网搜索结果]\n摘要: 新闻",
    )
    assert "姓名: 测试" in prompt
    assert "摘要: 新闻" in prompt
    assert "search_memory" in prompt
    assert "证据核对" in prompt
    assert "今天是" in prompt


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

    with (
        patch(
            "localagent.tools.query_memories_tool",
            return_value="记忆库共 5 条，返回 5 条",
        ) as browse,
        patch(
            "localagent.tools.search_knowledge",
            return_value="- [0.01] [chat] 讨论过项目架构",
        ) as cold,
    ):
        result = run_agent_turn("我的记忆库里有什么有趣的东西吗?", provider="ollama")

    assert "有趣" in result.response
    assert result.tool_calls == []
    browse.assert_called_once_with(
        query="我的记忆库里有什么有趣的东西吗?",
        sort="relevance",
        limit=8,
    )
    cold.assert_called_once()
    system_prompt = isolated_data["router"].chat.call_args.args[0][0].content
    assert "已预加载" in system_prompt
    assert "记忆库共 5 条" in system_prompt
    assert "Cold" in system_prompt
    assert "项目架构" in system_prompt


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

    assert "文件已更新。" in result.response
    assert "【Action receipt】" in result.response
    assert "write_file (overwrite): test.txt" in result.response
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

    assert "已追加第二行。" in result.response
    assert "【Action receipt】" in result.response
    assert "write_file (append): test.txt" in result.response
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


