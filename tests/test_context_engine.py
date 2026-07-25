"""Tests for the turn-level Context Engine."""

from __future__ import annotations

from unittest.mock import patch

from localagent.context.engine import ContextEngine
from localagent.context.router import route_prefetch_modules
from localagent.context.types import ContextBlocks
from localagent.context.working_memory import ReactWorkingMemory


def _empty_blocks() -> ContextBlocks:
    return ContextBlocks()


def test_build_turn_context_assembles_messages():
    engine = ContextEngine()
    with patch(
        "localagent.context.engine.fetch_prefetch_blocks",
        return_value=(_empty_blocks(), {}),
    ):
        ctx = engine.build_turn_context(
            "你好",
            [{"role": "user", "content": "上一轮"}],
            session_id="s-test",
        )

    assert len(ctx.messages) == 3
    assert ctx.messages[0].role == "system"
    assert ctx.messages[1].role == "user"
    assert ctx.messages[1].content == "上一轮"
    assert ctx.messages[2].role == "user"
    assert ctx.messages[2].content == "你好"


def test_jit_routing_session_recall():
    route = route_prefetch_modules("我今天问了啥?")
    assert "session" in route.modules
    assert "web" not in route.modules
    assert route.session_first is True


def test_jit_routing_archive_recall():
    route = route_prefetch_modules("我以前聊过 Rust 吗")
    assert "archive" in route.modules
    assert "web" not in route.modules


def test_jit_routing_personal_recall():
    route = route_prefetch_modules("我喜欢喝什么?")
    assert "personal" in route.modules
    assert "web" not in route.modules


def test_jit_routing_web_recall():
    route = route_prefetch_modules("最近有什么新闻?")
    assert "web" in route.modules
    assert "session" not in route.modules


def test_rebuild_system_accepts_turn_evidence():
    engine = ContextEngine()
    with patch(
        "localagent.context.engine.fetch_prefetch_blocks",
        return_value=(
            ContextBlocks(personal="预加载个人"),
            {"personal": True},
        ),
    ):
        ctx = engine.build_turn_context("我是谁?", history=None, session_id=None)

    rebuilt = ctx.rebuild_system(turn_evidence="[本轮证据]\n- 测试 bullet")
    assert "预加载个人" in rebuilt
    assert "测试 bullet" in rebuilt


def test_history_capped_at_ten():
    engine = ContextEngine()
    history = [{"role": "user", "content": f"msg-{i}"} for i in range(15)]
    with patch(
        "localagent.context.engine.fetch_prefetch_blocks",
        return_value=(_empty_blocks(), {}),
    ):
        ctx = engine.build_turn_context("最新问题", history, session_id=None)

    user_assistant = [m for m in ctx.messages if m.role != "system"]
    assert len(user_assistant) == 11  # 10 history + current user
    assert user_assistant[0].content == "msg-5"
    assert user_assistant[-1].content == "最新问题"


def test_open_working_memory_compresses_observation(monkeypatch):
    monkeypatch.setattr("localagent.config.OBSERVE_BUDGET_CHARS", 400)
    wm = ReactWorkingMemory(
        goal="找 timeout",
        user_query="timeout 在哪",
        prefer="ollama",
    )
    long_text = "工具结果:\n" + ("x" * 800)
    out = wm.compress_tool_observation("read_file", long_text)
    assert len(out) <= 400


def test_open_working_memory_refresh_system():
    from localagent.models.router import ChatMessage

    engine = ContextEngine()
    with patch(
        "localagent.context.engine.fetch_prefetch_blocks",
        return_value=(_empty_blocks(), {}),
    ):
        ctx = engine.build_turn_context("timeout 在哪", history=None, session_id=None)

    wm = ctx.open_working_memory(goal="timeout 在哪", user_query="timeout 在哪")
    wm.append_evidence("grep", "src/a.py:10:timeout=30", arguments={"pattern": "timeout"})
    messages = list(ctx.messages)
    wm.refresh_system(messages)
    assert "【已收集证据】" in messages[0].content
    assert "grep" in messages[0].content
