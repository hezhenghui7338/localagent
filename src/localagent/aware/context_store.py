"""Reduce-layer context artifacts: hot.json (now) + diff.json (since last tick).

Collect writes events; Reduce persists these compact cards for Reason to read.
No LLM calls here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from localagent import config
from localagent.aware.types import AwareEvent, utc_now


def _context_dir() -> Path:
    return Path(getattr(config, "AWARE_CONTEXT_DIR", config.AWARE_DIR / "context"))


def hot_path() -> Path:
    return Path(getattr(config, "AWARE_HOT_FILE", _context_dir() / "hot.json"))


def diff_path() -> Path:
    return Path(getattr(config, "AWARE_DIFF_FILE", _context_dir() / "diff.json"))


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def load_hot() -> dict[str, Any] | None:
    return load_json(hot_path())


def load_diff() -> dict[str, Any] | None:
    return load_json(diff_path())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    config.ensure_data_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _now_from_events(events: list[AwareEvent]) -> dict[str, Any]:
    """Extract apps / media observation from this tick's events."""
    now: dict[str, Any] = {
        "app": "",
        "window_title": "",
        "scene": "",
        "engagement": "",
        "media_title": "",
        "media_artist": "",
        "media_app": "",
        "media_observed": False,
    }
    apps = [e for e in events if e.source == "apps" and e.kind == "apps.focus"]
    if not apps:
        return now
    last = apps[-1]
    media_title = str(last.data.get("media_title") or "").strip()
    now.update(
        {
            "app": str(last.data.get("app") or "").strip(),
            "window_title": str(last.data.get("window_title") or "").strip(),
            "scene": str(last.data.get("scene") or "").strip(),
            "engagement": str(last.data.get("engagement") or "").strip(),
            "media_title": media_title,
            "media_artist": str(last.data.get("media_artist") or "").strip(),
            "media_app": str(last.data.get("media_app") or "").strip(),
            "media_observed": bool(media_title),
        }
    )
    return now


def _enrich_now_live(now: dict[str, Any]) -> dict[str, Any]:
    """If tick had no apps events, best-effort live snapshot when apps granted."""
    if now.get("app") or now.get("media_observed"):
        return now
    try:
        from localagent.aware.profile import SourceGrant, load_profile
        from localagent.aware.sensors.apps import AppsSensor

        if not load_profile().is_granted("apps"):
            return now
        events, _ = AppsSensor(SourceGrant(granted=True)).collect(
            {}, record_activity=False
        )
    except Exception:  # noqa: BLE001
        return now
    if not events:
        return now
    return _now_from_events(events)


def _episode_summaries(limit: int = 12) -> list[dict[str, Any]]:
    from localagent.aware.episode import load_episodes

    rows = []
    for ep in load_episodes(limit=limit):
        rows.append(
            {
                "id": ep.id,
                "scene": ep.scene,
                "source": ep.source,
                "title": ep.title,
                "start": ep.start,
                "end": ep.end,
                "duration_min": ep.duration_min,
                "engagement": str(ep.signals.get("engagement") or ""),
            }
        )
    return rows


def build_hot(
    events: list[AwareEvent],
    *,
    tick_at: str | None = None,
) -> dict[str, Any]:
    tick_at = tick_at or utc_now()
    now = _enrich_now_live(_now_from_events(events))
    return {
        "as_of": tick_at,
        "tick_at": tick_at,
        "now": now,
        "recent_episodes": _episode_summaries(),
        "event_count": len(events),
    }


def build_diff(
    prev_hot: dict[str, Any] | None,
    events: list[AwareEvent],
    *,
    tick_at: str | None = None,
) -> dict[str, Any]:
    tick_at = tick_at or utc_now()
    since = str((prev_hot or {}).get("tick_at") or (prev_hot or {}).get("as_of") or "")
    new_files: list[str] = []
    git_changes: list[str] = []
    terminal_cmds: list[str] = []
    other: list[str] = []
    for e in events:
        title = (e.title or "")[:80]
        if e.source == "fs":
            path = str(e.data.get("path") or title)
            new_files.append(path[:120])
        elif e.source == "git":
            git_changes.append(f"{e.kind}: {title}")
        elif e.source == "terminal":
            terminal_cmds.append(title)
        elif e.source in {"apps", "browser"}:
            other.append(f"{e.source}/{e.kind}: {title}")
        else:
            other.append(f"{e.source}/{e.kind}: {title}")

    empty = not (new_files or git_changes or terminal_cmds or other)
    return {
        "as_of": tick_at,
        "since_tick_at": since,
        "until_tick_at": tick_at,
        "empty": empty,
        "new_files": new_files[:20],
        "git_changes": git_changes[:20],
        "terminal_cmds": terminal_cmds[:15],
        "other": other[:20],
        "event_count": len(events),
    }


def refresh_context_artifacts(events: list[AwareEvent]) -> dict[str, Any]:
    """Write hot.json + diff.json after a tick Reduce step. Returns new hot."""
    tick_at = utc_now()
    prev = load_hot()
    hot = build_hot(events, tick_at=tick_at)
    diff = build_diff(prev, events, tick_at=tick_at)
    _write_json(hot_path(), hot)
    _write_json(diff_path(), diff)
    return hot


def format_diff_context_lines(diff: dict[str, Any] | None = None) -> list[str]:
    """Markdown lines for chat injection; empty list when no meaningful delta."""
    d = diff if diff is not None else load_diff()
    if not d:
        return []
    if d.get("empty") and not (
        d.get("new_files") or d.get("git_changes") or d.get("terminal_cmds") or d.get("other")
    ):
        return [
            "### 自上次 tick 以来的变化",
            "- （无新事件）",
        ]
    lines = ["### 自上次 tick 以来的变化"]
    since = str(d.get("since_tick_at") or "").strip()
    until = str(d.get("until_tick_at") or d.get("as_of") or "").strip()
    if since or until:
        lines.append(f"- 窗: {since or '?'} → {until or '?'}")
    for label, key in (
        ("文件", "new_files"),
        ("git", "git_changes"),
        ("终端", "terminal_cmds"),
        ("其它", "other"),
    ):
        items = [str(x) for x in list(d.get(key) or []) if x]
        if not items:
            continue
        for item in items[:8]:
            lines.append(f"- [{label}] {item}")
        if len(items) > 8:
            lines.append(f"- [{label}] …共 {len(items)} 条")
    if len(lines) == 1:
        lines.append("- （无新事件）")
    return lines


def format_hot_as_of_note(hot: dict[str, Any] | None = None) -> list[str]:
    """Optional freshness note when hot snapshot exists."""
    h = hot if hot is not None else load_hot()
    if not h:
        return []
    as_of = str(h.get("as_of") or "").strip()
    if not as_of:
        return []
    return [f"感知快照 as_of: {as_of}（当前应用/正在播放以下方 live 块为准）"]
