"""Background parallel segment summarization for segment-mode documents."""

from __future__ import annotations

import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from localagent import config
from localagent.summarize.segment_reader import (
    ReadingProgress,
    summarize_segment,
)

if TYPE_CHECKING:
    from localagent.summarize.document import SummarizeResult

SegmentUpdateCallback = Callable[[int, str], None]
PersistCallback = Callable[[], None]


@dataclass
class PrefetchSnapshot:
    enabled: bool
    running: bool
    done_count: int
    total: int
    running_index: int | None
    active_workers: int = 0
    running_indices: frozenset[int] = field(default_factory=frozenset)


class SegmentPrefetchWorker:
    """Background pool: summarize pending segments with bounded concurrency."""

    def __init__(
        self,
        result: SummarizeResult,
        *,
        provider: str = "auto",
        use_llm: bool = True,
        max_workers: int | None = None,
        on_update: SegmentUpdateCallback | None = None,
        on_persist: PersistCallback | None = None,
    ) -> None:
        self.result = result
        self.provider = provider
        self.use_llm = use_llm
        self.max_workers = max(
            1, int(max_workers or config.SUMMARIZE_SEGMENT_PREFETCH_WORKERS)
        )
        self.on_update = on_update
        self.on_persist = on_persist
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running_indices: set[int] = set()
        self._executor: ThreadPoolExecutor | None = None
        self._futures: dict[int, Future[str | None]] = {}

    @property
    def progress(self) -> ReadingProgress | None:
        return self.result.reading_progress

    def snapshot(self) -> PrefetchSnapshot:
        progress = self.progress
        if progress is None:
            return PrefetchSnapshot(
                enabled=False,
                running=False,
                done_count=0,
                total=0,
                running_index=None,
                active_workers=0,
            )
        with self._lock:
            indices = frozenset(self._running_indices)
            running_index = min(indices) if indices else None
            return PrefetchSnapshot(
                enabled=bool(progress.prefetch_enabled),
                running=self._thread is not None and self._thread.is_alive(),
                done_count=progress.done_count(),
                total=progress.total,
                running_index=running_index,
                active_workers=len(indices),
                running_indices=indices,
            )

    def start(self) -> None:
        progress = self.progress
        if progress is None:
            return
        progress.prefetch_enabled = True
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="segment-prefetch", daemon=True)
        self._thread.start()

    def stop(self, *, join_timeout: float = 2.0) -> None:
        self._stop.set()
        progress = self.progress
        if progress is not None:
            progress.prefetch_enabled = False
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)
        executor = self._executor
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        if progress is not None:
            with self._lock:
                for index in list(self._running_indices):
                    if progress.segment_status_at(index) == "running":
                        self._set_status(progress, index, "pending")
                self._running_indices.clear()
                self._futures.clear()

    def toggle(self) -> bool:
        snap = self.snapshot()
        if snap.running and self.progress and self.progress.prefetch_enabled:
            self.stop()
            return False
        self.start()
        return True

    def retry_segment(self, index: int) -> bool:
        """Reset a segment and ensure prefetch picks it up again."""
        progress = self.progress
        if progress is None:
            return False
        with self._lock:
            if index in self._futures or index in self._running_indices:
                return False
        from localagent.summarize.segment_reader import reset_segment_for_retry

        if not reset_segment_for_retry(progress, index):
            return False
        if self.on_persist:
            self.on_persist()
        snap = self.snapshot()
        if not snap.running:
            self.start()
        return True

    def _summarize_one(self, index: int) -> str | None:
        progress = self.progress
        if progress is None:
            return None
        try:
            return summarize_segment(
                progress.segments[index],
                filename=self.result.filename,
                use_llm=self.use_llm,
            )
        except Exception:
            return None

    def _run(self) -> None:
        progress = self.progress
        if progress is None:
            return
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            self._executor = pool
            try:
                while True:
                    if self._stop.is_set() and not self._futures:
                        break
                    if not self._stop.is_set():
                        self._fill_pool(progress, pool)
                    if not self._futures:
                        if self._stop.is_set() or self._next_pending_index(progress) is None:
                            break
                        time.sleep(0.05)
                        continue
                    done, _ = wait(
                        list(self._futures.values()),
                        timeout=0.25,
                        return_when=FIRST_COMPLETED,
                    )
                    if not done and not self._stop.is_set():
                        continue
                    for index in list(self._futures.keys()):
                        fut = self._futures.get(index)
                        if fut is None or not fut.done():
                            continue
                        self._finish_future(progress, index, fut)
            finally:
                self._executor = None
                with self._lock:
                    self._futures.clear()
                    self._running_indices.clear()

    def _fill_pool(self, progress: ReadingProgress, pool: ThreadPoolExecutor) -> None:
        while not self._stop.is_set():
            with self._lock:
                if len(self._futures) >= self.max_workers:
                    return
                next_idx = self._next_pending_index(
                    progress,
                    skip=set(self._futures.keys()) | self._running_indices,
                )
                if next_idx is None:
                    return
                self._running_indices.add(next_idx)
                self._set_status(progress, next_idx, "running")
                self._futures[next_idx] = pool.submit(self._summarize_one, next_idx)

    def _finish_future(
        self,
        progress: ReadingProgress,
        index: int,
        fut: Future[str | None],
    ) -> None:
        summary: str | None = None
        try:
            summary = fut.result()
        except Exception:
            summary = None
        with self._lock:
            self._futures.pop(index, None)
            self._running_indices.discard(index)
        if summary is None or not str(summary).strip():
            with self._lock:
                if self._stop.is_set():
                    if progress.segment_status_at(index) == "running":
                        self._set_status(progress, index, "pending")
                else:
                    self._set_status(progress, index, "failed")
            return
        with self._lock:
            while len(progress.segment_summaries) <= index:
                progress.segment_summaries.append("")
            progress.segment_summaries[index] = summary
            self._set_status(progress, index, "done")
        if self.on_update:
            self.on_update(index, summary)
        if self.on_persist:
            self.on_persist()

    @staticmethod
    def _next_pending_index(
        progress: ReadingProgress,
        *,
        skip: set[int] | None = None,
    ) -> int | None:
        blocked = skip or set()
        for idx in range(progress.total):
            if idx in blocked:
                continue
            status = progress.segment_status_at(idx)
            if status in {"pending", "failed"}:
                return idx
        return None

    @staticmethod
    def _set_status(progress: ReadingProgress, index: int, status: str) -> None:
        progress.set_segment_status(index, status)


def attach_prefetch_worker(
    result: SummarizeResult,
    *,
    provider: str = "auto",
    use_llm: bool = True,
    enabled: bool = True,
    max_workers: int | None = None,
    on_update: SegmentUpdateCallback | None = None,
    on_persist: PersistCallback | None = None,
) -> SegmentPrefetchWorker | None:
    """Create and optionally start a prefetch worker for segment-mode results."""
    if not result.segment_mode or result.reading_progress is None:
        return None
    worker = SegmentPrefetchWorker(
        result,
        provider=provider,
        use_llm=use_llm,
        max_workers=max_workers,
        on_update=on_update,
        on_persist=on_persist,
    )
    if enabled:
        worker.start()
    return worker
