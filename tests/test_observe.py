"""Tests for Observe-phase heuristic context compression."""

from __future__ import annotations

from localagent.agent.observe import (
    apply_context_budget,
    budget_prefetch_blocks,
    compact_prior_observations,
    compress_observation,
    truncate_head_tail,
)
from localagent.models.router import ChatMessage


def test_truncate_head_tail_keeps_ends():
    text = "A" * 2000 + "MID" + "B" * 2000
    out = truncate_head_tail(text, limit=500)
    assert len(out) < len(text)
    assert "截断" in out
    assert out.startswith("A")
    assert out.endswith("B")


def test_apply_context_budget_noop_when_short():
    assert apply_context_budget("hello", budget=100) == "hello"


def test_compress_memory_keeps_top_hits_and_budget(monkeypatch):
    monkeypatch.setattr("localagent.config.OBSERVE_BUDGET_CHARS", 800)
    monkeypatch.setattr("localagent.config.OBSERVE_KEEP_HITS", 3)

    cards = []
    for i in range(10):
        cards.append(
            f"### {i + 1}. 标题{i}\n"
            f"相关度 0.9 · 2024-01-01 · 事实 · #tag\n\n"
            + ("很长的记忆正文" * 30)
            + f"\n\n来源: file{i}.md"
        )
    text = "找到 10 条相关记忆（查询: test）\n\n" + ("\n" + "─" * 40 + "\n").join(cards)
    out = compress_observation("search_memory", text, budget=800)
    assert len(out) <= 800
    assert "标题0" in out
    assert "标题2" in out
    assert "省略" in out
    assert "来源: file9" not in out


def test_compress_knowledge_clips_snippets(monkeypatch):
    monkeypatch.setattr("localagent.config.OBSERVE_KEEP_HITS", 4)
    lines = [f"- [{i}] doc{i}.md\n  " + ("snippet" * 50) for i in range(8)]
    text = "命中:\n" + "\n".join(lines)
    out = compress_observation("search_knowledge", text, budget=900)
    assert len(out) <= 900
    assert "doc0.md" in out
    assert "省略" in out


def test_compress_web_drops_stale_keeps_links(monkeypatch):
    monkeypatch.setattr("localagent.config.OBSERVE_BUDGET_CHARS", 600)
    monkeypatch.setattr("localagent.config.OBSERVE_KEEP_HITS", 3)
    text = (
        "【日历今天】2026-07-16\n"
        "【时效核对】匹配 1 条 / 过期 2 条\n"
        "摘要: 今日多云\n"
        "- [匹配·2026-07-16] 深圳天气: " + ("详情" * 80) + "\n"
        "  来源: 深圳天气\n"
        "  链接: https://example.com/weather\n"
        "- [匹配·2026-07-16] 备选: 短内容\n"
        "  来源: 备选\n"
        "  链接: https://example.com/alt\n"
        "已过滤的过期结果:\n"
        "- [过期·2026-03-01] 旧文: 过期内容不应出现\n"
        "  链接: https://example.com/stale\n"
        "【引用要求】必须列出链接"
    )
    out = compress_observation("web_search", text)
    assert "过期内容不应出现" not in out
    assert "https://example.com/stale" not in out
    assert "https://example.com/weather" in out
    assert "深圳天气" in out
    assert len(out) <= 600


def test_compress_shell_prefers_exit_and_tail():
    text = (
        "$ pytest\n"
        "cwd: /tmp\n"
        "exit: 1\n"
        "stdout:\n"
        + ("ok line\n" * 100)
        + "FAILED tests/test_x.py::test_y - AssertionError\n"
    )
    out = compress_observation("run_shell", text, budget=400)
    assert len(out) <= 400
    assert "exit: 1" in out
    assert "FAILED" in out or "AssertionError" in out


def test_compress_write_file_mostly_passthrough():
    msg = "已写入 path=notes.md（32 字符）"
    assert compress_observation("write_file", msg) == msg


def test_budget_prefetch_blocks_priority(monkeypatch):
    monkeypatch.setattr("localagent.config.PREFETCH_BUDGET_CHARS", 500)
    blocks = {
        "personal": "P" * 300,
        "archive": "A" * 300,
        "session": "S" * 300,
        "web": "W" * 300,
        "workspace": "X" * 300,
    }
    out = budget_prefetch_blocks(blocks, budget=500)
    total = sum(len(v) for v in out.values())
    assert total <= 500
    # Highest priority should still be present.
    assert "personal" in out
    assert out["personal"].startswith("P")
    # Lowest priority trimmed or dropped first.
    assert len(out.get("workspace", "")) < 300 or "workspace" not in out


def test_budget_prefetch_blocks_session_first():
    blocks = {
        "personal": "P" * 300,
        "archive": "A" * 300,
        "session": "S" * 300,
    }
    out = budget_prefetch_blocks(blocks, budget=400, session_first=True)
    assert "session" in out
    assert out["session"].startswith("S")
    # personal/archive yield to session when session_first.
    assert sum(len(v) for v in out.values()) <= 400


def test_compact_prior_observations_keeps_latest():
    messages = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="查记忆"),
        ChatMessage(
            role="assistant",
            content='```tool\n{"name": "search_memory", "arguments": {"query": "a"}}\n```',
        ),
        ChatMessage(
            role="user",
            content="工具结果:\n" + ("旧结果很长" * 50) + "\n请回答。",
        ),
        ChatMessage(
            role="assistant",
            content='```tool\n{"name": "web_search", "arguments": {"query": "b"}}\n```',
        ),
        ChatMessage(
            role="user",
            content="工具结果:\n最新联网结果完整保留\n请回答。",
        ),
    ]
    compact_prior_observations(messages)
    assert "已压缩" in messages[3].content
    assert "search_memory" in messages[3].content
    assert messages[2].content == "[已调用工具 search_memory]"
    assert "最新联网结果完整保留" in messages[5].content
    assert "web_search" in messages[4].content or "工具结果" in messages[5].content


def test_compact_noop_with_single_observation():
    messages = [
        ChatMessage(role="assistant", content='```tool\n{"name": "run_shell"}\n```'),
        ChatMessage(role="user", content="工具结果:\nonly one"),
    ]
    compact_prior_observations(messages)
    assert messages[1].content == "工具结果:\nonly one"
