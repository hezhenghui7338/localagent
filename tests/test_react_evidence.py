"""Tests for turn-level working evidence in the ReAct loop."""

from __future__ import annotations

from localagent.agent.react_loop import run_react_loop
from localagent.models.router import ChatMessage


def test_react_loop_refreshes_system_with_evidence(isolated_data):
    read_tool = '```tool\n{"name": "read_file", "arguments": {"path": "a.py"}}\n```'
    grep_tool = '```tool\n{"name": "grep", "arguments": {"pattern": "timeout"}}\n```'
    captured: list[list[ChatMessage]] = []
    router = isolated_data["router"]

    def chat_side_effect(messages, **_kwargs):
        captured.append(list(messages))
        n = len(captured)
        if n == 1:
            return read_tool
        if n == 2:
            return grep_tool
        return "timeout 在 a.py 第 10 行"

    router.chat.side_effect = chat_side_effect

    def rebuild_system(**kwargs):
        base = "BASE"
        turn_evidence = kwargs.get("turn_evidence") or ""
        return f"{base}\n{turn_evidence}".strip()

    messages = [
        ChatMessage(role="system", content="BASE"),
        ChatMessage(role="user", content="timeout 在哪"),
    ]

    result = run_react_loop(
        messages=messages,
        user_message="timeout 在哪",
        router=router,
        prefer="ollama",
        session_id="s-evidence",
        max_iterations=5,
        on_status=None,
        on_token=None,
        gated_execute=lambda name, args: (
            "10: timeout = 30" if name == "read_file" else "a.py:10:timeout=30"
        ),
        rebuild_system=rebuild_system,
        goal="timeout 在哪",
    )

    assert "timeout" in result.response.lower()
    assert len(result.tool_calls) == 2
    final_system = captured[-1][0].content
    assert "【当前目标】" in final_system
    assert "【已收集证据】" in final_system
    assert "read_file" in final_system
    assert "grep" in final_system


def test_react_loop_cloud_tier_keeps_two_full_observations(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.OBSERVE_KEEP_FULL_ROUNDS_CLOUD", 2)
    tools = [
        '```tool\n{"name": "read_file", "arguments": {"path": "a.py"}}\n```',
        '```tool\n{"name": "grep", "arguments": {"pattern": "one"}}\n```',
        '```tool\n{"name": "glob", "arguments": {"pattern": "*.py"}}\n```',
        "扫描完成，已在 a.py 中找到相关匹配。",
    ]
    state = {"n": 0}
    router = isolated_data["router"]

    captured_before_final: list[ChatMessage] = []

    def chat_side_effect(messages, **_kwargs):
        reply = tools[state["n"]]
        state["n"] += 1
        if state["n"] == 4:
            captured_before_final.extend(messages)
        return reply

    router.chat.side_effect = chat_side_effect
    router.last_provider = "openrouter"

    run_react_loop(
        messages=[ChatMessage(role="user", content="scan project")],
        user_message="scan project",
        router=router,
        prefer="openrouter",
        session_id="s-cloud",
        max_iterations=5,
        on_status=None,
        on_token=None,
        gated_execute=lambda name, args: f"{name} ok",
    )

    full_obs = [
        m.content
        for m in captured_before_final
        if getattr(m, "role", None) == "user"
        and str(m.content).startswith("工具结果:")
    ]
    stubs = [
        m.content
        for m in captured_before_final
        if getattr(m, "role", None) == "user" and "system evidence" in str(m.content)
    ]
    assert len(full_obs) >= 2
    assert stubs


def test_react_loop_repeat_breaker_uses_evidence(isolated_data):
    tool = '```tool\n{"name": "grep", "arguments": {"pattern": "timeout"}}\n```'
    router = isolated_data["router"]
    router.chat.side_effect = [tool, tool, "timeout=10"]

    result = run_react_loop(
        messages=[ChatMessage(role="user", content="find timeout")],
        user_message="find timeout",
        router=router,
        prefer="ollama",
        session_id="s-repeat",
        max_iterations=5,
        on_status=None,
        on_token=None,
        gated_execute=lambda name, args: "src/config.py:10:timeout=10",
        rebuild_system=lambda **kwargs: kwargs.get("turn_evidence") or "SYS",
        goal="find timeout",
    )

    assert result.repeat_breaker or "timeout" in result.response.lower()


def test_react_loop_exhausted_when_max_iterations_reached(isolated_data):
    grep_tool = '```tool\n{"name": "grep", "arguments": {"pattern": "x"}}\n```'
    glob_tool = '```tool\n{"name": "glob", "arguments": {"pattern": "*.py"}}\n```'
    router = isolated_data["router"]
    router.chat.side_effect = [grep_tool, glob_tool]

    result = run_react_loop(
        messages=[ChatMessage(role="user", content="search x")],
        user_message="search x",
        router=router,
        prefer="ollama",
        session_id="s-exhaust",
        max_iterations=2,
        on_status=None,
        on_token=None,
        gated_execute=lambda name, args: "no match",
    )

    assert result.exhausted
    assert len(result.tool_calls) == 2
