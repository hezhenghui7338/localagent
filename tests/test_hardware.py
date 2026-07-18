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
    assert recommend_ollama_model(_gb(6)) == "qwen2.5:1.5b"
    assert recommend_ollama_model(_gb(9.9)) == "qwen2.5:1.5b"
    assert recommend_ollama_model(_gb(10)) == "qwen2.5:3b"
    assert recommend_ollama_model(_gb(13.9)) == "qwen2.5:3b"
    assert recommend_ollama_model(_gb(14)) == DEFAULT_TIER_MODEL
    assert recommend_ollama_model(_gb(32)) == "qwen3.5:4b"


def test_unknown_ram_uses_recommended_tier():
    assert recommend_ollama_model(None) == DEFAULT_TIER_MODEL
    assert tier_for_ram(None).model == DEFAULT_TIER_MODEL


def test_model_size_hint_and_format():
    assert "GB" in model_size_hint(MINI_OLLAMA_MODEL)
    assert "2.5" in model_size_hint("qwen3.5:4b") or "GB" in model_size_hint("qwen3.5:4b")
    assert format_ram_gb(None) == "未知"
    assert format_ram_gb(_gb(16)) == "16 GB"
    assert "GB" in format_ram_gb(_gb(8))


def test_tiers_are_ascending():
    mins = [t.min_ram_bytes for t in MODEL_TIERS]
    assert mins == sorted(mins)
    assert MODEL_TIERS[0].model == MINI_OLLAMA_MODEL
    assert MODEL_TIERS[-1].model == DEFAULT_TIER_MODEL
