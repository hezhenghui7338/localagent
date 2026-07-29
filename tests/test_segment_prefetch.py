"""Tests for background segment prefetch worker."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from localagent.summarize.document import SummarizeResult
from localagent.summarize.model_choice import SegmentSource, SummarizeModelChoice
from localagent.summarize.segment_prefetch import (
    SegmentPrefetchWorker,
    resolve_segment_prefetch_workers,
)
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


def _mock_summary(segment, *, filename="", use_llm=True, **kwargs):
    return f"sum{segment.index}", SegmentSource(via="heuristic" if not use_llm else "llm")


def test_prefetch_worker_stop_and_start(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "localagent.summarize.segment_reader.summarize_segment",
        _mock_summary,
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

    def fake_summarize(segment, *, filename="", use_llm=True, **kwargs):
        calls.append(segment.index)
        return _mock_summary(segment, filename=filename, use_llm=use_llm)

    monkeypatch.setattr(
        "localagent.summarize.segment_reader.summarize_segment",
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

    def slow_summarize(segment, *, filename="", use_llm=True, **kwargs):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.08)
        with lock:
            in_flight -= 1
        return _mock_summary(segment, filename=filename, use_llm=use_llm)

    monkeypatch.setattr(
        "localagent.summarize.segment_reader.summarize_segment",
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

    def blocking_summarize(segment, *, filename="", use_llm=True, **kwargs):
        gate.wait(timeout=2.0)
        return _mock_summary(segment, filename=filename, use_llm=use_llm)

    monkeypatch.setattr(
        "localagent.summarize.segment_reader.summarize_segment",
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


def test_resolve_prefetch_workers_ollama_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LA_SUMMARIZE_SEGMENT_PREFETCH_WORKERS", raising=False)
    choice = SummarizeModelChoice(provider="ollama")
    assert resolve_segment_prefetch_workers(choice) == 1
    worker = SegmentPrefetchWorker(_result(), model_choice=choice, use_llm=False)
    assert worker.max_workers == 1


def test_resolve_prefetch_workers_openrouter_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LA_SUMMARIZE_SEGMENT_PREFETCH_WORKERS", raising=False)
    choice = SummarizeModelChoice(provider="openrouter")
    assert resolve_segment_prefetch_workers(choice) == 8
    worker = SegmentPrefetchWorker(_result(), model_choice=choice, use_llm=False)
    assert worker.max_workers == 8


def test_resolve_prefetch_workers_auto_resolves_to_ollama(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("LA_SUMMARIZE_SEGMENT_PREFETCH_WORKERS", raising=False)

    class FakeRouter:
        def resolve_effective_provider(self, choice: str) -> str:
            assert choice == "auto"
            return "ollama"

    monkeypatch.setattr(
        "localagent.models.router.get_model_router",
        lambda: FakeRouter(),
    )
    choice = SummarizeModelChoice(provider="auto")
    assert resolve_segment_prefetch_workers(choice) == 1


def test_resolve_prefetch_workers_env_overrides_ollama(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LA_SUMMARIZE_SEGMENT_PREFETCH_WORKERS", "4")
    choice = SummarizeModelChoice(provider="ollama")
    assert resolve_segment_prefetch_workers(choice) == 4
    worker = SegmentPrefetchWorker(_result(), model_choice=choice, use_llm=False)
    assert worker.max_workers == 4


def test_resolve_prefetch_workers_arg_overrides_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LA_SUMMARIZE_SEGMENT_PREFETCH_WORKERS", "4")
    choice = SummarizeModelChoice(provider="ollama")
    assert resolve_segment_prefetch_workers(choice, max_workers=3) == 3
    worker = SegmentPrefetchWorker(
        _result(),
        model_choice=choice,
        use_llm=False,
        max_workers=3,
    )
    assert worker.max_workers == 3
