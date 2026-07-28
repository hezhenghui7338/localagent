"""Tests for segmented document reading in summarize."""

from __future__ import annotations

from pathlib import Path

import pytest

from localagent import config
from localagent.i18n import reset_lang_cache
from localagent.summarize.document import summarize_loaded, summarize_path
from localagent.summarize.segment_reader import (
    ReadingProgress,
    advance_segment,
    build_segments,
    compress_prior_summaries,
    format_segment_context,
    init_reading_progress,
    needs_cross_segment_rag,
    resolve_reading_budget,
    should_use_segment_mode,
)
from localagent.ingest.loader import load_file


@pytest.fixture(autouse=True)
def _force_zh_ui_lang(monkeypatch):
    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    yield
    reset_lang_cache()


def _long_md(tmp_path: Path, *, sections: int = 6, para_len: int = 400) -> Path:
    parts = []
    for i in range(sections):
        parts.append(f"# 章节{i + 1}\n\n" + ("内容段落。" * para_len) + "\n")
    path = tmp_path / "long.md"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def test_build_segments_respects_headings(tmp_path: Path):
    text = (
        "# 第一章\n\n"
        + "短。" * 50
        + "\n\n# 第二章\n\n"
        + "较长内容。" * 200
        + "\n\n# 第三章\n\n"
        + "结尾。" * 50
    )
    segments = build_segments(text, target_chars=800, segment_max=2000, filename="t.md")
    assert len(segments) >= 2
    assert all(seg.text.strip() for seg in segments)
    assert segments[0].index == 0


def test_should_use_segment_mode_threshold(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_THRESHOLD_CHARS", 500)
    assert should_use_segment_mode(400) is False
    assert should_use_segment_mode(600) is True


def test_compress_prior_within_budget():
    budget = resolve_reading_budget("auto")
    segments = build_segments(
        "# A\n\n" + "x" * 1200 + "\n\n# B\n\n" + "y" * 1200,
        target_chars=800,
        segment_max=1600,
        filename="t.md",
    )
    summaries = [
        "## 总结（最多三句话）\n第一句。\n\n## 结构化要点\n- **点**：细节 〔§A〕",
        "## 总结（最多三句话）\n第二句。\n\n## 结构化要点\n- **点**：更多 〔§B〕",
    ]
    compressed = compress_prior_summaries(
        summaries,
        segments,
        budget=budget.prior_budget,
    )
    assert len(compressed) <= budget.prior_budget + 200
    assert "段 1" in compressed
    assert "段 2" in compressed


def test_init_reading_progress_and_advance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_TARGET_CHARS", 800)
    path = _long_md(tmp_path, sections=4, para_len=120)
    doc = load_file(path)
    assert doc is not None
    from localagent.summarize.document import _annotate_for_cite

    annotated = _annotate_for_cite(doc)
    progress, _cache_info = init_reading_progress(
        annotated,
        filename=doc.filename,
        source_path=path,
        char_count=len(annotated),
        use_llm=False,
    )
    assert progress.total >= 2
    assert progress.current_index == 0
    assert progress.current_summary().strip()
    first = progress.current
    nxt = advance_segment(
        progress,
        filename=doc.filename,
        use_llm=False,
        sync_if_missing=True,
    )
    assert nxt is not None
    assert progress.current_index == 1
    assert progress.current is not first
    assert progress.compressed_prior.strip()


def test_summarize_loaded_segment_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SUMMARIZE_SHORT_MAX_CHARS", 500)
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_THRESHOLD_CHARS", 500)
    path = _long_md(tmp_path, sections=3, para_len=60)
    doc = load_file(path)
    assert doc is not None
    result = summarize_loaded(doc, use_llm=False, allow_long=True)
    assert result.segment_mode is True
    assert result.reading_progress is not None
    assert result.reading_progress.total >= 1
    assert any("逐段阅读" in w for w in result.warnings)


def test_short_doc_not_segment_mode(tmp_path: Path):
    path = tmp_path / "short.md"
    path.write_text("# Hi\n\nShort doc.\n", encoding="utf-8")
    result = summarize_path(path, use_llm=False)
    assert result.segment_mode is False
    assert result.reading_progress is None


def test_format_segment_context_includes_current_body():
    from localagent.summarize.document import SummarizeResult

    segments = build_segments(
        "## [§A]\nalpha text\n\n## [§B]\nbeta text",
        target_chars=500,
        segment_max=1000,
        filename="x.md",
    )
    progress = ReadingProgress(
        segments=segments,
        current_index=0,
        segment_summaries=["## 总结（最多三句话）\n段0\n"],
        compressed_prior="",
    )
    result = SummarizeResult(
        markdown=progress.current_summary(),
        path=Path("/tmp/x.md"),
        filename="x.md",
        char_count=100,
        annotated_text="## [§A]\nalpha text",
        segment_mode=True,
        reading_progress=progress,
    )
    block = format_segment_context(result, progress)
    assert "逐段阅读" in block
    assert "当前段原文" in block
    assert "alpha text" in block


def test_needs_cross_segment_rag():
    assert needs_cross_segment_rag("全文讲的是什么？") is True
    assert needs_cross_segment_rag("这段的年终奖怎么算？") is False


def test_set_segment_status_counts_after_summary_written():
    """Prefetch writes summary before marking done; done_count must still increment."""
    progress = ReadingProgress(
        segments=build_segments(
            "## [§A]\n" + "x" * 200 + "\n\n## [§B]\n" + "y" * 200,
            target_chars=200,
            segment_max=400,
            filename="t.md",
        ),
        current_index=0,
        segment_summaries=["sum0"],
        segment_statuses=["done"],
    )
    progress.sync_done_count()
    assert progress.done_count() == 1
    progress.segment_summaries.append("sum1")
    progress.set_segment_status(1, "done")
    assert progress.done_count() == 2


def test_reading_progress_from_session_dict(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_TARGET_CHARS", 200)
    annotated = "\n\n".join(
        f"## [§S{i}]\n" + ("段落内容。" * 120) for i in range(4)
    )
    data = {
        "current_index": 1,
        "segment_summaries": ["sum0", "sum1"],
        "compressed_prior": "prior blob",
    }
    progress = ReadingProgress.from_session_dict(
        data,
        annotated_text=annotated,
        filename="t.md",
    )
    assert progress.current_index == 1
    assert progress.segment_summaries == ["sum0", "sum1"]
    assert progress.compressed_prior == "prior blob"
    assert progress.segment_statuses[0] == "done"
    assert progress.segment_statuses[1] == "done"


def test_record_from_result_persists_segment_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from localagent.summarize.segment_cache import cache_paths
    from localagent.summarize.sessions import get_session, record_from_result, upsert_session

    monkeypatch.setattr(config, "SUMMARIZE_SHORT_MAX_CHARS", 500)
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_THRESHOLD_CHARS", 500)
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_TARGET_CHARS", 800)
    monkeypatch.setattr(config, "SUMMARIZE_SESSIONS_DIR", tmp_path / "summarize_sessions")
    monkeypatch.setattr(
        config,
        "SUMMARIZE_SESSIONS_INDEX",
        tmp_path / "summarize_sessions" / "index.json",
    )
    monkeypatch.setattr(
        config,
        "SUMMARIZE_SEGMENT_CACHE_DIR",
        tmp_path / "summarize_sessions" / "cache",
    )
    path = _long_md(tmp_path, sections=2, para_len=70)
    doc = load_file(path)
    assert doc is not None
    result = summarize_loaded(doc, use_llm=False, allow_long=True)
    assert result.segment_mode
    record = record_from_result(result, session_id="sum-test123")
    upsert_session(record)
    loaded = get_session("sum-test123")
    assert loaded is not None
    assert loaded.segment_mode is True
    assert loaded.current_segment_index == 0
    assert loaded.cache_path
    _, md_path = cache_paths(path)
    assert loaded.cache_path == str(md_path)


def test_summarize_segment_passes_model_choice(monkeypatch: pytest.MonkeyPatch):
    from localagent.models.router import ChatResult
    from localagent.summarize.model_choice import SummarizeModelChoice
    from localagent.summarize.segment_reader import DocumentSegment, summarize_segment

    calls: list[dict] = []

    class FakeRouter:
        def chat_with_meta(self, messages, **kwargs):
            calls.append(kwargs)
            return ChatResult(
                text=(
                    "## 总结（最多三句话）\n"
                    "段摘要。\n\n"
                    "## 结构化要点\n"
                    "- **点**：内容 — 依据：原文 〔§一〕\n"
                ),
                provider="openrouter",
                model="gpt-4o-mini",
            )

    monkeypatch.setattr(
        "localagent.models.router.get_model_router",
        lambda: FakeRouter(),
    )
    seg = DocumentSegment(
        index=0,
        heading="§一",
        text="## [§一]\n段落内容。",
        char_count=20,
        cite_range="§一",
    )
    choice = SummarizeModelChoice(provider="openrouter", model="gpt-4o-mini")
    markdown, source = summarize_segment(seg, filename="t.md", model_choice=choice)
    assert calls[0]["prefer"] == "openrouter"
    assert calls[0]["model"] == "gpt-4o-mini"
    assert "*摘要 via openrouter/gpt-4o-mini*" in markdown
    assert source.via == "llm"


def test_summarize_segment_returns_empty_when_llm_fails(monkeypatch: pytest.MonkeyPatch):
    from localagent.summarize.segment_reader import DocumentSegment, summarize_segment

    class FakeRouter:
        def is_ollama_available(self) -> bool:
            return False

        def chat_with_meta(self, messages, **kwargs):
            raise RuntimeError("down")

    monkeypatch.setattr(
        "localagent.models.router.get_model_router",
        lambda: FakeRouter(),
    )
    seg = DocumentSegment(
        index=0,
        heading="§一",
        text="## [§一]\n段落内容。",
        char_count=20,
        cite_range="§一",
    )
    markdown, source = summarize_segment(seg, filename="t.md", use_llm=True)
    assert markdown == ""
    assert source.via == "failed"
    assert "本地启发式" not in markdown
