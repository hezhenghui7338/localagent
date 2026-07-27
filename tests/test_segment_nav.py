"""Tests for segment browser navigation state."""

from __future__ import annotations

from localagent.i18n import reset_lang_cache
from localagent.summarize.nav import SegmentNavState
from localagent.summarize.segment_reader import ReadingProgress, build_segments
import pytest


@pytest.fixture(autouse=True)
def _force_zh_ui_lang(monkeypatch):
    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    yield
    reset_lang_cache()


def _progress(*, total: int = 5, index: int = 2) -> ReadingProgress:
    text = "\n\n".join(f"## [§S{i}]\n" + ("段落。" * 80) for i in range(total))
    segments = build_segments(text, target_chars=200, segment_max=400, filename="t.md")
    summaries = ["sum0"] + [""] * (len(segments) - 1)
    statuses = ["done"] + ["pending"] * (len(segments) - 1)
    if len(segments) >= 2:
        statuses[1] = "running"
    return ReadingProgress(
        segments=segments,
        current_index=index,
        segment_summaries=summaries[: len(segments)],
        segment_statuses=statuses[: len(segments)],
    )


def test_move_wraps_and_clears_message():
    progress = _progress(total=4, index=0)
    state = SegmentNavState(progress=progress, filename="t.md", index=0, message="hint")
    state.move(-1)
    assert state.index == 3
    assert state.message == ""
    state.move(1)
    assert state.index == 0


def test_window_slice_centers_cursor():
    progress = _progress(total=12, index=6)
    state = SegmentNavState(progress=progress, filename="t.md", index=6, list_window=5)
    start, end = state.window_slice()
    assert end - start <= 5
    assert start <= state.index < end


def test_status_icon_reflects_progress():
    progress = _progress(total=4, index=0)
    state = SegmentNavState(progress=progress, filename="t.md", index=0)
    assert state.status_icon(0) == "✓"
    assert state.status_icon(1) == "⟳"
    assert state.status_icon(2) == "·"


def test_detail_text_pending_and_done():
    progress = _progress(total=4, index=0)
    state = SegmentNavState(progress=progress, filename="t.md", index=0)
    assert "sum0" in state.detail_text()
    state.index = 2
    assert state.detail_text() == "摘要待生成…"


def test_detail_text_window_truncates_long_summary():
    progress = _progress(total=4, index=0)
    progress.segment_summaries[0] = "\n".join(f"line {i}" for i in range(40))
    progress.segment_statuses[0] = "done"
    state = SegmentNavState(progress=progress, filename="t.md", index=0)
    window = state.detail_text_window(scroll=0, max_lines=5)
    assert "line 0" in window
    assert "下方还有" in window
    scrolled = state.detail_text_window(scroll=5, max_lines=5)
    assert "line 5" in scrolled
    assert "上方还有" in scrolled
