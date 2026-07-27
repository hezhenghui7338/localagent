"""On-disk cache for per-segment summarize cards (JSON + readable Markdown)."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from localagent import config
from localagent.summarize.segment_reader import ReadingBudget, ReadingProgress
from localagent.summarize.sessions import file_mtime
from localagent.tzutil import local_now

if TYPE_CHECKING:
    from localagent.summarize.document import SummarizeResult

_CACHE_VERSION = 1
_LARGE_DOC_SEGMENTS = 500
_FULL_MD_EVERY = 50


@dataclass(frozen=True)
class SegmentCacheLoad:
    loaded: bool
    done_count: int
    total: int
    md_path: Path | None = None
    retry_reset_count: int = 0


def cache_dir() -> Path:
    config.ensure_data_dirs()
    path = config.SUMMARIZE_SEGMENT_CACHE_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_key(source_path: Path) -> str:
    resolved = str(source_path.expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def cache_paths(source_path: Path) -> tuple[Path, Path]:
    key = cache_key(source_path)
    base = cache_dir()
    return base / f"{key}.json", base / f"{key}.md"


def segment_config_dict(budget: ReadingBudget) -> dict[str, int]:
    return {
        "segment_target": budget.segment_target,
        "segment_max": budget.segment_max,
        "threshold_chars": budget.threshold_chars,
    }


def effective_cache_throttle_sec(*, total_segments: int, base: float | None = None) -> float:
    throttle = base if base is not None else float(config.SUMMARIZE_SEGMENT_CACHE_THROTTLE_SEC)
    if total_segments > _LARGE_DOC_SEGMENTS:
        return max(throttle, 5.0)
    return max(0.05, throttle)


def _normalize_summaries(
    summaries: list[str],
    *,
    total: int,
) -> list[str]:
    out = list(summaries or [])
    while len(out) < total:
        out.append("")
    return out[:total]


def _normalize_statuses(
    statuses: list[str],
    *,
    total: int,
    summaries: list[str],
) -> list[str]:
    out = list(statuses or [])
    while len(out) < total:
        out.append("pending")
    out = out[:total]
    for idx in range(total):
        if summaries[idx].strip() and out[idx] not in {"running", "failed"}:
            out[idx] = "done"
    return out


def _render_markdown(
    *,
    filename: str,
    source_path: Path,
    progress: ReadingProgress,
    updated_at: str,
    done_only: bool = False,
) -> str:
    done = progress.done_count()
    total = progress.total
    pending = max(0, total - done)
    lines = [
        f"# {filename} · 段摘要缓存",
        "",
        f"> 源文件: {source_path} · {done}/{total} 已完成 · 更新于 {updated_at}",
        "",
    ]
    if done_only and pending:
        lines.append(f"> 另有 {pending} 段待摘要（增量缓存，退出时写入完整版）")
        lines.append("")
    for idx in range(total):
        if done_only and not progress.summary_ready(idx):
            continue
        seg = progress.segments[idx]
        summary = ""
        if idx < len(progress.segment_summaries):
            summary = progress.segment_summaries[idx].strip()
        status = progress.segment_status_at(idx)
        if not summary:
            if status == "running":
                summary = "（摘要生成中…）"
            elif status == "failed":
                summary = "（摘要失败）"
            else:
                summary = "（待摘要）"
        lines.extend([f"## 段 {idx + 1} · {seg.heading}", "", summary, ""])
    return "\n".join(lines).rstrip() + "\n"


def save_segment_cache(
    source_path: Path,
    progress: ReadingProgress,
    *,
    filename: str,
    char_count: int,
    budget: ReadingBudget,
    full_md: bool = False,
) -> Path:
    """Write JSON + Markdown cache atomically; returns Markdown path."""
    json_path, md_path = cache_paths(source_path)
    updated_at = local_now().isoformat(timespec="seconds")
    summaries = _normalize_summaries(progress.segment_summaries, total=progress.total)
    statuses = _normalize_statuses(
        progress.segment_statuses,
        total=progress.total,
        summaries=summaries,
    )
    payload: dict[str, Any] = {
        "version": _CACHE_VERSION,
        "source_path": str(source_path.expanduser().resolve()),
        "mtime": file_mtime(source_path),
        "char_count": int(char_count),
        "total_segments": progress.total,
        "segment_summaries": summaries,
        "segment_statuses": statuses,
        "segment_config": segment_config_dict(budget),
        "updated_at": updated_at,
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    use_done_only = not full_md and progress.total > _LARGE_DOC_SEGMENTS
    md_path.write_text(
        _render_markdown(
            filename=filename,
            source_path=source_path,
            progress=progress,
            updated_at=updated_at,
            done_only=use_done_only,
        ),
        encoding="utf-8",
    )
    return md_path


def load_segment_cache(
    source_path: Path,
    *,
    total_segments: int,
    char_count: int,
    budget: ReadingBudget,
) -> dict[str, Any] | None:
    """Return cache payload when path/mtime/segment config still match."""
    json_path, _md_path = cache_paths(source_path)
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or int(data.get("version") or 0) != _CACHE_VERSION:
        return None
    if str(data.get("source_path") or "") != str(source_path.expanduser().resolve()):
        return None
    if abs(float(data.get("mtime") or 0.0) - file_mtime(source_path)) > 1e-6:
        return None
    if int(data.get("total_segments") or 0) != total_segments:
        return None
    if int(data.get("char_count") or 0) != char_count:
        return None
    cached_cfg = data.get("segment_config")
    if not isinstance(cached_cfg, dict):
        return None
    expected = segment_config_dict(budget)
    for key, value in expected.items():
        if int(cached_cfg.get(key) or 0) != value:
            return None
    return data


def apply_cache_to_progress(progress: ReadingProgress, data: dict[str, Any]) -> int:
    """Hydrate progress from cache; return number of ready segments."""
    total = progress.total
    summaries = _normalize_summaries(
        [str(item) for item in (data.get("segment_summaries") or [])],
        total=total,
    )
    statuses = _normalize_statuses(
        [str(item) for item in (data.get("segment_statuses") or [])],
        total=total,
        summaries=summaries,
    )
    progress.segment_summaries = summaries
    progress.segment_statuses = statuses
    from localagent.summarize.segment_reader import normalize_stale_running_segments

    normalize_stale_running_segments(progress)
    progress.sync_done_count()
    return progress.done_count()


class ThrottledSegmentCacheWriter:
    """Debounce segment cache writes; adaptive throttle for large docs."""

    def __init__(self, *, throttle_sec: float | None = None) -> None:
        self._base_throttle = (
            throttle_sec
            if throttle_sec is not None
            else float(config.SUMMARIZE_SEGMENT_CACHE_THROTTLE_SEC)
        )
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._pending: tuple[Path, ReadingProgress, str, int, ReadingBudget, bool] | None = None
        self._last_full_md_done = 0

    def schedule(
        self,
        source_path: Path,
        progress: ReadingProgress,
        *,
        filename: str,
        char_count: int,
        budget: ReadingBudget,
        full_md: bool = False,
    ) -> None:
        with self._lock:
            self._pending = (source_path, progress, filename, char_count, budget, full_md)
            if self._timer is not None:
                self._timer.cancel()
            delay = effective_cache_throttle_sec(
                total_segments=progress.total,
                base=self._base_throttle,
            )
            self._timer = threading.Timer(delay, self._flush_locked)
            self._timer.daemon = True
            self._timer.start()

    def flush(self, *, full_md: bool = False) -> Path | None:
        with self._lock:
            if self._pending is not None:
                src, prog, name, count, budget, old_full = self._pending
                self._pending = (src, prog, name, count, budget, full_md or old_full)
            return self._flush_locked(force_full_md=full_md)

    def _flush_locked(self, *, force_full_md: bool = False) -> Path | None:
        pending = self._pending
        self._pending = None
        timer = self._timer
        self._timer = None
        if timer is not None:
            timer.cancel()
        if pending is None:
            return None
        source_path, progress, filename, char_count, budget, want_full = pending
        done = progress.done_count()
        full_md = force_full_md or want_full
        if not full_md and progress.total > _LARGE_DOC_SEGMENTS:
            if done - self._last_full_md_done >= _FULL_MD_EVERY:
                full_md = True
        if full_md:
            self._last_full_md_done = done
        return save_segment_cache(
            source_path,
            progress,
            filename=filename,
            char_count=char_count,
            budget=budget,
            full_md=full_md,
        )


def schedule_segment_cache_save(
    writer: ThrottledSegmentCacheWriter,
    result: "SummarizeResult",
    *,
    provider: str = "auto",
    full_md: bool = False,
) -> None:
    progress = result.reading_progress
    if progress is None:
        return
    from localagent.summarize.segment_reader import resolve_reading_budget

    budget = resolve_reading_budget(provider)
    writer.schedule(
        Path(result.path),
        progress,
        filename=result.filename,
        char_count=int(result.char_count or 0),
        budget=budget,
        full_md=full_md,
    )
