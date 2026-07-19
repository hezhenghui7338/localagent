"""Data-layer inventory: Hot / Warm / Cold / Aware for banner and `la status`."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from localagent import config


@dataclass(frozen=True)
class DataLayerStatus:
    """Read-only snapshot of LocalAgent foundation data layers."""

    hot_configured: bool = False
    hot_name: str = ""
    hot_pref_count: int = 0
    hot_anchor_count: int = 0
    hot_updated_at: str = ""
    warm_facts: int = 0
    warm_pending: int = 0
    warm_sources: dict[str, int] = field(default_factory=dict)
    cold_kb_files: int = 0
    cold_chunks: dict[str, int] = field(default_factory=dict)
    cold_chat_sessions: int = 0
    cold_chatgpt_imported: int = 0
    cold_news_bookmarks: int = 0
    cold_summarize_kept: int = 0
    aware_events_today: int = 0
    aware_suggestions: int = 0


def _ingest_index_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        processed = raw.get("processed", {})
        return len(processed) if isinstance(processed, dict) else 0
    except Exception:
        return 0


def _kb_file_count() -> int:
    kb = config.KB_DIR
    if not kb.is_dir():
        return 0
    try:
        return sum(1 for p in kb.iterdir() if p.is_file() or p.is_symlink())
    except OSError:
        return 0


def memory_source_counts() -> dict[str, int]:
    """Count Warm facts by SOURCE_GROUPS origin (chat / chatgpt / file / other)."""
    from localagent.memory.reset import SOURCE_GROUPS
    from localagent.memory.store import get_memory_store

    counts = {"chat": 0, "chatgpt": 0, "file": 0, "other": 0}
    source_to_group: dict[str, str] = {}
    for group, sources in SOURCE_GROUPS.items():
        for src in sources:
            source_to_group[src] = group

    for fact in get_memory_store().all_facts():
        meta = fact.metadata or {}
        src = str(meta.get("source") or "")
        group = source_to_group.get(src, "other")
        counts[group] = counts.get(group, 0) + 1
    return counts


def collect_data_layer_status() -> DataLayerStatus:
    """Gather lightweight layer counts; each subsystem failure is isolated."""
    hot_configured = False
    hot_name = ""
    hot_pref_count = 0
    hot_anchor_count = 0
    hot_updated_at = ""
    try:
        from localagent.memory.core_profile import load_core_profile

        profile = load_core_profile()
        hot_name = (profile.name or "").strip()
        hot_pref_count = len(profile.preferences or {})
        hot_anchor_count = len(profile.life_anchors or [])
        hot_updated_at = (profile.updated_at or "").strip()
        hot_configured = bool(
            hot_name
            or (profile.current_status or "").strip()
            or hot_pref_count
            or hot_anchor_count
        )
    except Exception:
        pass

    warm_facts = 0
    warm_sources: dict[str, int] = {}
    try:
        from localagent.memory.store import get_memory_store

        warm_facts = get_memory_store().count()
        warm_sources = memory_source_counts()
    except Exception:
        warm_facts = 0
        warm_sources = {}

    warm_pending = 0
    try:
        from localagent.pending.queue import pending_count

        warm_pending = pending_count()
    except Exception:
        warm_pending = 0

    cold_kb_files = _kb_file_count()
    cold_chunks: dict[str, int] = {}
    try:
        from localagent.ingest.conversation_cold import count_chunks_by_origin

        cold_chunks = dict(count_chunks_by_origin())
    except Exception:
        cold_chunks = {}

    cold_chat_sessions = 0
    try:
        from localagent.persist.conversations import list_sessions

        cold_chat_sessions = len(list_sessions())
    except Exception:
        cold_chat_sessions = 0

    cold_chatgpt_imported = 0
    try:
        cold_chatgpt_imported = _ingest_index_count(config.CHATGPT_IMPORT_INDEX_FILE)
    except Exception:
        cold_chatgpt_imported = 0

    cold_news_bookmarks = 0
    try:
        from localagent.news.store import NewsStore

        cold_news_bookmarks = NewsStore().count_by_status("bookmarked")
    except Exception:
        cold_news_bookmarks = 0

    cold_summarize_kept = 0
    try:
        from localagent.summarize.sessions import count_kept_sessions

        cold_summarize_kept = count_kept_sessions()
    except Exception:
        cold_summarize_kept = 0

    aware_events = 0
    aware_sug = 0
    try:
        from localagent.aware.store import events_count_today
        from localagent.aware.suggestion import suggestion_count

        aware_events = events_count_today()
        aware_sug = suggestion_count()
    except Exception:
        pass

    return DataLayerStatus(
        hot_configured=hot_configured,
        hot_name=hot_name,
        hot_pref_count=hot_pref_count,
        hot_anchor_count=hot_anchor_count,
        hot_updated_at=hot_updated_at,
        warm_facts=warm_facts,
        warm_pending=warm_pending,
        warm_sources=warm_sources,
        cold_kb_files=cold_kb_files,
        cold_chunks=cold_chunks,
        cold_chat_sessions=cold_chat_sessions,
        cold_chatgpt_imported=cold_chatgpt_imported,
        cold_news_bookmarks=cold_news_bookmarks,
        cold_summarize_kept=cold_summarize_kept,
        aware_events_today=aware_events,
        aware_suggestions=aware_sug,
    )


def format_data_layer_banner_lines(status: DataLayerStatus | None = None) -> list[str]:
    """Short lines for the welcome banner「数据层」section."""
    status = status or collect_data_layer_status()
    if status.hot_configured:
        hot = f"Hot · 已配置 · {status.hot_pref_count}偏好"
        if status.hot_anchor_count:
            hot += f" · {status.hot_anchor_count}锚点"
    else:
        hot = "Hot · 未配置"

    chat_chunks = int(status.cold_chunks.get("chat", 0) or 0)
    chatgpt_chunks = int(status.cold_chunks.get("chatgpt", 0) or 0)
    cold_dialog = chat_chunks + chatgpt_chunks

    return [
        hot,
        f"Warm · {status.warm_facts}事实 · pending {status.warm_pending}",
        (
            f"Cold · kb{status.cold_kb_files} · 对话块{cold_dialog}"
            f" · ChatGPT{status.cold_chatgpt_imported}"
        ),
        f"Aware · 今日{status.aware_events_today}",
        "la status 查看明细",
    ]


def format_data_layer_detail_lines(status: DataLayerStatus | None = None) -> list[str]:
    """Detailed lines for `la status` / `/status`."""
    status = status or collect_data_layer_status()
    if status.hot_configured:
        name = status.hot_name or "—"
        hot = (
            f"Hot   已配置 · {name} · {status.hot_pref_count}偏好"
            f" · {status.hot_anchor_count}锚点"
        )
        if status.hot_updated_at:
            hot += f" · updated {status.hot_updated_at}"
    else:
        hot = "Hot   未配置"

    src = status.warm_sources or {}
    warm = (
        f"Warm  {status.warm_facts}事实 · pending {status.warm_pending}"
        f" · 来源 chat={src.get('chat', 0)} chatgpt={src.get('chatgpt', 0)}"
        f" file={src.get('file', 0)} other={src.get('other', 0)}"
    )

    chunks = status.cold_chunks or {}
    cold = (
        f"Cold  kb={status.cold_kb_files}"
        f" · 块 kb={chunks.get('kb', 0)} chat={chunks.get('chat', 0)}"
        f" chatgpt={chunks.get('chatgpt', 0)}"
        f" · LA会话 {status.cold_chat_sessions}"
        f" · ChatGPT已导入 {status.cold_chatgpt_imported}"
        f" · 收藏 news={status.cold_news_bookmarks}"
        f" summarize={status.cold_summarize_kept}"
    )

    aware = (
        f"Aware 今日事件 {status.aware_events_today}"
        f" · suggestion {status.aware_suggestions}"
    )
    return [hot, warm, cold, aware]


def format_recall_priority_lines() -> list[str]:
    """Explain observe / temporal weighting for users (no retrieval changes)."""
    recency = getattr(config, "RECENCY_HALFLIFE_DAYS", 14)
    time_hl = getattr(config, "TIME_DECAY_HALFLIFE_DAYS", 90)
    return [
        "默认顺序: Hot/Warm(personal) → Cold对话归档(archive) → session → web → workspace → aware",
        (
            f"时间邻近加权已启用（记忆半衰期 {recency:g} 天 / 时间锚衰减 {time_hl:g} 天）；"
            "STM 类问题会把 session 提前"
        ),
    ]
