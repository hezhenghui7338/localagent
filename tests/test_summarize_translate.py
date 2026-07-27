"""Tests for la summarize --deep-translate integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from localagent.summarize.segment_cache import load_segment_cache, segment_config_dict
from localagent.summarize.segment_reader import resolve_reading_budget
from localagent.summarize.translate import (
    TranslateConfig,
    TranslateDependencyError,
    apply_translate_for_summarize,
    is_mostly_chinese,
    needs_translation,
    resolve_translate_config,
    translate_preserving_markers,
)


def test_resolve_translate_config_cli_overrides(monkeypatch):
    monkeypatch.setenv("LA_SUMMARIZE_DEEP_TRANSLATE", "0")
    monkeypatch.setenv("LA_SUMMARIZE_TRANSLATE_TARGET", "zh")
    monkeypatch.setenv("LA_SUMMARIZE_TRANSLATE_SOURCE", "auto")
    cfg = resolve_translate_config(
        deep_translate=True,
        translate_to="en",
        translate_from="de",
    )
    assert cfg.enabled is True
    assert cfg.target == "en"
    assert cfg.source == "de"


def test_is_mostly_chinese():
    assert is_mostly_chinese("这是中文文档内容。" * 10)
    assert not is_mostly_chinese("This is an English document about history." * 10)


def test_needs_translation_skips_chinese_when_target_zh():
    cfg = TranslateConfig(enabled=True, target="zh")
    assert not needs_translation("中文内容" * 20, cfg)
    assert needs_translation("English prose about guns, germs, and steel." * 5, cfg)


def test_translate_preserving_markers_keeps_cite_lines():
    cfg = TranslateConfig(enabled=True, source="en", target="zh")
    text = "## [§Chapter1]\nHello world.\n\n## [§Chapter2]\nSecond paragraph."

    mock_translator = MagicMock()
    mock_translator.translate.side_effect = lambda s: f"译:{s}"
    mock_translator.translate_batch.side_effect = lambda parts: [f"译:{p}" for p in parts]

    with patch(
        "localagent.summarize.translate._translator_for",
        return_value=mock_translator,
    ):
        out, warnings = translate_preserving_markers(text, cfg)

    assert "## [§Chapter1]" in out
    assert "## [§Chapter2]" in out
    assert "译:Hello world." in out
    assert "译:Second paragraph." in out
    assert mock_translator.translate.called or mock_translator.translate_batch.called
    assert warnings == []


def test_apply_translate_for_summarize_skips_chinese_without_calling_api():
    cfg = TranslateConfig(enabled=True, target="zh")
    text = "这是不需要翻译的中文正文。" * 5

    with patch("localagent.summarize.translate._translator_for") as mock_factory:
        out, warnings, translated = apply_translate_for_summarize(text, cfg)

    assert out == text
    assert warnings == []
    assert translated is False
    mock_factory.assert_not_called()


def test_translate_plain_chunks_long_text(monkeypatch):
    from localagent import config

    monkeypatch.setattr(config, "SUMMARIZE_TRANSLATE_CHUNK_CHARS", 50)
    cfg = TranslateConfig(enabled=True, source="en", target="zh")
    long_text = "word " * 200

    mock_translator = MagicMock()
    mock_translator.translate.side_effect = lambda s: f"t:{len(s)}"
    mock_translator.translate_batch.side_effect = lambda parts: [f"t:{len(p)}" for p in parts]

    with patch(
        "localagent.summarize.translate._translator_for",
        return_value=mock_translator,
    ):
        out, warnings = translate_preserving_markers(long_text, cfg)

    assert mock_translator.translate_batch.called
    batches = mock_translator.translate_batch.call_args[0][0]
    assert len(batches) >= 2
    assert "t:" in out
    assert warnings == []


def test_translate_dependency_error_propagates():
    cfg = TranslateConfig(enabled=True, source="en", target="zh")
    with patch(
        "localagent.summarize.translate._translator_for",
        side_effect=TranslateDependencyError("missing deep-translator"),
    ):
        with pytest.raises(TranslateDependencyError, match="missing deep-translator"):
            translate_preserving_markers("English only text here.", cfg)


def test_segment_cache_isolates_translate_settings(tmp_path: Path):
    source = tmp_path / "book.txt"
    source.write_text("placeholder", encoding="utf-8")
    budget = resolve_reading_budget("auto")
    no_translate = TranslateConfig(enabled=False)
    with_translate = TranslateConfig(enabled=True, target="zh", source="auto")

    expected_plain = segment_config_dict(budget, no_translate)
    expected_translated = segment_config_dict(budget, with_translate)
    assert expected_plain["translate_enabled"] == 0
    assert expected_translated["translate_enabled"] == 1

    cached_cfg = {
        "segment_target": budget.segment_target,
        "segment_max": budget.segment_max,
        "threshold_chars": budget.threshold_chars,
        **expected_plain,
    }
    payload = {
        "version": 1,
        "source_path": str(source.resolve()),
        "mtime": source.stat().st_mtime,
        "char_count": 1000,
        "total_segments": 3,
        "segment_config": cached_cfg,
    }
    json_path = tmp_path / "cache.json"
    import json

    json_path.write_text(json.dumps(payload), encoding="utf-8")

    with patch("localagent.summarize.segment_cache.cache_paths", return_value=(json_path, tmp_path / "x.md")):
        with patch("localagent.summarize.segment_cache.file_mtime", return_value=source.stat().st_mtime):
            hit = load_segment_cache(
                source,
                total_segments=3,
                char_count=1000,
                budget=budget,
                translate=no_translate,
            )
            miss = load_segment_cache(
                source,
                total_segments=3,
                char_count=1000,
                budget=budget,
                translate=with_translate,
            )

    assert hit is not None
    assert miss is None


def test_segment_cache_isolates_model_choice(tmp_path: Path):
    from localagent.summarize.model_choice import SummarizeModelChoice

    source = tmp_path / "book.txt"
    source.write_text("placeholder", encoding="utf-8")
    budget = resolve_reading_budget("auto")
    choice_a = SummarizeModelChoice(provider="ollama", model="qwen3:4b")
    choice_b = SummarizeModelChoice(provider="ollama", model="qwen3:8b")

    cached_cfg = segment_config_dict(budget, model_choice=choice_a)
    payload = {
        "version": 3,
        "source_path": str(source.resolve()),
        "mtime": source.stat().st_mtime,
        "char_count": 1000,
        "total_segments": 3,
        "segment_config": cached_cfg,
    }
    json_path = tmp_path / "cache.json"
    import json

    json_path.write_text(json.dumps(payload), encoding="utf-8")

    with patch("localagent.summarize.segment_cache.cache_paths", return_value=(json_path, tmp_path / "x.md")):
        with patch("localagent.summarize.segment_cache.file_mtime", return_value=source.stat().st_mtime):
            hit = load_segment_cache(
                source,
                total_segments=3,
                char_count=1000,
                budget=budget,
                model_choice=choice_a,
            )
            miss = load_segment_cache(
                source,
                total_segments=3,
                char_count=1000,
                budget=budget,
                model_choice=choice_b,
            )

    assert hit is not None
    assert miss is None


def test_summarize_path_with_deep_translate_mock(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LA_SUMMARIZE_DEEP_TRANSLATE", "0")
    path = tmp_path / "english.md"
    path.write_text(
        "# Intro\n\n"
        "Guns, germs, and steel shaped human societies across continents.\n\n"
        "## Chapter\n\n"
        "Agriculture enabled population growth and technological diffusion.\n",
        encoding="utf-8",
    )

    mock_translator = MagicMock()
    mock_translator.translate.side_effect = lambda s: f"[zh]{s[:40]}"

    with patch(
        "localagent.summarize.translate._translator_for",
        return_value=mock_translator,
    ):
        from localagent.summarize.document import summarize_path

        result = summarize_path(
            path,
            keep=False,
            use_llm=False,
            translate=TranslateConfig(enabled=True, target="zh"),
        )

    assert result.translated is True
    assert result.translate_target == "zh"
    assert "## 总结" in result.markdown
    mock_translator.translate.assert_called()
