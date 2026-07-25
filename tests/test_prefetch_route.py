"""Tests for centralized JIT prefetch routing."""

from __future__ import annotations

from localagent.agent.prefetch_route import (
    CONFIDENCE_ANCHOR,
    CONFIDENCE_BM25,
    PrefetchRoute,
    is_archive_recall_query,
    is_session_recall_query,
    is_web_query,
    prefetch_header,
    route_prefetch_modules,
)


def test_route_session_beats_archive():
    route = route_prefetch_modules("我上次对话问了啥?")
    assert route.modules == ["session"]
    assert route.session_first is True


def test_route_archive_not_session():
    route = route_prefetch_modules("我以前聊过 Rust 吗")
    assert route.modules == ["archive"]
    assert "session" not in route.modules


def test_route_personal_blocks_web():
    route = route_prefetch_modules("我喜欢喝什么?")
    assert "personal" in route.modules
    assert "web" not in route.modules


def test_route_web_news():
    route = route_prefetch_modules("最近有什么新闻?")
    assert route.modules == ["web"]


def test_route_web_not_personal_conflict():
    route = route_prefetch_modules("今天我喜欢什么?")
    assert "personal" in route.modules
    assert "web" not in route.modules


def test_route_workspace_not_web():
    route = route_prefetch_modules("最近工作区改了啥")
    assert "workspace" in route.modules
    assert "web" not in route.modules


def test_route_weather_overrides_personal_block():
    route = route_prefetch_modules("今天天气怎么样?")
    assert route.modules == ["web"]


def test_route_aware_activity():
    route = route_prefetch_modules("今天下午在忙什么")
    assert "aware" in route.modules


def test_route_session_blocks_web_and_aware():
    route = route_prefetch_modules("今天聊了啥")
    assert route.modules == ["session"]
    assert "web" not in route.modules


def test_is_web_query_domain_vs_temporal():
    assert is_web_query("最近有什么新闻?") is True
    assert is_web_query("Python 怎么写装饰器?") is False
    assert is_web_query("现在几点了") is True


def test_legacy_session_archive_helpers():
    assert is_session_recall_query("我今天问了啥?") is True
    assert is_archive_recall_query("我问过关于关羽的什么问题吗?") is True
    assert is_archive_recall_query("我今天问了啥?") is False


def test_hybrid_bm25_session_paraphrase(monkeypatch):
    monkeypatch.setattr("localagent.config.PREFETCH_ROUTER", "hybrid")
    route = route_prefetch_modules("帮我回忆一下咱们刚才讨论的部署方案")
    assert route.modules == ["session"]
    assert route.source == "bm25"
    assert route.module_confidence["session"] == CONFIDENCE_BM25
    assert not route.forbid_tools("session")


def test_regex_mode_skips_bm25_paraphrase(monkeypatch):
    monkeypatch.setattr("localagent.config.PREFETCH_ROUTER", "regex")
    route = route_prefetch_modules("帮我回忆一下咱们刚才讨论的部署方案")
    assert route.modules == []


def test_forbid_tools_anchor_confidence():
    route = route_prefetch_modules("我今天问了啥?")
    assert route.forbid_tools("session")
    assert route.module_confidence["session"] >= CONFIDENCE_ANCHOR


def test_prefetch_header_soft_when_low_confidence():
    route = PrefetchRoute(module_confidence={"personal": CONFIDENCE_BM25})
    assert (
        prefetch_header(route, "personal", strong="STRONG", soft="SOFT")
        == "SOFT"
    )
    assert (
        prefetch_header(None, "personal", strong="STRONG", soft="SOFT")
        == "STRONG"
    )


def test_prefetch_personal_soft_header():
    from unittest.mock import MagicMock, patch

    from localagent.agent.runtime import _prefetch_personal_context

    route = PrefetchRoute(
        modules=["personal"],
        personal_path="personal",
        module_confidence={"personal": CONFIDENCE_BM25},
        source="bm25",
    )
    with patch(
        "localagent.context.retrieval.get_retrieval_gateway",
    ) as get_gw:
        gw = MagicMock()
        gw.recall_warm.return_value = "未找到相关记忆。"
        gw.search_cold.return_value = "未找到相关知识。"
        get_gw.return_value = gw
        ctx = _prefetch_personal_context("测试问题", path="personal", route=route)
    assert "可优先据此回答" in ctx
    assert "勿再调用" not in ctx.split("\n")[0]
