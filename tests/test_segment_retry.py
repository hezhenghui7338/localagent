"""Tests for segment summary retry (failed reset + prefetch retry)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from localagent.i18n import reset_lang_cache, t
from localagent.summarize.browser import render_segment_browser_text
from localagent.summarize.document import SummarizeResult
from localagent.summarize.nav import SegmentNavState
from localagent.summarize.segment_prefetch import SegmentPrefetchWorker
from localagent.summarize.segment_reader import (
    ReadingProgress,
    build_segments,
    can_manual_retry_segment,
    reset_failed_segments,
    reset_segment_for_retry,
)


@pytest.fixture(autouse=True)
def _force_zh_ui_lang(monkeypatch):
    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    yield
    reset_lang_cache()


def _progress(*, statuses: list[str], summaries: list[str] | None = None) -> ReadingProgress:
    text = "\n\n".join(
        f"## [§S{i}]\n" + ("内容。" * 80) for i in range(len(statuses))
    )
    segments = build_segments(text, target_chars=200, segment_max=400, filename="doc.md")
    assert len(segments) == len(statuses), f"expected {len(statuses)} segments, got {len(segments)}"
    progress = ReadingProgress(
        segments=segments,
        current_index=0,
        segment_summaries=summaries or ["sum"] * len(statuses),
        segment_statuses=list(statuses),
    )
    progress.sync_done_count()
    return progress


def test_reset_segment_for_retry_skips_running():
    progress = _progress(statuses=["running", "done", "failed"])
    assert reset_segment_for_retry(progress, 0) is False
    assert progress.segment_status_at(0) == "running"


def test_reset_failed_segments_only_resets_failed():
    progress = _progress(
        statuses=["done", "failed", "pending", "failed"],
        summaries=["a", "bad", "", "bad2"],
    )
    reset = reset_failed_segments(progress)
    assert reset == [1, 3]
    assert progress.segment_status_at(0) == "done"
    assert progress.segment_summaries[0] == "a"
    assert progress.segment_status_at(1) == "pending"
    assert progress.segment_summaries[1] == ""
    assert progress.segment_status_at(2) == "pending"
    assert progress.segment_status_at(3) == "pending"
    assert progress.segment_summaries[3] == ""


def test_can_manual_retry_segment():
    progress = _progress(statuses=["done", "failed", "pending"])
    assert can_manual_retry_segment(progress, 0, prefetch_enabled=True) is False
    assert can_manual_retry_segment(progress, 1, prefetch_enabled=True) is True
    assert can_manual_retry_segment(progress, 2, prefetch_enabled=True) is False
    assert can_manual_retry_segment(progress, 2, prefetch_enabled=False) is True


def test_nav_detail_text_includes_retry_hint_for_failed():
    progress = _progress(statuses=["failed"], summaries=[""])
    state = SegmentNavState(progress=progress, filename="doc.md", index=0)
    detail = state.detail_text()
    assert t("summarize.browser_failed") in detail
    assert t("summarize.browser_retry_hint") in detail


def test_render_header_shows_failed_count():
    progress = _progress(statuses=["done", "failed"], summaries=["ok", ""])
    state = SegmentNavState(progress=progress, filename="book.pdf", index=1)
    text = render_segment_browser_text(state)
    assert "1 失败" in text


def test_prefetch_retry_segment_reschedules_failed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "localagent.summarize.segment_prefetch.summarize_segment",
        lambda segment, *, filename="", use_llm=True: f"sum{segment.index}",
    )
    progress = _progress(statuses=["done", "failed", "pending"], summaries=["sum0", "", ""])
    result = SummarizeResult(
        markdown="sum0",
        path=Path("/tmp/t.md"),
        filename="t.md",
        char_count=1000,
        annotated_text="x",
        segment_mode=True,
        reading_progress=progress,
    )
    worker = SegmentPrefetchWorker(result, use_llm=False, max_workers=1)
    assert worker.retry_segment(1) is True
    worker.start()
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if progress.summary_ready(1):
            break
        time.sleep(0.02)
    worker.stop(join_timeout=3.0)
    assert progress.segment_status_at(1) == "done"
    assert progress.segment_summaries[1] == "sum1"
