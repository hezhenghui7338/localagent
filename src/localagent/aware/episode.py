"""Episode layer: sessionize aware events + retrieve context for aware>."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from localagent import config
from localagent.aware.engagement import (
    ENGAGEMENT_ENGAGE,
    ENGAGEMENT_GLANCE,
    episode_attention_score,
    max_engagement,
    tick_interval_minutes,
)
from localagent.aware.timewin import (
    QueryWindow,
    format_now_local,
    format_period_span,
    infer_query_window,
    parse_since,
    parse_ts,
    period_key,
    since_token_to_hours,
    to_local,
)
from localagent.aware.types import AwareEvent, utc_now
from localagent.i18n import t

_CODE_SUFFIXES = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".rs",
        ".go",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".toml",
        ".yaml",
        ".yml",
    }
)
_DOC_SUFFIXES = frozenset(
    {".md", ".markdown", ".txt", ".docx", ".doc", ".rtf", ".pdf", ".csv", ".html", ".htm"}
)


@dataclass
class AwareEpisode:
    id: str
    scene: str
    start: str
    end: str
    duration_min: float
    source: str
    title: str
    entities: list[str] = field(default_factory=list)
    signals: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AwareEpisode:
        return cls(
            id=str(raw.get("id") or ""),
            scene=str(raw.get("scene") or "other"),
            start=str(raw.get("start") or ""),
            end=str(raw.get("end") or ""),
            duration_min=float(raw.get("duration_min") or 0),
            source=str(raw.get("source") or ""),
            title=str(raw.get("title") or ""),
            entities=[str(x) for x in list(raw.get("entities") or [])],
            signals=dict(raw.get("signals") or {}),
            evidence=[str(x) for x in list(raw.get("evidence") or [])],
        )

    def to_card_line(self) -> str:
        dur = f"{self.duration_min:.0f}min" if self.duration_min >= 1 else "<1min"
        eng = str(self.signals.get("engagement") or "")
        scene_bit = f"[{self.scene}/{eng}]" if eng else f"[{self.scene}]"
        when = format_period_span(self.start, self.end or self.start)
        head = f"[{when}] {scene_bit}" if when else scene_bit
        bits = [f"{head} {self.title} ({dur})"]
        if self.entities:
            bits.append(" · " + ", ".join(self.entities[:5]))
        sig = self.signals
        if sig.get("chars_approx"):
            bits.append(t("aware.episode_chars", n=sig["chars_approx"]))
        if sig.get("cmd_count"):
            bits.append(t("aware.episode_cmds", n=sig["cmd_count"]))
        samples = sig.get("samples") if isinstance(sig.get("samples"), list) else []
        if self.source == "browser" and samples:
            short = [str(s)[:40] for s in samples[:3] if s]
            if short:
                bits.append(" · " + " / ".join(short))
        return "".join(bits)


def _episodes_path() -> Path:
    return Path(getattr(config, "AWARE_EPISODES_FILE", config.AWARE_DIR / "episodes.jsonl"))


def _parse_ts(ts: str) -> datetime | None:
    return parse_ts(ts)


def _session_start(rows: list[AwareEvent], *, fallback: str = "") -> str:
    """Prefer data.focus_since (session start) over tick event.ts."""
    for r in rows:
        fs = str(r.data.get("focus_since") or "").strip()
        if fs and _parse_ts(fs):
            return fs
    if rows and rows[0].ts:
        return rows[0].ts
    return fallback or utc_now()


def _session_end(rows: list[AwareEvent]) -> str:
    last = rows[-1]
    for key in ("last_seen_at",):
        val = str(last.data.get(key) or "").strip()
        if val and _parse_ts(val):
            return val
    return last.ts or utc_now()


def _maybe_rotate(path: Path) -> None:
    max_bytes = int(
        getattr(config, "AWARE_EPISODES_MAX_BYTES", 3 * 1024 * 1024) or 3 * 1024 * 1024
    )
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
        bak = path.with_name(path.name + ".1")
        if bak.exists():
            bak.unlink()
        path.replace(bak)
    except OSError:
        return


def stamp_episode_time_signals(ep: AwareEpisode) -> AwareEpisode:
    """Materialize local_day / period / tz_offset_min on write (time is first-class)."""
    local = to_local(ep.start or ep.end)
    if local is None:
        return ep
    sig = dict(ep.signals or {})
    if not str(sig.get("local_day") or "").strip():
        sig["local_day"] = local.date().isoformat()
    if not str(sig.get("period") or "").strip():
        sig["period"] = period_key(ep.start or ep.end)
    if sig.get("tz_offset_min") is None:
        off = local.utcoffset()
        if off is not None:
            sig["tz_offset_min"] = int(off.total_seconds() // 60)
    ep.signals = sig
    return ep


def append_episodes(episodes: list[AwareEpisode]) -> int:
    if not episodes:
        return 0
    config.ensure_data_dirs()
    path = _episodes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _maybe_rotate(path)
    with path.open("a", encoding="utf-8") as fh:
        for ep in episodes:
            stamp_episode_time_signals(ep)
            fh.write(json.dumps(ep.to_dict(), ensure_ascii=False) + "\n")
    return len(episodes)


def _session_collapse_key(ep: AwareEpisode) -> str:
    fk = str(ep.signals.get("focus_key") or "").strip()
    if fk:
        return f"fk:{fk}"
    # Growing tick snapshots share the same start + title prefix.
    return f"{ep.source}|{ep.scene}|{ep.start}|{(ep.title or '')[:60]}"


def collapse_session_episodes(episodes: list[AwareEpisode]) -> list[AwareEpisode]:
    """Drop nested same-session snapshots; keep the longest (usually latest) row."""
    groups: dict[str, list[AwareEpisode]] = {}
    for ep in episodes:
        groups.setdefault(_session_collapse_key(ep), []).append(ep)
    out: list[AwareEpisode] = []
    for rows in groups.values():
        best = max(
            rows,
            key=lambda e: (
                float(e.duration_min or 0),
                e.end or "",
                e.start or "",
            ),
        )
        out.append(best)
    return out


def upsert_episodes(episodes: list[AwareEpisode]) -> int:
    """Update open apps/browser sessions by focus_key; append the rest."""
    if not episodes:
        return 0
    existing = _load_all_episodes()
    # Prefer the latest row per focus_key so a restarted session does not
    # keep updating a finished earlier one.
    index_by_fk: dict[str, int] = {}
    for i, ep in enumerate(existing):
        fk = str(ep.signals.get("focus_key") or "").strip()
        if not fk:
            continue
        prev = index_by_fk.get(fk)
        if prev is None:
            index_by_fk[fk] = i
            continue
        old = existing[prev]
        if (ep.end or ep.start or "") >= (old.end or old.start or ""):
            index_by_fk[fk] = i

    changed = False
    to_append: list[AwareEpisode] = []
    for ep in episodes:
        fk = str(ep.signals.get("focus_key") or "").strip()
        if fk and fk in index_by_fk:
            idx = index_by_fk[fk]
            old = existing[idx]
            # Same continuous session shares focus_since / start.
            if (old.start or "") == (ep.start or ""):
                ep.id = old.id or ep.id
                existing[idx] = ep
                changed = True
                continue
        to_append.append(ep)

    if changed:
        for i, ep in enumerate(existing):
            existing[i] = stamp_episode_time_signals(ep)
        _rewrite_episodes(existing)
    if to_append:
        append_episodes(to_append)
    return len(episodes)


def load_episodes(
    *,
    since: datetime | None = None,
    scene: str | None = None,
    limit: int = 80,
) -> list[AwareEpisode]:
    path = _episodes_path()
    if not path.exists():
        return []
    rows: list[AwareEpisode] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(raw, dict):
                    continue
                ep = AwareEpisode.from_dict(raw)
                if scene and ep.scene != scene:
                    continue
                if since is not None:
                    end = _parse_ts(ep.end) or _parse_ts(ep.start)
                    if end is None or end < since:
                        continue
                rows.append(ep)
    except OSError:
        return []
    rows.sort(key=lambda e: e.end or e.start, reverse=True)
    if limit <= 0:
        return list(reversed(rows))
    return list(reversed(rows[:limit]))


def load_episodes_for_overview(
    *,
    since: datetime | None,
    limit: int = 8,
) -> list[AwareEpisode]:
    """Load full since-window episodes, collapse sessions, stratify by day, rank."""
    from localagent.aware.timewin import to_local

    # limit=0 → no newest-N truncation so multi-day windows stay complete.
    raw_limit = 0 if since is not None else max(limit * 4, 40)
    raw = load_episodes(since=since, limit=raw_limit)
    collapsed = collapse_session_episodes(filter_stale_episodes(raw))
    if not collapsed:
        return []

    by_day: dict[str, list[AwareEpisode]] = {}
    for ep in collapsed:
        local = to_local(ep.end or ep.start)
        day = local.date().isoformat() if local else "unknown"
        by_day.setdefault(day, []).append(ep)

    per_day = max(2, (limit + len(by_day) - 1) // max(1, len(by_day)))
    picked: list[AwareEpisode] = []
    for day in sorted(by_day.keys()):
        day_rows = sorted(
            by_day[day],
            key=episode_attention_score,
            reverse=True,
        )[:per_day]
        picked.extend(day_rows)
    ranked = sorted(picked, key=episode_attention_score, reverse=True)
    return ranked[: max(0, limit)]


def _fs_scene(suffix: str) -> str:
    if suffix in _CODE_SUFFIXES:
        return "coding"
    if suffix in _DOC_SUFFIXES:
        return "writing"
    return "other"


def build_episodes_from_events(events: list[AwareEvent]) -> list[AwareEpisode]:
    """Sessionize a tick's events into lightweight episodes."""
    if not events:
        return []
    out: list[AwareEpisode] = []
    fs_events = [e for e in events if e.source == "fs"]
    term_events = [e for e in events if e.source == "terminal"]
    browser_events = [e for e in events if e.source == "browser"]
    git_events = [e for e in events if e.source == "git"]
    apps_events = [e for e in events if e.source == "apps" and e.kind == "apps.focus"]

    if fs_events:
        by_scene: dict[str, list[AwareEvent]] = {}
        for e in fs_events:
            scene = _fs_scene(str(e.data.get("suffix") or ""))
            by_scene.setdefault(scene, []).append(e)
        for scene, rows in by_scene.items():
            paths = [str(r.data.get("path") or r.title) for r in rows]
            names = [Path(p).name for p in paths]
            chars = sum(int(r.data.get("chars_approx") or 0) for r in rows)
            created = sum(1 for r in rows if r.kind == "file.created")
            modified = sum(1 for r in rows if r.kind == "file.modified")
            start = rows[0].ts
            end = rows[-1].ts
            dur = _duration_min(start, end, fallback_min=max(1.0, len(rows) * 0.5))
            title = t(
                "aware.episode_fs_title",
                scene=scene,
                created=created,
                modified=modified,
            )
            out.append(
                AwareEpisode(
                    id=uuid.uuid4().hex[:12],
                    scene=scene if scene != "other" else "writing",
                    start=start,
                    end=end,
                    duration_min=dur,
                    source="fs",
                    title=title,
                    entities=names[:12],
                    signals={
                        "created": created,
                        "modified": modified,
                        "chars_approx": chars or None,
                        "paths": paths[:12],
                    },
                    evidence=[f"{r.kind}:{r.title}" for r in rows[:12]],
                )
            )

    if term_events:
        cmds = [str(e.data.get("command") or e.title) for e in term_events]
        scene = "coding" if _looks_like_coding(cmds) else "terminal"
        start = term_events[0].ts
        end = term_events[-1].ts
        out.append(
            AwareEpisode(
                id=uuid.uuid4().hex[:12],
                scene=scene,
                start=start,
                end=end,
                duration_min=_duration_min(start, end, fallback_min=float(len(cmds))),
                source="terminal",
                title=t("aware.episode_term_title", n=len(cmds)),
                entities=_cmd_entities(cmds),
                signals={"cmd_count": len(cmds), "commands": cmds[:20]},
                evidence=cmds[:12],
            )
        )

    has_interaction = bool(fs_events or term_events or git_events)

    if browser_events:
        out.extend(_build_browser_episodes(browser_events))

    if apps_events:
        out.extend(_build_apps_episodes(apps_events, has_interaction=has_interaction))

    if git_events:
        out.append(
            AwareEpisode(
                id=uuid.uuid4().hex[:12],
                scene="coding",
                start=git_events[0].ts,
                end=git_events[-1].ts,
                duration_min=_duration_min(
                    git_events[0].ts, git_events[-1].ts, fallback_min=1.0
                ),
                source="git",
                title=t("aware.episode_git_title", n=len(git_events)),
                entities=[e.title for e in git_events[:8]],
                signals={"event_count": len(git_events)},
                evidence=[f"{e.kind}:{e.title}" for e in git_events[:8]],
            )
        )

    return out


def _build_browser_episodes(browser_events: list[AwareEvent]) -> list[AwareEpisode]:
    from localagent.aware.scenes import classify_browser_event_hosts, classify_host

    out: list[AwareEpisode] = []
    summaries = [e for e in browser_events if e.kind == "browser.summary"]
    # Only OS-frontmost viewing heartbeats contribute dwell episodes.
    # browser.selected (background selected tab) is ignored here.
    actives = [
        e
        for e in browser_events
        if e.kind == "browser.active" and e.data.get("viewing") is True
    ]

    for e in summaries:
        hosts: list[str] = []
        samples: list[str] = []
        for row in list(e.data.get("hosts") or []):
            if not isinstance(row, dict) or not row.get("host"):
                continue
            hosts.append(str(row["host"]))
            sample = str(row.get("sample") or "").strip()
            if sample and sample not in samples:
                samples.append(sample)
        scene = classify_browser_event_hosts(hosts)
        visit_count = int(e.data.get("visit_count") or 0)
        # Prefer real visit span when sensor retained visit times.
        first_visit = str(e.data.get("first_visit") or "").strip()
        last_visit = str(e.data.get("last_visit") or "").strip()
        start = first_visit if _parse_ts(first_visit) else e.ts
        end = last_visit if _parse_ts(last_visit) else e.ts
        # History summary = navigation intensity, not dwell.
        duration_min = max(0.5, min(float(tick_interval_minutes()), visit_count * 0.5))
        if _parse_ts(first_visit) and _parse_ts(last_visit):
            duration_min = max(
                duration_min,
                _duration_min(start, end, fallback_min=duration_min),
            )
        hour_buckets = e.data.get("hour_buckets")
        signals: dict[str, Any] = {
            "visit_count": visit_count,
            "engagement": ENGAGEMENT_GLANCE,
        }
        if isinstance(hour_buckets, list) and hour_buckets:
            signals["hour_buckets"] = hour_buckets
        if scene == "sensitive_video":
            out.append(
                AwareEpisode(
                    id=uuid.uuid4().hex[:12],
                    scene=scene,
                    start=start,
                    end=end,
                    duration_min=duration_min,
                    source="browser",
                    title=t("aware.episode_sensitive_browse"),
                    entities=[],
                    signals=signals,
                    evidence=[],
                )
            )
        else:
            out.append(
                AwareEpisode(
                    id=uuid.uuid4().hex[:12],
                    scene=scene,
                    start=start,
                    end=end,
                    duration_min=duration_min,
                    source="browser",
                    title=e.title[:80],
                    entities=hosts[:10],
                    signals={
                        **signals,
                        "samples": samples[:8],
                    },
                    evidence=(samples[:8] or hosts[:10]),
                )
            )

    # Merge same active_url heartbeats within the tick batch.
    by_url: dict[str, list[AwareEvent]] = {}
    for e in actives:
        key = str(e.data.get("active_url") or e.data.get("host") or e.title)
        by_url.setdefault(key, []).append(e)

    for _key, rows in by_url.items():
        last = rows[-1]
        dwell_sec = max(float(r.data.get("dwell_sec") or 0) for r in rows)
        ticks_seen = max(int(r.data.get("ticks_seen") or 1) for r in rows)
        eng = max_engagement(*(str(r.data.get("engagement") or ENGAGEMENT_GLANCE) for r in rows))
        host = str(last.data.get("host") or "")
        scene = str(last.data.get("scene") or "") or (
            classify_host(host, title=str(last.data.get("active_title") or ""))
            if host
            else "browser"
        )
        start = _session_start(rows)
        end = _session_end(rows)
        duration_min = max(dwell_sec / 60.0, 0.5 if ticks_seen else 0.0)
        if scene == "sensitive_video":
            out.append(
                AwareEpisode(
                    id=uuid.uuid4().hex[:12],
                    scene=scene,
                    start=start,
                    end=end,
                    duration_min=duration_min,
                    source="browser",
                    title=t("aware.episode_sensitive_page"),
                    entities=[],
                    signals={
                        "dwell_sec": dwell_sec,
                        "ticks_seen": ticks_seen,
                        "engagement": eng,
                        "visit_count": last.data.get("visit_count"),
                        "viewing": True,
                    },
                    evidence=[],
                )
            )
            continue
        sample = str(last.data.get("sample") or last.data.get("active_title") or "")
        entities = [x for x in [host, sample] if x]
        out.append(
            AwareEpisode(
                id=uuid.uuid4().hex[:12],
                scene=scene,
                start=start,
                end=end,
                duration_min=duration_min,
                source="browser",
                title=last.title[:80],
                entities=entities[:10],
                signals={
                    "active_url": last.data.get("active_url"),
                    "active_title": last.data.get("active_title"),
                    "host": host,
                    "dwell_sec": dwell_sec,
                    "ticks_seen": ticks_seen,
                    "engagement": eng,
                    "visit_count": last.data.get("visit_count"),
                    "samples": [sample] if sample else [],
                    "viewing": True,
                },
                evidence=[sample or host],
            )
        )
    return out


def _build_apps_episodes(
    apps_events: list[AwareEvent], *, has_interaction: bool
) -> list[AwareEpisode]:
    by_key: dict[str, list[AwareEvent]] = {}
    for e in apps_events:
        key = str(e.data.get("focus_key") or e.data.get("app") or e.title or "unknown")
        by_key.setdefault(key, []).append(e)

    out: list[AwareEpisode] = []
    for _key, rows in by_key.items():
        last = rows[-1]
        scene = str(last.data.get("scene") or "other")
        dwell_sec = max(float(r.data.get("dwell_sec") or 0) for r in rows)
        ticks_seen = max(int(r.data.get("ticks_seen") or 1) for r in rows)
        eng = max_engagement(*(str(r.data.get("engagement") or ENGAGEMENT_GLANCE) for r in rows))
        if has_interaction and ticks_seen >= 2 and eng != ENGAGEMENT_ENGAGE:
            eng = ENGAGEMENT_ENGAGE
        elif has_interaction and eng == ENGAGEMENT_GLANCE and ticks_seen >= 2:
            eng = ENGAGEMENT_ENGAGE
        duration_min = max(dwell_sec / 60.0, 0.5 if ticks_seen else 0.0)
        start = _session_start(rows)
        end = _session_end(rows)

        if scene == "sensitive_video":
            out.append(
                AwareEpisode(
                    id=uuid.uuid4().hex[:12],
                    scene=scene,
                    start=start,
                    end=end,
                    duration_min=duration_min,
                    source="apps",
                    title=t("aware.episode_sensitive_fg"),
                    entities=[],
                    signals={
                        "dwell_sec": dwell_sec,
                        "ticks_seen": ticks_seen,
                        "engagement": eng,
                        "focus_samples": len(rows),
                    },
                    evidence=[],
                )
            )
            continue

        apps = [str(r.data.get("app") or "") for r in rows if r.data.get("app")]
        media = next(
            (str(r.data.get("media_title") or "") for r in rows if r.data.get("media_title")),
            "",
        )
        titles = [
            str(r.data.get("window_title") or "")
            for r in rows
            if r.data.get("window_title")
        ]
        entities: list[str] = []
        for x in ([media] if media else []) + apps + titles:
            if x and x not in entities:
                entities.append(x)
        out.append(
            AwareEpisode(
                id=uuid.uuid4().hex[:12],
                scene=scene if scene != "other" else "other",
                start=start,
                end=end,
                duration_min=duration_min,
                source="apps",
                title=last.title[:80],
                entities=entities[:10],
                signals={
                    "app": last.data.get("app"),
                    "media_title": media or None,
                    "media_artist": last.data.get("media_artist"),
                    "idle_seconds": last.data.get("idle_seconds"),
                    "focus_samples": len(rows),
                    "focus_key": last.data.get("focus_key"),
                    "dwell_sec": dwell_sec,
                    "ticks_seen": ticks_seen,
                    "engagement": eng,
                    "input_active": bool(last.data.get("input_active")),
                },
                evidence=[r.title for r in rows[:8]],
            )
        )
    return out


def _duration_min(start: str, end: str, *, fallback_min: float) -> float:
    a = _parse_ts(start)
    b = _parse_ts(end)
    if a and b and b >= a:
        return max(fallback_min, (b - a).total_seconds() / 60.0)
    return fallback_min


def _looks_like_coding(cmds: list[str]) -> bool:
    keys = ("pytest", "python", "npm", "cargo", "go ", "git ", "make", "uv ", "pip ")
    return any(any(k in c.lower() for k in keys) for c in cmds)


def _cmd_entities(cmds: list[str]) -> list[str]:
    out: list[str] = []
    for c in cmds[:12]:
        tok = c.strip().split(maxsplit=1)[0] if c.strip() else ""
        if tok and tok not in out:
            out.append(tok)
    return out[:8]


def is_stale_browser_episode(ep: AwareEpisode) -> bool:
    """True for legacy mislabeled browser dwell or non-viewing browser rows."""
    if ep.source != "browser":
        return False
    title = ep.title or ""
    if title.startswith("前台页:"):
        return True
    if title.startswith("选中标签:"):
        return True
    if ep.signals.get("viewing") is False:
        return True
    return False


def filter_stale_episodes(episodes: list[AwareEpisode]) -> list[AwareEpisode]:
    return [ep for ep in episodes if not is_stale_browser_episode(ep)]


def rank_episodes_by_attention(
    episodes: list[AwareEpisode], *, limit: int = 16
) -> list[AwareEpisode]:
    """Highest attention first; drops stale browser rows and nested sessions."""
    ranked = sorted(
        collapse_session_episodes(filter_stale_episodes(episodes)),
        key=episode_attention_score,
        reverse=True,
    )
    return ranked[: max(0, limit)]


def format_episode_cards(
    episodes: list[AwareEpisode],
    *,
    limit: int = 16,
    by_attention: bool = False,
    by_time: bool = False,
) -> str:
    if not episodes:
        return t("aware.episode_empty")
    if by_attention:
        rows = rank_episodes_by_attention(episodes, limit=limit)
    elif by_time:
        rows = sorted(
            filter_stale_episodes(episodes),
            key=lambda e: e.start or e.end or "",
        )[: max(0, limit)]
    else:
        rows = filter_stale_episodes(episodes)[-limit:]
    if not rows:
        return t("aware.episode_empty")
    lines = [ep.to_card_line() for ep in rows]
    return "\n".join(f"- {ln}" for ln in lines)


def _load_all_episodes() -> list[AwareEpisode]:
    path = _episodes_path()
    if not path.exists():
        return []
    rows: list[AwareEpisode] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, dict):
                    rows.append(AwareEpisode.from_dict(raw))
    except OSError:
        return []
    return rows


def _rewrite_episodes(episodes: list[AwareEpisode]) -> None:
    config.ensure_data_dirs()
    path = _episodes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for ep in episodes:
            fh.write(json.dumps(ep.to_dict(), ensure_ascii=False) + "\n")
    tmp.replace(path)


def purge_stale_episodes() -> int:
    """Drop legacy mislabeled browser dwell cards; keep all other episodes."""
    rows = _load_all_episodes()
    if not rows:
        return 0
    kept = filter_stale_episodes(rows)
    dropped = len(rows) - len(kept)
    if dropped <= 0:
        return 0
    try:
        _rewrite_episodes(kept)
    except OSError:
        return 0
    return dropped


def rebuild_episodes_from_events(*, since_hours: float = 24) -> int:
    """Merge episodes rebuilt from recent events; never drop non-stale cards."""
    from localagent.aware.store import load_events

    hours = max(1.0, float(since_hours))
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    events = load_events(since=since, limit=5000)
    rebuilt = build_episodes_from_events(events)

    kept = filter_stale_episodes(_load_all_episodes())
    keys = {(e.source, e.title, e.start, e.end) for e in kept}
    added = 0
    for ep in rebuilt:
        key = (ep.source, ep.title, ep.start, ep.end)
        if key in keys:
            continue
        kept.append(ep)
        keys.add(key)
        added += 1
    try:
        _rewrite_episodes(kept)
    except OSError:
        return 0
    return added


def maybe_rebuild_stale_episodes(*, since_hours: float = 24) -> int:
    """Purge legacy browser dwell cards; optionally merge fresh builds from events."""
    del since_hours  # purge is file-wide; hours reserved for API stability
    dropped = purge_stale_episodes()
    if dropped <= 0:
        return 0
    try:
        rebuild_episodes_from_events(since_hours=24)
    except Exception:
        pass
    return dropped


def _browser_session_annotation(active_url: str, *, viewing: bool) -> str:
    """Attach dwell/engagement/session-start when browser is viewing that URL."""
    if not active_url:
        return ""
    try:
        from localagent.aware.store import load_cursors

        sess = dict((load_cursors().get("browser") or {}).get("active_session") or {})
    except Exception:
        return ""
    if str(sess.get("active_url") or "") != active_url:
        return ""
    bits: list[str] = []
    focus_since = str(sess.get("focus_since") or "").strip()
    when = format_period_span(focus_since, sess.get("last_seen_at") or focus_since)
    if when:
        bits.append(when)
    if viewing and bool(sess.get("viewing")):
        eng = str(sess.get("engagement") or "")
        dwell_sec = float(sess.get("dwell_sec") or 0)
        if eng:
            bits.append(eng)
        if dwell_sec >= 60:
            bits.append(f"{dwell_sec / 60.0:.0f}min")
        elif dwell_sec > 0:
            bits.append(f"{dwell_sec:.0f}s")
    return f" ({', '.join(bits)})" if bits else ""


def _format_browser_now_context(*, max_other_tabs: int = 8) -> list[str]:
    """Render viewing tab for chat injection; unattended open tabs are omitted."""
    from localagent.aware.browser_tabs import collect_open_tabs
    from localagent.aware.scenes import classify_host, host_from_url

    _ = max_other_tabs  # kept for call-site compat; other open tabs are not attention
    snaps = collect_open_tabs()
    if not snaps:
        return []
    lines: list[str] = ["### 当前浏览器"]
    any_ok = False
    for snap in snaps:
        if snap.error and not snap.active_title and not snap.active_url and not snap.items:
            lines.append(f"- [{snap.browser}] ({snap.error})")
            continue
        any_ok = True
        label = snap.browser or "browser"
        viewing = bool(snap.frontmost)
        if not viewing:
            # Background-open tabs are not attention; omit titles/URLs.
            tab_bit = f" · {snap.tabs}标签" if snap.tabs else ""
            lines.append(f"- [{label}] 非正在看{tab_bit}")
            continue
        active_host = host_from_url(snap.active_url)
        active_scene = (
            classify_host(active_host, title=snap.active_title) if active_host else ""
        )
        sess_bit = _browser_session_annotation(snap.active_url, viewing=True)
        if active_scene == "sensitive_video":
            lines.append(
                f"- [{label}] 正在看: 敏感类标签（已打开）"
                + (f" · {snap.tabs}标签" if snap.tabs else "")
                + sess_bit
            )
        elif snap.active_title or snap.active_url:
            title = (snap.active_title or "(无标题)")[:80]
            url = (snap.active_url or "")[:120]
            bit = f"- [{label}] 正在看: {title}"
            if url:
                bit += f"  {url}"
            bit += sess_bit
            lines.append(bit)
        else:
            lines.append(f"- [{label}] {snap.tabs}标签{sess_bit}")
    if not any_ok and len(lines) == 1:
        return []
    return lines


def _format_apps_now_context() -> list[str]:
    """Frontmost app + Now Playing observation for chat injection (if apps granted)."""
    try:
        from localagent.aware.profile import SourceGrant, load_profile
        from localagent.aware.sensors.apps import AppsSensor

        if not load_profile().is_granted("apps"):
            return []
        # Live read; do not inflate daily input-activity aggregates.
        events, _ = AppsSensor(SourceGrant(granted=True)).collect(
            {}, record_activity=False
        )
    except Exception:
        return []

    lines = ["### 当前应用"]
    if not events:
        lines.append("- （无法读取前台）")
        lines.extend(
            [
                "### 正在播放",
                "- 未观测到",
            ]
        )
        return lines

    e = events[0]
    app = str(e.data.get("app") or "").strip()
    win = str(e.data.get("window_title") or "").strip()
    scene = str(e.data.get("scene") or "").strip()
    eng = str(e.data.get("engagement") or "").strip()
    media_title = str(e.data.get("media_title") or "").strip()
    media_artist = str(e.data.get("media_artist") or "").strip()
    media_app = str(e.data.get("media_app") or "").strip()

    app_bits = [app or "(unknown)"]
    if win:
        app_bits.append(win[:80])
    app_line = " · ".join(app_bits)
    if scene:
        tag = f"{scene}/{eng}" if eng else scene
        app_line += f" [{tag}]"
    lines.append(f"- {app_line}")

    # Always emit an explicit media observation so models cannot infer from frontmost app.
    lines.append("### 正在播放")
    if media_title:
        media_bits = [media_title[:80]]
        if media_artist:
            media_bits.append(media_artist[:60])
        if media_app:
            media_bits.append(f"via {media_app}")
        lines.append("- " + " · ".join(media_bits))
    else:
        lines.append(
            "- 未观测到（仅检测 Spotify/Music 播放中；"
            "无此字段≠用户没在听其它来源）"
        )
    return lines


def retrieve_aware_context(
    query: str = "",
    *,
    since_hours: float | None = None,
    since: str | None = None,
    limit: int = 14,
    include_sensitive: bool = False,
) -> str:
    """Compact card for aware> / optional chat injection.

    Time window: explicit ``since`` token > ``since_hours`` > infer from ``query``.
    Longer horizons prefer daily rollups over raw episode dumps.
    """
    del include_sensitive  # reserved; MVP has no sensitive episode titles
    win = infer_query_window(query, default_token="3h")
    if since:
        try:
            tok = parse_since(since)
            hours = since_token_to_hours(tok)
            prefer_rollup = hours >= 72
            tier = "rollup" if prefer_rollup else ("hot" if hours <= 3 else "episodes")
            win = QueryWindow(
                since_token=tok,
                since_hours=hours,
                tier=tier,
                prefer_rollup=prefer_rollup,
                label="explicit_since",
            )
        except ValueError:
            pass
    elif since_hours is not None:
        hours = max(1.0, float(since_hours))
        prefer_rollup = hours >= 72 or win.prefer_rollup
        win = QueryWindow(
            since_token=win.since_token,
            since_hours=hours,
            tier="rollup" if prefer_rollup else win.tier,
            prefer_rollup=prefer_rollup,
            label=win.label or "explicit_hours",
        )

    since_dt = datetime.now(timezone.utc) - timedelta(hours=max(1.0, win.since_hours))
    ep_limit = max(4, min(limit, 8)) if win.prefer_rollup else limit
    if win.prefer_rollup:
        episodes = load_episodes_for_overview(since=since_dt, limit=ep_limit)
        query_ranked = False
    else:
        episodes = load_episodes(since=since_dt, limit=80)
        q = (query or "").strip().lower()
        query_ranked = False
        if q and episodes:
            tokens = [t for t in re.split(r"\s+", q) if len(t) >= 2]
            scored: list[tuple[int, AwareEpisode]] = []
            for ep in episodes:
                blob = " ".join(
                    [
                        ep.scene,
                        ep.title,
                        ep.source,
                        " ".join(ep.entities),
                        " ".join(ep.evidence),
                        json.dumps(ep.signals, ensure_ascii=False),
                    ]
                ).lower()
                score = sum(1 for t in tokens if t in blob)
                if score:
                    scored.append((score, ep))
            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                episodes = [ep for _s, ep in scored[:ep_limit]]
                query_ranked = True
            else:
                episodes = episodes[-ep_limit:]
        else:
            episodes = episodes[-ep_limit:]

    from localagent.aware.hypothesis import load_hypotheses
    from localagent.aware.rollup import format_rollup_context_lines
    from localagent.aware.suggestion import load_suggestions
    from localagent.status.daily import format_daily_actions_lines

    sug_lines = []
    for item in load_suggestions()[:5]:
        kind = str(item.data.get("kind") or "action")
        sug_lines.append(f"- [{kind}] {item.title}: {item.rationale}")

    hypo_lines = [f"- ({h.confidence:.2f}) {h.claim}" for h in load_hypotheses()[:5]]

    browser_now = _format_browser_now_context()
    apps_now = _format_apps_now_context()

    from localagent.aware.context_store import (
        format_diff_context_lines,
        format_hot_as_of_note,
        load_diff,
        load_hot,
    )

    hot_note = format_hot_as_of_note(load_hot())
    # Diff/hot live blocks matter for near-term; skip noisy diff on long history.
    diff_lines = format_diff_context_lines(load_diff()) if win.since_hours <= 48 else []
    rollup_lines = (
        format_rollup_context_lines(since=since_dt, limit=14)
        if win.prefer_rollup or win.tier == "rollup" or win.since_hours >= 48
        else []
    )

    hours_label = (
        f"{int(win.since_hours)}"
        if float(win.since_hours).is_integer()
        else f"{win.since_hours:g}"
    )
    now_local = format_now_local()
    parts = [
        "## LocalAgent Aware 感知上下文",
        f"当前本地时间: {now_local}",
        f"检索窗: {win.since_token} · tier={win.tier}"
        + (" · 优先日摘要" if win.prefer_rollup else ""),
        "规则: 只根据下列本机感知证据回答；无证据不编造；"
        "缺字段时答「未观测到」，禁止自信否定未列出的行为；"
        "发生时刻/时段是最重要元数据；回答「什么时候」必须引用证据中的本地钟面或时段"
        "（如晚上 22:15、白天上午），禁止仅用「最近/今天上午」等模糊说法；"
        "叙事优先按时段组织（白天/晚上 + 具体钟面），总时长次之；"
        "敏感类不复述片名/URL/站点名，只谈时长与时段聚合；"
        "用户询问本人本机行为时，须据证据如实回答敏感类的时段与时长，"
        "不得因主题敏感拒答或道德说教；"
        "参与度分 glance(掠过)/dwell(停留)/engage(操作)，勿把 glance 当深度使用；"
        "当前应用表示此刻前台，近窗 Episode 表示持续注意力；"
        "「正在播放」无标题 ≠ 用户没在听歌；只能说未观测到播放中媒体"
        "（当前仅检测 Spotify/Music），不得用前台应用推断或否定后台媒体；"
        "询问音乐/正在听什么时，只依据「正在播放」块或 scene=music 的 Episode；"
        "浏览器块仅在标注「正在看」时表示正在浏览；"
        "非正在看/后台打开标签不播报标题，不等于浏览；"
        "前台应用不能用来否定后台浏览器标签；"
        "「自上次 tick 以来的变化」为空时不要编造其它活动；"
        "日摘要为历史聚合，粒度粗于 Episode，勿编造摘要未列出的细节；"
        f"Episode 仅为近 {hours_label} 小时活动，勿当成此刻仍在做的事；"
        "做朋友式建议，不评判。需要改记忆时请用户明确说「记住」。",
    ]
    from localagent.tone import evening_postscript_block

    evening = evening_postscript_block(surface="aware")
    if evening:
        parts.append(evening.rstrip())
    parts.append("")
    if hot_note and win.since_hours <= 48:
        parts.extend([*hot_note, ""])
    # Apps (true frontmost) before browser tabs so attention signal leads.
    if apps_now and win.tier in {"hot", "episodes"} and win.since_hours <= 48:
        parts.extend([*apps_now, ""])
    if browser_now and win.tier in {"hot", "episodes"} and win.since_hours <= 48:
        parts.extend([*browser_now, ""])
    if diff_lines:
        parts.extend([*diff_lines, ""])
    if rollup_lines:
        parts.extend([*rollup_lines, ""])
    ep_cards = (
        format_episode_cards(episodes, limit=ep_limit)
        if query_ranked
        else format_episode_cards(episodes, limit=ep_limit, by_time=True)
    )
    ep_heading = (
        f"### 抽样 Episode（近 {hours_label} 小时 · 历史窗已压缩）"
        if win.prefer_rollup
        else f"### 近期 Episode（时间线 · 最近 {hours_label} 小时）"
    )
    parts.extend(
        [
            ep_heading,
            ep_cards,
            "",
            "### 近期状态",
            *[f"- {ln}" for ln in format_daily_actions_lines()],
        ]
    )
    if hypo_lines:
        parts.extend(["", "### Pending hypotheses", *hypo_lines])
    if sug_lines:
        parts.extend(["", "### Pending suggestions", *sug_lines])
    return "\n".join(parts)


def maybe_enqueue_active_hours_wellness() -> str | None:
    """If today's event hours exceed threshold, enqueue a gentle wellness suggestion."""
    from localagent.aware.store import load_events
    from localagent.aware.suggestion import enqueue, load_suggestions

    threshold = int(getattr(config, "AWARE_ACTIVE_HOURS_WELLNESS", 10) or 10)
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    events = load_events(since=start, limit=2000)
    hours: set[int] = set()
    for e in events:
        dt = _parse_ts(e.ts)
        if dt:
            hours.add(dt.astimezone().hour)
    # Also count episode hours
    for ep in load_episodes(since=start, limit=200):
        for key in (ep.start, ep.end):
            dt = _parse_ts(key)
            if dt:
                hours.add(dt.astimezone().hour)
    n = len(hours)
    if n < threshold:
        return None
    title = "今日电脑活跃时段偏长"
    for item in load_suggestions():
        if item.data.get("kind") == "wellness" and item.title == title:
            # cooldown: same day already suggested
            created = _parse_ts(item.created_at)
            if created and created >= start:
                return None
    rationale = (
        f"今天至少在 {n} 个不同小时有本机活动（阈值 {threshold}）。"
        "抽空站起来走走或做点户外活动会更舒服。"
    )
    return enqueue(
        source="wellness",
        title=title,
        rationale=rationale,
        suggested_cmd="# aware wellness ack",
        risk="low",
        data={"kind": "wellness", "active_hours": n, "threshold": threshold},
    )


def ingest_tick_episodes(events: list[AwareEvent]) -> list[AwareEpisode]:
    """Build + persist episodes from a tick; maybe enqueue wellness / hypotheses."""
    episodes = build_episodes_from_events(events)
    upsert_episodes(episodes)
    try:
        maybe_enqueue_active_hours_wellness()
    except Exception:
        pass
    try:
        from localagent.aware.hypothesis import run_hypothesis_loop

        run_hypothesis_loop(force=False)
    except Exception:
        pass
    return episodes
