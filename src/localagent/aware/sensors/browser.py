"""Browser history sensor: copy SQLite then query (Chromium / Safari / Firefox)."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from localagent import config
from localagent.aware.engagement import (
    ENGAGEMENT_GLANCE,
    classify_engagement,
    tick_interval_sec,
    update_idle_stats,
)
from localagent.aware.platform_paths import BrowserDb, discover_browser_dbs
from localagent.aware.profile import SourceGrant
from localagent.aware.types import AwareEvent, utc_now

_MAX_RAW_VISITS = 100
_CHROMIUM_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
_SAFARI_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

_NOISE_PREFIXES = (
    "chrome://",
    "chrome-extension://",
    "edge://",
    "about:",
    "devtools://",
    "brave://",
    "safari-web-extension://",
)


class BrowserSensor:
    name = "browser"

    def __init__(self, grant: SourceGrant) -> None:
        self.grant = grant

    def _dbs(self) -> list[BrowserDb]:
        return discover_browser_dbs()

    def describe_access(self) -> list[str]:
        dbs = self._dbs()
        if not dbs:
            return ["（未发现浏览器 History 数据库）"]
        lines = [f"{db.browser}/{db.profile}: {db.path}" for db in dbs]
        lines.append("说明: 只读拷贝后查询；不读取 Cookie/密码。macOS Safari 可能需要「完全磁盘访问」。")
        return lines

    def collect(self, cursor: dict[str, Any]) -> tuple[list[AwareEvent], dict[str, Any]]:
        last_ts: dict[str, float] = {
            str(k): float(v) for k, v in dict(cursor.get("last_visit_ts") or {}).items()
        }
        new_last = dict(last_ts)
        host_counts: Counter[str] = Counter()
        samples: dict[str, str] = {}
        visit_isos: list[str] = []
        raw_n = 0

        primed_keys = set(last_ts.keys())
        for db in self._dbs():
            key = f"{db.browser}:{db.profile}:{db.path}"
            since = last_ts.get(key, 0.0)
            try:
                if key not in primed_keys:
                    # First grant: seed watermark only (no historical flood).
                    new_last[key] = _max_visit_ts(db) or _high_watermark(db.engine)
                    continue
                visits, max_ts = _read_visits(
                    db, since_ts=since, limit=_MAX_RAW_VISITS - raw_n
                )
            except PermissionError:
                continue
            except OSError:
                continue
            if max_ts > since:
                new_last[key] = max_ts
            for visit in visits:
                raw_n += 1
                url = visit["url"]
                if any(url.startswith(p) for p in _NOISE_PREFIXES):
                    continue
                host = urlparse(url).netloc or url[:40]
                host_counts[host] += 1
                if host not in samples:
                    samples[host] = visit.get("title") or url
                vts = str(visit.get("visit_ts") or "").strip()
                if vts:
                    visit_isos.append(vts)

        events: list[AwareEvent] = []
        if host_counts:
            top = host_counts.most_common(15)
            parts = [f"{h}×{c}" for h, c in top]
            first_visit = min(visit_isos) if visit_isos else ""
            last_visit = max(visit_isos) if visit_isos else ""
            hour_buckets = _hour_buckets(visit_isos)
            data: dict[str, Any] = {
                "hosts": [
                    {"host": h, "count": c, "sample": samples.get(h, "")}
                    for h, c in top
                ],
                "visit_count": sum(host_counts.values()),
                "engagement": "glance",
            }
            if first_visit:
                data["first_visit"] = first_visit
            if last_visit:
                data["last_visit"] = last_visit
            if hour_buckets:
                data["hour_buckets"] = hour_buckets
            events.append(
                AwareEvent(
                    source="browser",
                    kind="browser.summary",
                    title="浏览摘要: " + ", ".join(parts[:5]),
                    data=data,
                )
            )

        active_event, active_session = _collect_active_session(
            cursor=cursor,
            host_counts=host_counts,
            samples=samples,
        )
        if active_event is not None:
            events.append(active_event)

        return events, {"last_visit_ts": new_last, "active_session": active_session}


def _host_visit_count(host_counts: Counter[str], host: str) -> int:
    if not host:
        return 0
    h = host.lower().removeprefix("www.")
    total = 0
    for key, count in host_counts.items():
        k = str(key).lower().removeprefix("www.")
        if k == h or k.endswith("." + h) or h.endswith("." + k):
            total += int(count)
    return total


def _collect_active_session(
    *,
    cursor: dict[str, Any],
    host_counts: Counter[str],
    samples: dict[str, str],
) -> tuple[AwareEvent | None, dict[str, Any]]:
    """Track selected-tab session; dwell only while the browser is OS-frontmost."""
    from localagent.aware.browser_tabs import BrowserNow, collect_open_tabs
    from localagent.aware.scenes import classify_host, host_from_url

    snaps = collect_open_tabs()
    viewing_snap: BrowserNow | None = None
    selected_snap: BrowserNow | None = None
    for snap in snaps:
        if snap.error and not (snap.active_url or snap.active_title):
            continue
        if not (snap.active_url or snap.active_title):
            continue
        if selected_snap is None:
            selected_snap = snap
        if snap.frontmost:
            viewing_snap = snap
            break

    snap = viewing_snap or selected_snap
    prev = dict(cursor.get("active_session") or {})
    if snap is None:
        return None, {}

    active_url = str(snap.active_url or "")
    active_title = str(snap.active_title or "")
    browser_id = str(snap.browser or "")
    if not active_url:
        return None, {}

    viewing = viewing_snap is not None
    now = utc_now()
    quantum = tick_interval_sec()
    host = host_from_url(active_url)
    same = prev.get("active_url") == active_url
    prev_viewing = bool(prev.get("viewing"))
    prev_ticks = int(prev.get("ticks_seen") or 0)

    if viewing:
        if same and prev_viewing:
            ticks_seen = max(1, prev_ticks) + 1
            focus_since = str(prev.get("focus_since") or now)
            session = update_idle_stats(prev, None)
        elif same and not prev_viewing and prev_ticks >= 1:
            # Resume after background freeze; gap ticks are not counted.
            ticks_seen = prev_ticks + 1
            focus_since = str(prev.get("focus_since") or now)
            session = update_idle_stats(prev, None)
        else:
            ticks_seen = 1
            focus_since = now
            session = {}
        dwell_sec = float(ticks_seen) * quantum
        visit_count = _host_visit_count(host_counts, host)
        engagement = classify_engagement(
            ticks_seen=ticks_seen,
            dwell_sec=dwell_sec,
            visit_count=visit_count,
            interval_sec=quantum,
        )
        kind = "browser.active"
        title_prefix = "正在看"
    else:
        # Background selected tab: freeze dwell counters.
        if same:
            ticks_seen = prev_ticks
            dwell_sec = float(prev.get("dwell_sec") or 0.0)
            focus_since = str(prev.get("focus_since") or now)
            session = dict(prev)
        else:
            ticks_seen = 0
            dwell_sec = 0.0
            focus_since = now
            session = {}
        visit_count = _host_visit_count(host_counts, host)
        engagement = ENGAGEMENT_GLANCE
        kind = "browser.selected"
        title_prefix = "选中标签"

    scene = classify_host(host, title=active_title) if host else "browser"
    sample = samples.get(host) or samples.get("www." + host) or active_title or active_url
    title = (active_title or host or active_url)[:80]
    event = AwareEvent(
        source="browser",
        kind=kind,
        title=f"{title_prefix}: {title}",
        data={
            "browser": browser_id,
            "active_url": active_url,
            "active_title": active_title,
            "host": host,
            "sample": sample,
            "scene": scene,
            "focus_since": focus_since,
            "ticks_seen": ticks_seen,
            "dwell_sec": dwell_sec,
            "engagement": engagement,
            "visit_count": visit_count,
            "viewing": viewing,
        },
    )
    # Persist last viewing engagement for resume; selected heartbeats stay glance.
    session_engagement = engagement if viewing else str(prev.get("engagement") or ENGAGEMENT_GLANCE)
    session.update(
        {
            "active_url": active_url,
            "active_title": active_title,
            "host": host,
            "browser": browser_id,
            "focus_since": focus_since,
            "last_seen_at": now,
            "ticks_seen": ticks_seen,
            "dwell_sec": dwell_sec,
            "engagement": session_engagement,
            "visit_count": visit_count,
            "viewing": viewing,
        }
    )
    return event, session


def _high_watermark(engine: str) -> float:
    """Cursor value meaning 'ignore history before next real visit'."""
    now = datetime.now(timezone.utc)
    if engine == "chromium":
        return (now - _CHROMIUM_EPOCH).total_seconds() * 1_000_000
    if engine == "safari":
        return (now - _SAFARI_EPOCH).total_seconds()
    if engine == "firefox":
        return now.timestamp() * 1_000_000
    return now.timestamp()


def _engine_visit_to_iso(engine: str, visit_time: float) -> str:
    """Convert engine-native visit_time to UTC ISO string."""
    if visit_time <= 0:
        return ""
    try:
        if engine == "chromium":
            dt = _CHROMIUM_EPOCH + timedelta(microseconds=int(visit_time))
        elif engine == "safari":
            dt = _SAFARI_EPOCH + timedelta(seconds=float(visit_time))
        elif engine == "firefox":
            dt = datetime.fromtimestamp(visit_time / 1_000_000.0, tz=timezone.utc)
        else:
            return ""
    except (OverflowError, OSError, ValueError):
        return ""
    return dt.isoformat()


def _hour_buckets(visit_isos: list[str]) -> list[dict[str, int]]:
    """Aggregate visit counts by local hour."""
    from localagent.aware.timewin import to_local

    counts: Counter[int] = Counter()
    for iso in visit_isos:
        local = to_local(iso)
        if local is None:
            continue
        counts[local.hour] += 1
    return [{"hour": h, "count": c} for h, c in sorted(counts.items())]


def _browser_db_max_bytes() -> int:
    return int(getattr(config, "AWARE_BROWSER_DB_MAX_BYTES", 64 * 1024 * 1024) or 64 * 1024 * 1024)


def _db_too_large(db: BrowserDb) -> bool:
    try:
        return db.path.stat().st_size > _browser_db_max_bytes()
    except OSError:
        return True


def _with_db_copy(db: BrowserDb):
    """Context-like helper: copy DB to temp and return (copy_path, cleanup).

    Raises OSError when the History DB exceeds AWARE_BROWSER_DB_MAX_BYTES.
    """
    if _db_too_large(db):
        raise OSError(f"browser history db too large to copy: {db.path}")
    tmp_dir = Path(tempfile.mkdtemp(prefix="la-aware-browser-"))
    copy_path = tmp_dir / db.path.name
    shutil.copy2(db.path, copy_path)
    for suffix in ("-journal", "-wal", "-shm"):
        side = Path(str(db.path) + suffix)
        if side.is_file():
            try:
                # Side files can also be huge; skip oversized companions.
                if side.stat().st_size > _browser_db_max_bytes():
                    continue
                shutil.copy2(side, tmp_dir / (db.path.name + suffix))
            except OSError:
                pass
    return copy_path, tmp_dir


def _max_visit_ts(db: BrowserDb) -> float:
    if _db_too_large(db):
        return _high_watermark(db.engine)
    copy_path, tmp_dir = _with_db_copy(db)
    try:
        conn = sqlite3.connect(f"file:{copy_path}?mode=ro", uri=True)
        try:
            if db.engine == "chromium":
                row = conn.execute("SELECT MAX(visit_time) FROM visits").fetchone()
            elif db.engine == "safari":
                row = conn.execute("SELECT MAX(visit_time) FROM history_visits").fetchone()
            elif db.engine == "firefox":
                row = conn.execute("SELECT MAX(last_visit_date) FROM moz_places").fetchone()
            else:
                return 0.0
            return float(row[0] or 0) if row else 0.0
        except sqlite3.Error:
            return 0.0
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _read_visits(db: BrowserDb, *, since_ts: float, limit: int) -> tuple[list[dict[str, str]], float]:
    if limit <= 0:
        return [], since_ts
    if _db_too_large(db):
        return [], since_ts
    copy_path, tmp_dir = _with_db_copy(db)
    try:
        if db.engine == "chromium":
            return _query_chromium(copy_path, since_ts=since_ts, limit=limit)
        if db.engine == "safari":
            return _query_safari(copy_path, since_ts=since_ts, limit=limit)
        if db.engine == "firefox":
            return _query_firefox(copy_path, since_ts=since_ts, limit=limit)
        return [], since_ts
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _query_chromium(path: Path, *, since_ts: float, limit: int) -> tuple[list[dict[str, str]], float]:
    # Chromium visit_time is microseconds since 1601
    since_chrome = int(since_ts) if since_ts > 1e12 else 0
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT u.url, u.title, v.visit_time
            FROM visits v
            JOIN urls u ON u.id = v.url
            WHERE v.visit_time > ?
            ORDER BY v.visit_time ASC
            LIMIT ?
            """,
            (since_chrome, limit),
        ).fetchall()
    except sqlite3.Error:
        return [], since_ts
    finally:
        conn.close()
    visits: list[dict[str, str]] = []
    max_ts = since_ts
    for url, title, visit_time in rows:
        vt = float(visit_time or 0)
        max_ts = max(max_ts, vt)
        row: dict[str, str] = {"url": str(url or ""), "title": str(title or "")}
        iso = _engine_visit_to_iso("chromium", vt)
        if iso:
            row["visit_ts"] = iso
        visits.append(row)
    return visits, max_ts


def _query_safari(path: Path, *, since_ts: float, limit: int) -> tuple[list[dict[str, str]], float]:
    # visit_time is seconds since 2001-01-01
    since_safari = since_ts if since_ts < 1e12 else 0
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT i.url, v.title, v.visit_time
            FROM history_visits v
            JOIN history_items i ON i.id = v.history_item
            WHERE v.visit_time > ?
            ORDER BY v.visit_time ASC
            LIMIT ?
            """,
            (since_safari, limit),
        ).fetchall()
    except sqlite3.Error:
        return [], since_ts
    finally:
        conn.close()
    visits: list[dict[str, str]] = []
    max_ts = since_ts
    for url, title, visit_time in rows:
        vt = float(visit_time or 0)
        max_ts = max(max_ts, vt)
        row: dict[str, str] = {"url": str(url or ""), "title": str(title or "")}
        iso = _engine_visit_to_iso("safari", vt)
        if iso:
            row["visit_ts"] = iso
        visits.append(row)
    return visits, max_ts


def _query_firefox(path: Path, *, since_ts: float, limit: int) -> tuple[list[dict[str, str]], float]:
    # last_visit_date microseconds since Unix epoch
    since_ff = int(since_ts) if since_ts > 1e12 else 0
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            """
            SELECT p.url, p.title, p.last_visit_date
            FROM moz_places p
            WHERE p.last_visit_date IS NOT NULL AND p.last_visit_date > ?
            ORDER BY p.last_visit_date ASC
            LIMIT ?
            """,
            (since_ff, limit),
        ).fetchall()
    except sqlite3.Error:
        return [], since_ts
    finally:
        conn.close()
    visits: list[dict[str, str]] = []
    max_ts = since_ts
    for url, title, visit_time in rows:
        vt = float(visit_time or 0)
        max_ts = max(max_ts, vt)
        row: dict[str, str] = {"url": str(url or ""), "title": str(title or "")}
        iso = _engine_visit_to_iso("firefox", vt)
        if iso:
            row["visit_ts"] = iso
        visits.append(row)
    return visits, max_ts
