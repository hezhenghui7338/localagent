"""Tests for RAM detection helpers and model tiers."""

from __future__ import annotations

from localagent.hardware import (
    DEFAULT_TIER_MODEL,
    MINI_OLLAMA_MODEL,
    MODEL_TIERS,
    format_ram_gb,
    model_size_hint,
    recommend_ollama_model,
    tier_for_ram,
)


def _gb(n: float) -> int:
    return int(n * (1024**3))


def test_tier_boundaries():
    assert recommend_ollama_model(_gb(4)) == MINI_OLLAMA_MODEL
    assert recommend_ollama_model(_gb(5.9)) == MINI_OLLAMA_MODEL
    assert recommend_ollama_model(_gb(6)) == "qwen3.5:2b"
    assert recommend_ollama_model(_gb(9.9)) == "qwen3.5:2b"
    assert recommend_ollama_model(_gb(10)) == "qwen3.5:4b"
    assert recommend_ollama_model(_gb(17.9)) == "qwen3.5:4b"
    assert recommend_ollama_model(_gb(18)) == "qwen3.5:9b"
    assert recommend_ollama_model(_gb(32)) == "qwen3.5:9b"


def test_unknown_ram_uses_recommended_tier():
    assert recommend_ollama_model(None) == DEFAULT_TIER_MODEL
    assert tier_for_ram(None).model == DEFAULT_TIER_MODEL
    assert DEFAULT_TIER_MODEL == "qwen3.5:4b"


def test_model_size_hint_and_format():
    assert "GB" in model_size_hint(MINI_OLLAMA_MODEL)
    assert "GB" in model_size_hint("qwen3.5:4b")
    assert "GB" in model_size_hint("qwen3.5:9b")
    assert format_ram_gb(None) == "未知"
    assert format_ram_gb(_gb(16)) == "16 GB"
    assert "GB" in format_ram_gb(_gb(8))


def test_tiers_are_ascending():
    mins = [t.min_ram_bytes for t in MODEL_TIERS]
    assert mins == sorted(mins)
    assert MODEL_TIERS[0].model == MINI_OLLAMA_MODEL
    assert [t.model for t in MODEL_TIERS] == [
        "qwen3.5:0.8b",
        "qwen3.5:2b",
        "qwen3.5:4b",
        "qwen3.5:9b",
    ]
    assert DEFAULT_TIER_MODEL in {t.model for t in MODEL_TIERS}
