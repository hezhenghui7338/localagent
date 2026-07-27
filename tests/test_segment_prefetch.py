"""Tests for background segment prefetch worker."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from localagent.summarize.document import SummarizeResult
from localagent.summarize.segment_prefetch import SegmentPrefetchWorker
from localagent.summarize.segment_reader import ReadingProgress, build_segments


def _result(*, total: int = 3) -> SummarizeResult:
    text = "\n\n".join(f"## [§S{i}]\n" + ("段落。" * 80) for i in range(total))
    segments = build_segments(text, target_chars=200, segment_max=400, filename="t.md")
    summaries = ["sum0"] + [""] * (total - 1)
    statuses = ["done"] + ["pending"] * (total - 1)
    progress = ReadingProgress(
        segments=segments,
        current_index=0,
        segment_summaries=summaries,
        segment_statuses=statuses,
    )
    return SummarizeResult(
        markdown=summaries[0],
        path=Path("/tmp/t.md"),
        filename="t.md",
        char_count=len(text),
        annotated_text=text,
        segment_mode=True,
        reading_progress=progress,
    )


def test_prefetch_worker_stop_and_start(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "localagent.summarize.segment_prefetch.summarize_segment",
        lambda segment, *, filename="", use_llm=True: f"sum{segment.index}",
    )
    result = _result(total=2)
    worker = SegmentPrefetchWorker(result, use_llm=False)
    worker.start()
    worker.stop(join_timeout=5.0)
    snap = worker.snapshot()
    assert snap.enabled is False
    worker.start()
    worker.stop(join_timeout=5.0)
    progress = result.reading_progress
    assert progress is not None
    assert progress.summary_ready(1)


def test_prefetch_worker_summarizes_pending(monkeypatch: pytest.MonkeyPatch):
    calls: list[int] = []

    def fake_summarize(segment, *, filename="", use_llm=True):
        calls.append(segment.index)
        return f"sum{segment.index}"

    monkeypatch.setattr(
        "localagent.summarize.segment_prefetch.summarize_segment",
        fake_summarize,
    )
    result = _result(total=3)
    progress = result.reading_progress
    assert progress is not None
    worker = SegmentPrefetchWorker(result, use_llm=False, max_workers=1)
    worker.start()
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if progress.summary_ready(1) and progress.summary_ready(2):
            break
        time.sleep(0.02)
    worker.stop(join_timeout=5.0)
    assert sorted(calls) == [1, 2]
    assert progress.summary_ready(1)
    assert progress.summary_ready(2)


def test_prefetch_respects_max_workers(monkeypatch: pytest.MonkeyPatch):
    lock = threading.Lock()
    in_flight = 0
    peak = 0

    def slow_summarize(segment, *, filename="", use_llm=True):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.08)
        with lock:
            in_flight -= 1
        return f"sum{segment.index}"

    monkeypatch.setattr(
        "localagent.summarize.segment_prefetch.summarize_segment",
        slow_summarize,
    )
    result = _result(total=12)
    worker = SegmentPrefetchWorker(result, use_llm=False, max_workers=8)
    worker.start()
    time.sleep(0.35)
    worker.stop(join_timeout=5.0)
    assert peak <= 8
    assert peak >= 2


def test_prefetch_snapshot_active_workers(monkeypatch: pytest.MonkeyPatch):
    gate = threading.Event()

    def blocking_summarize(segment, *, filename="", use_llm=True):
        gate.wait(timeout=2.0)
        return f"sum{segment.index}"

    monkeypatch.setattr(
        "localagent.summarize.segment_prefetch.summarize_segment",
        blocking_summarize,
    )
    result = _result(total=4)
    worker = SegmentPrefetchWorker(result, use_llm=False, max_workers=3)
    worker.start()
    time.sleep(0.15)
    snap = worker.snapshot()
    assert snap.active_workers <= 3
    gate.set()
    worker.stop(join_timeout=5.0)
