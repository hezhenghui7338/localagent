"""Tests for RetrievalGateway."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from localagent.context.retrieval import get_retrieval_gateway


def test_recall_warm_returns_hits(isolated_data):
    gateway = get_retrieval_gateway()
    with patch(
        "localagent.context.retrieval.gateway.get_memory_backend"
    ) as get_backend:
        backend = MagicMock()
        backend.backend_name.return_value = "json"
        backend.recall.return_value = [
            {"text": "我喜欢美式咖啡", "score": 0.9, "metadata": {}},
        ]
        get_backend.return_value = backend
        out = gateway.recall_warm("咖啡", top_k=3, fallback=False)
    assert "美式" in out
    backend.recall.assert_called_once()


def test_search_cold_miss_without_fallback(isolated_data):
    gateway = get_retrieval_gateway()
    with patch(
        "localagent.knowledge.hybrid.get_hybrid_retriever"
    ) as get_retriever:
        retriever = MagicMock()
        retriever.retrieve.return_value = []
        get_retriever.return_value = retriever
        out = gateway.search_cold("不存在的话题", fallback=False)
    assert out.startswith("未找到")


def test_tools_search_memory_delegates_to_gateway(isolated_data):
    from localagent.tools import search_memory

    with patch(
        "localagent.context.retrieval.get_retrieval_gateway"
    ) as get_gw:
        gw = MagicMock()
        gw.recall_warm.return_value = "命中"
        get_gw.return_value = gw
        out = search_memory("test", fallback=False)
    assert out == "命中"
    gw.recall_warm.assert_called_once()
