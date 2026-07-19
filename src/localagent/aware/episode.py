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
    format_now_local,
    format_period_span,
    parse_ts,
)
from localagent.aware.types import AwareEvent, utc_now

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
            bits.append(f" · ~{sig['chars_approx']}字")
        if sig.get("cmd_count"):
            bits.append(f" · {sig['cmd_count']}条命令")
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


def append_episodes(episodes: list[AwareEpisode]) -> int:
    if not episodes:
        return 0
    config.ensure_data_dirs()
    path = _episodes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _maybe_rotate(path)
    with path.open("a", encoding="utf-8") as fh:
        for ep in episodes:
            fh.write(json.dumps(ep.to_dict(), ensure_ascii=False) + "\n")
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
    return list(reversed(rows[:limit]))


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
            title = f"{scene} · 新增{created}/编辑{modified}"
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
                title=f"终端会话 · {len(cmds)} 条命令",
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
                title=f"git · {len(git_events)} 条变化",
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
                    title="敏感类浏览（仅时长信号）",
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
                    title="敏感类浏览页（仅时长信号）",
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
                    title="敏感类前台活动（仅时长）",
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
    """Highest attention first; drops stale browser rows."""
    ranked = sorted(
        filter_stale_episodes(episodes),
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
        return "（近窗无 Episode）"
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
        return "（近窗无 Episode）"
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
    """Render open-tab title/URL for chat injection (sensitive hosts redacted)."""
    from localagent.aware.browser_tabs import collect_open_tabs
    from localagent.aware.scenes import classify_host, host_from_url

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
        active_host = host_from_url(snap.active_url)
        active_scene = classify_host(active_host, title=snap.active_title) if active_host else ""
        viewing = bool(snap.frontmost)
        focus_label = "正在看" if viewing else "后台选中"
        sess_bit = _browser_session_annotation(snap.active_url, viewing=viewing)
        if active_scene == "sensitive_video":
            lines.append(
                f"- [{label}] {focus_label}: 敏感类标签（已打开）"
                + (f" · {snap.tabs}标签" if snap.tabs else "")
                + sess_bit
            )
        elif snap.active_title or snap.active_url:
            title = (snap.active_title or "(无标题)")[:80]
            url = (snap.active_url or "")[:120]
            bit = f"- [{label}] {focus_label}: {title}"
            if url:
                bit += f"  {url}"
            bit += sess_bit
            lines.append(bit)
        else:
            lines.append(f"- [{label}] {snap.tabs}标签{sess_bit}")

        others: list[str] = []
        sensitive_others = 0
        for it in snap.items:
            if it.get("active"):
                continue
            host = host_from_url(str(it.get("url") or ""))
            scene = classify_host(host, title=str(it.get("title") or "")) if host else ""
            if scene == "sensitive_video":
                sensitive_others += 1
                continue
            t = str(it.get("title") or "").strip()
            u = str(it.get("url") or "").strip()
            if not t and not u:
                continue
            if t:
                others.append(f"{t[:50]}" + (f" ({host})" if host else ""))
            elif host:
                others.append(host)
            elif u:
                others.append(u[:60])
            if len(others) >= max_other_tabs:
                break
        for o in others:
            lines.append(f"  · {o}")
        if sensitive_others:
            lines.append(f"  · 另有 {sensitive_others} 个敏感类标签")
    if not any_ok and len(lines) == 1:
        return []
    return lines


def _format_apps_now_context() -> list[str]:
    """One-line current frontmost app for chat injection (if apps granted)."""
    try:
        from localagent.aware.digest import _render_now_compact
        from localagent.aware.profile import load_profile

        if not load_profile().is_granted("apps"):
            return []
        live = _render_now_compact("apps")
    except Exception:
        return []
    if not live:
        return []
    text = live[0].strip()
    if text.startswith("当前:"):
        text = text[len("当前:") :].strip()
    if not text:
        return []
    return ["### 当前应用", f"- {text}"]


def retrieve_aware_context(
    query: str = "",
    *,
    since_hours: float = 3,
    limit: int = 14,
    include_sensitive: bool = False,
) -> str:
    """Compact card for aware> / optional chat injection."""
    del include_sensitive  # reserved; MVP has no sensitive episode titles
    since = datetime.now(timezone.utc) - timedelta(hours=max(1.0, since_hours))
    episodes = load_episodes(since=since, limit=80)
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
            episodes = [ep for _s, ep in scored[:limit]]
            query_ranked = True
        else:
            episodes = episodes[-limit:]
    else:
        episodes = episodes[-limit:]

    from localagent.aware.hypothesis import load_hypotheses
    from localagent.aware.suggestion import load_suggestions
    from localagent.status.daily import format_daily_actions_lines

    sug_lines = []
    for item in load_suggestions()[:5]:
        kind = str(item.data.get("kind") or "action")
        sug_lines.append(f"- [{kind}] {item.title}: {item.rationale}")

    hypo_lines = [f"- ({h.confidence:.2f}) {h.claim}" for h in load_hypotheses()[:5]]

    browser_now = _format_browser_now_context()
    apps_now = _format_apps_now_context()

    hours_label = (
        f"{int(since_hours)}"
        if float(since_hours).is_integer()
        else f"{since_hours:g}"
    )
    now_local = format_now_local()
    parts = [
        "## LocalAgent Aware 感知上下文",
        f"当前本地时间: {now_local}",
        "规则: 只根据下列本机感知证据回答；无证据不编造；"
        "发生时刻/时段是最重要元数据；回答「什么时候」必须引用证据中的本地钟面或时段"
        "（如晚上 22:15、白天上午），禁止仅用「最近/今天上午」等模糊说法；"
        "叙事优先按时段组织（白天/晚上 + 具体钟面），总时长次之；"
        "敏感类不复述片名/URL/站点名，只谈时长与时段聚合；"
        "用户询问本人本机行为时，须据证据如实回答敏感类的时段与时长，"
        "不得因主题敏感拒答或道德说教；"
        "参与度分 glance(掠过)/dwell(停留)/engage(操作)，勿把 glance 当深度使用；"
        "当前应用(apps.focus)优先表示用户此刻注意力；"
        "浏览器块仅在标注「正在看」时表示正在浏览，后台选中标签不等于浏览；"
        "当前应用/正在看浏览器块优先于近期 Episode；"
        f"Episode 仅为近 {hours_label} 小时活动，勿当成此刻仍在做的事；"
        "做朋友式建议，不评判。需要改记忆时请用户明确说「记住」。",
        "",
    ]
    # Apps (true frontmost) before browser tabs so attention signal leads.
    if apps_now:
        parts.extend([*apps_now, ""])
    if browser_now:
        parts.extend([*browser_now, ""])
    ep_cards = (
        format_episode_cards(episodes, limit=limit)
        if query_ranked
        else format_episode_cards(episodes, limit=limit, by_time=True)
    )
    parts.extend(
        [
            f"### 近期 Episode（时间线 · 最近 {hours_label} 小时）",
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
    append_episodes(episodes)
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
