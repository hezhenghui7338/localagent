"""Persist summarize document-session metadata for --list / --resume."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from localagent import config
from localagent.tzutil import local_now


def _now_iso() -> str:
    return local_now().isoformat(timespec="seconds")


@dataclass
class SummarizeSessionRecord:
    id: str
    path: str
    filename: str
    mtime: float
    updated_at: str
    conversation_session_id: str
    summary_md: str = ""
    char_count: int = 0
    page_count: int | None = None
    kept: bool = False
    keep_target: str | None = None
    segment_mode: bool = False
    current_segment_index: int = 0
    segment_summaries: list[str] = field(default_factory=list)
    compressed_prior: str = ""
    segment_statuses: list[str] = field(default_factory=list)
    prefetch_enabled: bool = True
    cache_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SummarizeSessionRecord:
        raw_summaries = data.get("segment_summaries")
        summaries: list[str] = []
        if isinstance(raw_summaries, list):
            summaries = [str(item) for item in raw_summaries]
        raw_statuses = data.get("segment_statuses")
        statuses: list[str] = []
        if isinstance(raw_statuses, list):
            statuses = [str(item) for item in raw_statuses]
        return cls(
            id=str(data.get("id") or ""),
            path=str(data.get("path") or ""),
            filename=str(data.get("filename") or ""),
            mtime=float(data.get("mtime") or 0.0),
            updated_at=str(data.get("updated_at") or ""),
            conversation_session_id=str(
                data.get("conversation_session_id") or data.get("id") or ""
            ),
            summary_md=str(data.get("summary_md") or ""),
            char_count=int(data.get("char_count") or 0),
            page_count=data.get("page_count") if data.get("page_count") is not None else None,
            kept=bool(data.get("kept")),
            keep_target=str(data["keep_target"]) if data.get("keep_target") else None,
            segment_mode=bool(data.get("segment_mode")),
            current_segment_index=int(data.get("current_segment_index") or 0),
            segment_summaries=summaries,
            compressed_prior=str(data.get("compressed_prior") or ""),
            segment_statuses=statuses,
            prefetch_enabled=bool(data.get("prefetch_enabled", True)),
            cache_path=str(data.get("cache_path") or ""),
        )


def _empty_index() -> dict[str, Any]:
    return {"sessions": []}


def _load_index() -> dict[str, Any]:
    config.ensure_data_dirs()
    path = config.SUMMARIZE_SESSIONS_INDEX
    if not path.exists():
        return _empty_index()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_index()
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
        return _empty_index()
    return data


def _save_index(data: dict[str, Any]) -> None:
    config.ensure_data_dirs()
    path = config.SUMMARIZE_SESSIONS_INDEX
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def new_summarize_session_id() -> str:
    return f"sum-{uuid.uuid4().hex[:10]}"


def file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def upsert_session(record: SummarizeSessionRecord) -> SummarizeSessionRecord:
    data = _load_index()
    sessions: list[dict[str, Any]] = list(data.get("sessions") or [])
    payload = asdict(record)
    payload["updated_at"] = _now_iso()
    record.updated_at = payload["updated_at"]

    # Drop any existing entry with same id or same path, then insert at front.
    sessions = [
        item
        for item in sessions
        if str(item.get("id") or "") != record.id
        and str(item.get("path") or "") != record.path
    ]
    sessions.insert(0, payload)
    data["sessions"] = sessions[:50]
    _save_index(data)
    return record


def get_session(session_id: str) -> SummarizeSessionRecord | None:
    sid = (session_id or "").strip()
    if not sid:
        return None
    for item in _load_index().get("sessions") or []:
        if str(item.get("id") or "") == sid:
            return SummarizeSessionRecord.from_dict(item)
    return None


def find_session_by_path(path: str | Path) -> SummarizeSessionRecord | None:
    resolved = str(Path(path).expanduser().resolve())
    for item in _load_index().get("sessions") or []:
        if str(item.get("path") or "") == resolved:
            return SummarizeSessionRecord.from_dict(item)
    return None


def list_sessions(*, limit: int = 20) -> list[SummarizeSessionRecord]:
    items = [
        SummarizeSessionRecord.from_dict(item)
        for item in (_load_index().get("sessions") or [])
    ]
    items.sort(key=lambda r: r.updated_at or "", reverse=True)
    return items[: max(1, limit)]


def count_kept_sessions() -> int:
    """Count summarize sessions marked kept (favorited into Cold kb)."""
    return sum(1 for item in (_load_index().get("sessions") or []) if item.get("kept"))


def record_from_result(
    result: Any,
    *,
    session_id: str,
    conversation_session_id: str | None = None,
) -> SummarizeSessionRecord:
    path = Path(result.path)
    progress = getattr(result, "reading_progress", None)
    segment_mode = bool(getattr(result, "segment_mode", False))
    current_index = 0
    summaries: list[str] = []
    compressed_prior = ""
    statuses: list[str] = []
    prefetch_enabled = True
    cache_path = ""
    if progress is not None:
        segment_mode = True
        current_index = int(getattr(progress, "current_index", 0) or 0)
        compressed_prior = str(getattr(progress, "compressed_prior", "") or "")
        prefetch_enabled = bool(getattr(progress, "prefetch_enabled", True))
        from localagent.summarize.segment_cache import cache_paths

        _, md_path = cache_paths(path)
        cache_path = str(md_path)
    return SummarizeSessionRecord(
        id=session_id,
        path=str(path.resolve()),
        filename=result.filename,
        mtime=file_mtime(path),
        updated_at=_now_iso(),
        conversation_session_id=conversation_session_id or session_id,
        summary_md=result.markdown,
        char_count=int(result.char_count or 0),
        page_count=result.page_count,
        kept=bool(result.kept),
        keep_target=str(result.keep_target) if result.keep_target else None,
        segment_mode=segment_mode,
        current_segment_index=current_index,
        segment_summaries=summaries,
        compressed_prior=compressed_prior,
        segment_statuses=statuses,
        prefetch_enabled=prefetch_enabled,
        cache_path=cache_path,
    )
