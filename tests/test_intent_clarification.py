"""Tests for proactive intent clarification."""

from __future__ import annotations

import json

from localagent.agent.intent_clarification import (
    IntentAssessment,
    assess_intent,
    format_assumed_intent,
    format_clarification_response,
    is_personal_memory_query,
    is_session_recall_query,
    merge_clarified_intent,
    should_skip_intent_assessment,
)


def test_should_skip_for_greeting():
    assert should_skip_intent_assessment("你好") is True


def test_should_skip_for_clear_line_count():
    assert should_skip_intent_assessment("统计当前项目的代码行数") is True
    assert should_skip_intent_assessment("当前项目,localagent,给我提供详细的代码行数") is True
    assert should_skip_intent_assessment("帮我改一下") is False


def test_should_skip_for_specific_path():
    assert should_skip_intent_assessment("请分析 src/localagent/agent/runtime.py") is True


def test_should_not_skip_for_vague_request():
    assert should_skip_intent_assessment("帮我改一下") is False


def test_should_skip_for_session_recall():
    assert should_skip_intent_assessment("我今天问了啥?") is True
    assert should_skip_intent_assessment("我们刚才聊了什么") is True
    assert should_skip_intent_assessment("总结一下今天的对话") is True
    assert should_skip_intent_assessment("今天的聊天记录") is True


def test_should_skip_for_personal_memory_queries():
    assert should_skip_intent_assessment("你知道我住在哪里吗?") is True
    assert should_skip_intent_assessment("记录一下:我居住在深圳") is True
    assert should_skip_intent_assessment("我是谁") is True
    assert should_skip_intent_assessment("我喜欢喝什么呢?") is True
    assert should_skip_intent_assessment("我喜欢什么") is True
    assert is_personal_memory_query("我喜欢喝什么呢?") is True


def test_is_session_recall_query():
    assert is_session_recall_query("今天的聊天记录") is True
    assert is_session_recall_query("最近有什么新闻?") is False


def test_assess_intent_skips_session_recall_without_llm(isolated_data):
    result = assess_intent("我今天问了啥?")
    assert result.mode == "act"
    assert result.needs_clarification is False
    isolated_data["router"].chat.assert_not_called()


def test_assess_intent_skips_preference_recall_without_llm(isolated_data):
    result = assess_intent("我喜欢喝什么呢?")
    assert result.mode == "act"
    assert result.needs_clarification is False
    isolated_data["router"].chat.assert_not_called()


def test_parse_assessment_needs_clarification(isolated_data):
    payload = json.dumps(
        {
            "mode": "clarify",
            "assumptions": [],
            "questions": ["你想修改哪个文件？"],
            "risk": "high",
            "reasoning": "缺少对象与目标",
        },
        ensure_ascii=False,
    )
    isolated_data["router"].chat.return_value = payload
    result = assess_intent("帮我改一下")
    assert result.mode == "clarify"
    assert result.needs_clarification is True
    assert len(result.questions) == 1
    assert "文件" in result.questions[0]


def test_parse_assessment_legacy_binary_schema(isolated_data):
    payload = json.dumps(
        {
            "needs_clarification": True,
            "questions": ["你想修改哪个文件？", "是要重构还是修 bug？"],
            "reasoning": "缺少对象与目标",
        },
        ensure_ascii=False,
    )
    isolated_data["router"].chat.return_value = payload
    result = assess_intent("帮我改一下")
    assert result.mode == "clarify"
    assert result.needs_clarification is True
    assert len(result.questions) == 1


def test_parse_assessment_clear_intent(isolated_data):
    payload = json.dumps(
        {
            "mode": "act",
            "assumptions": [],
            "questions": [],
            "risk": "low",
            "reasoning": "问题明确",
        },
        ensure_ascii=False,
    )
    isolated_data["router"].chat.return_value = payload
    result = assess_intent("统计 src/ 下所有 .py 文件的行数")
    assert result.mode == "act"
    assert result.needs_clarification is False


def test_parse_assessment_assume_mode(isolated_data):
    payload = json.dumps(
        {
            "mode": "assume",
            "assumptions": ["先列出当前项目目录结构"],
            "questions": [],
            "risk": "low",
            "reasoning": "轻微模糊但可逆",
        },
        ensure_ascii=False,
    )
    isolated_data["router"].chat.return_value = payload
    result = assess_intent("看看项目")
    assert result.mode == "assume"
    assert result.needs_clarification is False
    assert result.assumptions == ["先列出当前项目目录结构"]


def test_assess_intent_skips_when_disabled(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.INTENT_CLARIFY_ENABLED", False)
    result = assess_intent("帮我改一下")
    assert result.mode == "act"
    assert result.needs_clarification is False
    isolated_data["router"].chat.assert_not_called()


def test_assess_intent_parse_failure_defaults_to_clear(isolated_data):
    isolated_data["router"].chat.return_value = "这不是 JSON"
    result = assess_intent("帮我改一下")
    assert result.mode == "act"
    assert result.needs_clarification is False


def test_assess_intent_empty_questions_treated_as_clear(isolated_data):
    payload = json.dumps(
        {
            "mode": "clarify",
            "assumptions": [],
            "questions": [],
            "reasoning": "矛盾输出",
        },
        ensure_ascii=False,
    )
    isolated_data["router"].chat.return_value = payload
    result = assess_intent("帮我改一下")
    assert result.mode == "act"
    assert result.needs_clarification is False


def test_assess_intent_clarify_without_questions_falls_back_to_assume(isolated_data):
    payload = json.dumps(
        {
            "mode": "clarify",
            "assumptions": ["先查看 runtime.py"],
            "questions": [],
            "reasoning": "矛盾输出",
        },
        ensure_ascii=False,
    )
    isolated_data["router"].chat.return_value = payload
    result = assess_intent("帮我改一下")
    assert result.mode == "assume"
    assert result.assumptions == ["先查看 runtime.py"]


def test_format_clarification_response():
    assessment = IntentAssessment(
        mode="clarify",
        questions=["你想改哪个文件？"],
    )
    text = format_clarification_response(assessment)
    assert "确认你的意图" in text
    assert "1. 你想改哪个文件？" in text


def test_format_assumed_intent():
    text = format_assumed_intent("看看项目", ["先列出当前仓库目录结构"])
    assert "[用户问题]" in text
    assert "看看项目" in text
    assert "[执行假设" in text
    assert "先列出当前仓库目录结构" in text


def test_merge_clarified_intent():
    merged = merge_clarified_intent("帮我改一下", "改 runtime.py，减少重复代码")
    assert "[用户原始问题]" in merged
    assert "帮我改一下" in merged
    assert "[用户澄清补充]" in merged
    assert "runtime.py" in merged
