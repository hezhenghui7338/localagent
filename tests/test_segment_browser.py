"""Tests for segment browser text rendering."""

from __future__ import annotations

from localagent.i18n import reset_lang_cache
from localagent.summarize.browser import render_segment_browser_text
from localagent.summarize.nav import SegmentNavState
from localagent.summarize.segment_reader import ReadingProgress, build_segments
import pytest


@pytest.fixture(autouse=True)
def _force_zh_ui_lang(monkeypatch):
    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    yield
    reset_lang_cache()


def test_render_segment_browser_text_snapshot():
    text = "\n\n".join(f"## [§S{i}]\n" + ("内容。" * 60) for i in range(4))
    segments = build_segments(text, target_chars=200, segment_max=400, filename="doc.md")
    progress = ReadingProgress(
        segments=segments,
        current_index=1,
        segment_summaries=["sum0", "sum1", "", ""],
        segment_statuses=["done", "done", "pending", "running"],
    )
    state = SegmentNavState(progress=progress, filename="doc.md", index=1)
    rendered = render_segment_browser_text(
        state, prefetch_enabled=True, done_count=2, active_workers=1
    )
    assert "逐段阅读 · doc.md · 2/4 已摘要" in rendered
    assert "> 2." in rendered
    assert "sum1" in rendered
    assert "↑↓ 滚动详情" in rendered or "[/] 切换段" in rendered
    assert "PageDown" in rendered
    assert "后台摘要: 运行中 · 2/4 完成 · 1 路进行中" in rendered


def test_render_segment_browser_prefetch_stopped():
    progress = ReadingProgress(
        segments=[],
        current_index=0,
    )
    state = SegmentNavState(progress=progress, filename="empty.md", index=0)
    rendered = render_segment_browser_text(state, prefetch_enabled=False, done_count=0)
    assert "（无分段）" in rendered
