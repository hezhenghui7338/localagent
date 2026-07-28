"""Tests for on-disk segment summary cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from localagent import config
from localagent.summarize.segment_cache import (
    apply_cache_to_progress,
    cache_paths,
    effective_cache_throttle_sec,
    load_segment_cache,
    save_segment_cache,
    ThrottledSegmentCacheWriter,
)
from localagent.summarize.model_choice import SegmentSource
from localagent.summarize.segment_reader import (
    ReadingProgress,
    build_segments,
    init_reading_progress,
    resolve_reading_budget,
)


@pytest.fixture
def cache_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_CACHE_DIR", cache_dir)
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_CACHE_THROTTLE_SEC", "0.05")
    yield tmp_path


def _progress(total: int = 3) -> ReadingProgress:
    text = "\n\n".join(f"## [§S{i}]\n" + ("段落。" * 80) for i in range(total))
    segments = build_segments(text, target_chars=200, segment_max=400, filename="t.md")
    summaries = [f"sum{i}" for i in range(total)]
    statuses = ["done"] * total
    progress = ReadingProgress(
        segments=segments,
        current_index=0,
        segment_summaries=summaries,
        segment_statuses=statuses,
    )
    progress.sync_done_count()
    return progress


def test_save_and_load_segment_cache(cache_home: Path):
    source = cache_home / "doc.txt"
    source.write_text("hello", encoding="utf-8")
    progress = _progress(total=3)
    budget = resolve_reading_budget("auto")
    md_path = save_segment_cache(
        source,
        progress,
        filename="doc.txt",
        char_count=123,
        budget=budget,
    )
    assert md_path.exists()
    json_path, _ = cache_paths(source)
    assert json_path.exists()
    loaded = load_segment_cache(
        source,
        total_segments=3,
        char_count=123,
        budget=budget,
    )
    assert loaded is not None
    assert loaded["segment_summaries"] == ["sum0", "sum1", "sum2"]


def test_cache_invalid_when_mtime_changes(cache_home: Path):
    source = cache_home / "doc.txt"
    source.write_text("hello", encoding="utf-8")
    progress = _progress(total=2)
    budget = resolve_reading_budget("auto")
    save_segment_cache(
        source,
        progress,
        filename="doc.txt",
        char_count=50,
        budget=budget,
    )
    source.write_text("hello updated", encoding="utf-8")
    assert (
        load_segment_cache(
            source,
            total_segments=2,
            char_count=50,
            budget=budget,
        )
        is None
    )


def test_markdown_export_contains_segment_headings(cache_home: Path):
    source = cache_home / "doc.txt"
    source.write_text("x", encoding="utf-8")
    progress = _progress(total=2)
    budget = resolve_reading_budget("auto")
    md_path = save_segment_cache(
        source,
        progress,
        filename="doc.txt",
        char_count=10,
        budget=budget,
    )
    text = md_path.read_text(encoding="utf-8")
    assert "段摘要缓存" in text
    assert "## 段 1" in text
    assert "sum0" in text


def test_init_reading_progress_uses_cache(
    cache_home: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source = cache_home / "long.md"
    text = "\n\n".join(f"# 章节{i}\n\n" + ("内容。" * 120) for i in range(4))
    source.write_text(text, encoding="utf-8")
    calls: list[int] = []

    def fake_summarize(segment, *, filename="", use_llm=True, **kwargs):
        calls.append(segment.index)
        return f"sum{segment.index}", SegmentSource(via="llm")

    monkeypatch.setattr(
        "localagent.summarize.segment_reader.summarize_segment",
        fake_summarize,
    )
    monkeypatch.setattr(config, "SUMMARIZE_SEGMENT_TARGET_CHARS", 800)
    progress, cache_info = init_reading_progress(
        text,
        filename=source.name,
        source_path=source,
        char_count=len(text),
        use_llm=False,
    )
    assert cache_info is None
    assert calls == [0]
    calls.clear()

    progress2, cache_info2 = init_reading_progress(
        text,
        filename=source.name,
        source_path=source,
        char_count=len(text),
        use_llm=False,
    )
    assert cache_info2 is not None
    assert cache_info2.loaded is True
    assert cache_info2.done_count == 1
    assert cache_info2.total == progress2.total
    assert calls == []


def test_throttled_writer_flushes(cache_home: Path):
    source = cache_home / "doc.txt"
    source.write_text("x", encoding="utf-8")
    progress = _progress(total=2)
    budget = resolve_reading_budget("auto")
    writer = ThrottledSegmentCacheWriter(throttle_sec=0.05)
    writer.schedule(
        source,
        progress,
        filename="doc.txt",
        char_count=10,
        budget=budget,
    )
    md_path = writer.flush()
    assert md_path is not None
    assert md_path.exists()


def test_apply_cache_to_progress_restores_book_context(cache_home: Path):
    progress = _progress(total=2)
    progress.segment_summaries = []
    progress.segment_statuses = []
    data = {
        "segment_summaries": ["a", "b"],
        "segment_statuses": ["done", "pending"],
        "book_context": "## 全书阅读进度\n已完成 1/2 段摘要",
        "book_context_done_count": 1,
    }
    done = apply_cache_to_progress(progress, data)
    assert done == 2
    assert progress.book_context.startswith("## 全书阅读进度")
    assert progress.book_context_done_count == 1


def test_apply_cache_to_progress(cache_home: Path):
    progress = _progress(total=2)
    progress.segment_summaries = []
    progress.segment_statuses = []
    data = {
        "segment_summaries": ["a", "b"],
        "segment_statuses": ["done", "pending"],
    }
    done = apply_cache_to_progress(progress, data)
    assert done == 2
    assert progress.segment_summaries == ["a", "b"]


def test_effective_cache_throttle_large_doc():
    assert effective_cache_throttle_sec(total_segments=600, base=1.0) >= 5.0
    assert effective_cache_throttle_sec(total_segments=10, base=1.0) == 1.0


def _large_progress(*, total: int, done: int) -> ReadingProgress:
    parts = [f"## [§S{i}]\n" + ("段落。" * 120) for i in range(total)]
    text = "\n\n".join(parts)
    segments = build_segments(text, target_chars=200, segment_max=400, filename="big.md")
    seg_total = len(segments)
    summaries = [f"sum{i}" if i < done else "" for i in range(seg_total)]
    statuses = ["done"] * min(done, seg_total) + ["pending"] * max(0, seg_total - done)
    progress = ReadingProgress(
        segments=segments,
        current_index=0,
        segment_summaries=summaries,
        segment_statuses=statuses,
    )
    progress.sync_done_count()
    return progress


def test_large_doc_incremental_markdown(cache_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "localagent.summarize.segment_cache._LARGE_DOC_SEGMENTS",
        2,
    )
    source = cache_home / "big.txt"
    source.write_text("x", encoding="utf-8")
    done = 3
    progress = _large_progress(total=10, done=done)
    seg_total = progress.total
    budget = resolve_reading_budget("auto")
    md_path = save_segment_cache(
        source,
        progress,
        filename="big.txt",
        char_count=999,
        budget=budget,
        full_md=False,
    )
    text = md_path.read_text(encoding="utf-8")
    assert text.count("## 段") == done
    assert f"另有 {seg_total - done} 段待摘要" in text
    assert "（待摘要）" not in text


def test_flush_writes_full_markdown(cache_home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "localagent.summarize.segment_cache._LARGE_DOC_SEGMENTS",
        2,
    )
    source = cache_home / "big.txt"
    source.write_text("x", encoding="utf-8")
    progress = _large_progress(total=10, done=2)
    seg_total = progress.total
    budget = resolve_reading_budget("auto")
    writer = ThrottledSegmentCacheWriter(throttle_sec=0.05)
    writer.schedule(
        source,
        progress,
        filename="big.txt",
        char_count=999,
        budget=budget,
        full_md=False,
    )
    md_path = writer.flush(full_md=True)
    assert md_path is not None
    text = md_path.read_text(encoding="utf-8")
    assert text.count("## 段") == seg_total
