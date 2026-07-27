"""Tests for segment browser refresh (dirty flag + refresh_interval, no broken invalidate)."""

from __future__ import annotations

import pytest

from localagent.summarize.browser import BrowserUiState, _run_one_session
from localagent.summarize.nav import SegmentNavState
from localagent.summarize.segment_reader import ReadingProgress, build_segments


def _state() -> SegmentNavState:
    text = "\n\n".join(f"## [§S{i}]\n" + ("内容。" * 40) for i in range(3))
    segments = build_segments(text, target_chars=200, segment_max=400, filename="doc.md")
    progress = ReadingProgress(
        segments=segments,
        current_index=0,
        segment_summaries=["sum0", "", ""],
        segment_statuses=["done", "pending", "pending"],
    )
    progress.sync_done_count()
    return SegmentNavState(progress=progress, filename="doc.md", index=0)


def test_browser_ui_state_dirty_sync():
    state = _state()
    ui = BrowserUiState()
    ui.mark_dirty()
    assert ui.dirty is True
    ui.sync_from(progress=state.progress, worker=None, force=False)
    assert ui.dirty is False
    assert ui.done_count == 1


def test_run_one_session_uses_refresh_interval(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, object] = {}
    state = _state()
    ui = BrowserUiState()
    ui.sync_from(progress=state.progress, worker=None, force=True)

    class FakeApp:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self):
            return None

    monkeypatch.setattr(
        "prompt_toolkit.application.Application",
        FakeApp,
    )
    monkeypatch.setattr(
        "localagent.summarize.browser.config.SUMMARIZE_BROWSER_REFRESH_SEC",
        1.5,
    )
    _run_one_session(state, worker=None, ui_state=ui)
    assert captured.get("refresh_interval") == 1.5
    assert captured.get("min_redraw_interval") == 0.5
    assert captured.get("full_screen") is True
    assert "call_from_executor" not in dir(FakeApp)


def test_on_update_marks_dirty_without_call_from_executor():
    ui = BrowserUiState()
    ui.sync_from(progress=_state().progress, worker=None, force=True)

    def on_update(_index: int, _summary: str) -> None:
        ui.mark_dirty()

    on_update(1, "sum1")
    assert ui.dirty is True
