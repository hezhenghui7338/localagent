"""Categorized aware views: now / since-last / time-window."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from localagent import config
from localagent.aware.browser_tabs import collect_open_tabs
from localagent.aware.platform_paths import default_fs_watch_paths
from localagent.aware.profile import load_profile
from localagent.aware.store import load_events
from localagent.aware.suggestion import suggestion_count
from localagent.aware.timewin import (
    format_period_span,
    label_since,
    period_label,
    since_to_datetime,
    to_local,
)
from localagent.aware.types import AwareEvent, IMPLEMENTED_SOURCES
from localagent.i18n import t
from localagent.workspace.context import git_summary, resolve_workspace

ViewMode = Literal["now", "delta", "window"]

_SOURCE_ORDER = ("browser", "fs", "terminal", "git", "apps")
_NOISE = getattr(config, "AWARE_NOISE_SUFFIXES", set())
_WINDOW_EVENT_LIMIT = 2000
_ROLLUP_TOP_N = 16


def format_view(
    *,
    mode: ViewMode,
    since: str | None = None,
    source: str | None = None,
    delta_events: list[AwareEvent] | None = None,
    detail: bool = False,
    use_llm: bool = True,
) -> str:
    if not detail:
        from localagent.aware.summary import render_summary_view

        return render_summary_view(
            mode=mode,
            since=since,
            source=source,
            delta_events=delta_events,
            use_llm=use_llm,
        )
    return _format_detail_view(
        mode=mode, since=since, source=source, delta_events=delta_events
    )


def _format_detail_view(
    *,
    mode: ViewMode,
    since: str | None = None,
    source: str | None = None,
    delta_events: list[AwareEvent] | None = None,
) -> str:
    profile = load_profile()
    sources = [source] if source else list(_SOURCE_ORDER)
    sources = [s for s in sources if s in IMPLEMENTED_SOURCES]

    if mode == "now":
        title = t("aware.title_detail_now")
    elif mode == "delta":
        title = t("aware.title_detail_delta")
    else:
        title = f"LocalAgent · Aware · {label_since(since)}"

    lines = [title, ""]
    for name in sources:
        if not profile.is_granted(name):
            lines.append(f"■ {name}")
            lines.append(t("aware.detail_unauthorized", name=name))
            lines.append("")
            continue
        lines.append(f"■ {name}")
        if mode == "now":
            lines.extend(_render_now(name))
        elif mode == "delta":
            lines.extend(
                _render_events(name, delta_events or [], empty=t("aware.no_change"))
            )
        else:
            lines.extend(_render_window(name, since or "1w"))
        lines.append("")

    n_sug = suggestion_count()
    if n_sug:
        lines.append(
            f"suggestion · {n_sug} 条（la aware suggestion · approve|reject）"
        )
    else:
        lines.append("suggestion · 0")
    lines.append(t("aware.detail_tip"))
    return "\n".join(lines).rstrip() + "\n"


def _render_now(source: str) -> list[str]:
    if source == "browser":
        return _render_browser_now()
    if source == "fs":
        profile = load_profile()
        paths = profile.grant_for("fs").paths or [str(p) for p in default_fs_watch_paths()]
        lines = ["  监视路径:"]
        for p in paths[:8]:
            lines.append(f"  · {p}")
        lines.append("  （近期文件变化请: la aware --since 1w）")
        return lines
    if source == "terminal":
        return ["  （当前无实时 PTY；近期命令请: la aware tick 或 --since 1w）"]
    if source == "git":
        summary = git_summary(resolve_workspace())
        return ["  " + ln for ln in summary.to_text().splitlines()]
    if source == "apps":
        return _render_apps_now()
    return [t("aware.detail_no_data")]


def _render_apps_now() -> list[str]:
    try:
        from localagent.aware.sensors.apps import AppsSensor
        from localagent.aware.profile import SourceGrant

        # Display-only: do not inflate daily input-activity aggregates.
        events, _ = AppsSensor(SourceGrant(granted=True)).collect(
            {}, record_activity=False
        )
    except Exception as exc:  # noqa: BLE001
        return [f"  ! 读取前台应用失败: {exc}"]
    if not events:
        return ["  （前台无变化或无法读取）"]
    e = events[0]
    lines = [f"  {e.title}"]
    scene = e.data.get("scene")
    if scene:
        lines.append(f"  场景: {scene}")
    eng = e.data.get("engagement")
    dwell_sec = e.data.get("dwell_sec")
    if eng or dwell_sec is not None:
        bits = []
        if eng:
            bits.append(str(eng))
        if dwell_sec is not None:
            ds = float(dwell_sec)
            bits.append(f"{ds / 60.0:.0f}min" if ds >= 60 else f"{ds:.0f}s")
        lines.append("  参与: " + " · ".join(bits))
    idle = e.data.get("idle_seconds")
    if idle is not None:
        lines.append(f"  空闲: {float(idle):.0f}s")
    if e.data.get("input_active"):
        lines.append("  输入: 活跃（本采样）")
    try:
        from localagent.aware.input_activity import format_input_activity_line

        activity = format_input_activity_line()
        if activity:
            lines.append(f"  {activity}")
    except Exception:  # noqa: BLE001
        pass
    if e.data.get("error"):
        lines.append(f"  ! {e.data.get('error')}")
    return lines


def _render_now_compact(source: str) -> list[str]:
    """One-line live snapshot for fact cards (avoids dumping full tab lists)."""
    prefix = t("aware.current_prefix")
    if source == "browser":
        snaps = collect_open_tabs()
        if not snaps:
            return [f"  {prefix} 无打开的浏览器"]
        parts: list[str] = []
        for snap in snaps[:2]:
            label = snap.browser or "browser"
            if snap.error and snap.tabs == 0:
                parts.append(f"{label} 不可用")
                continue
            active = snap.active_title or snap.active_url or ""
            bit = f"{label} {snap.tabs}{t('aware.tabs_unit')}"
            if snap.frontmost and active:
                bit += f" {t('aware.viewing')}={active[:60]}"
            elif not snap.frontmost and snap.tabs:
                # Open-but-unattended tabs are not attention; omit titles.
                bit += f" · {t('aware.not_viewing')}"
            parts.append(bit)
        return [f"  {prefix} " + "；".join(parts)] if parts else []
    if source == "git":
        summary = git_summary(resolve_workspace())
        text = summary.to_text().splitlines()
        if not text:
            return []
        return [f"  {prefix} " + text[0].strip()]
    if source == "apps":
        lines = _render_apps_now()
        if not lines:
            return []
        return [f"  {prefix} " + lines[0].strip()]
    return []


def _is_sensitive_browser(
    *, host: str = "", url: str = "", title: str = ""
) -> bool:
    from localagent.aware.scenes import classify_host, host_from_url

    h = (host or "").strip() or host_from_url(url)
    if not h:
        return False
    return classify_host(h, title=title) == "sensitive_video"


def _render_browser_now() -> list[str]:
    snaps = collect_open_tabs()
    # Persist snapshot for tick/status
    try:
        config.ensure_data_dirs()
        path = Path(config.AWARE_NOW_DIR) / "browser.json"
        path.write_text(
            json.dumps([s.to_dict() for s in snaps], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass

    lines: list[str] = []
    for snap in snaps:
        if snap.error and snap.tabs == 0:
            lines.append(f"  ! {snap.error}")
            continue
        lines.append(f"  {snap.browser} · {snap.windows} 窗口 · {snap.tabs} 标签")
        if snap.frontmost and (snap.active_title or snap.active_url):
            sess = ""
            try:
                from localagent.aware.store import load_cursors

                active_sess = dict(
                    (load_cursors().get("browser") or {}).get("active_session") or {}
                )
                if (
                    str(active_sess.get("active_url") or "") == snap.active_url
                    and bool(active_sess.get("viewing"))
                ):
                    eng = active_sess.get("engagement")
                    dwell_sec = float(active_sess.get("dwell_sec") or 0)
                    bits = []
                    if eng:
                        bits.append(str(eng))
                    if dwell_sec >= 60:
                        bits.append(f"{dwell_sec / 60.0:.0f}min")
                    if bits:
                        sess = " · " + " ".join(bits)
            except Exception:
                sess = ""
            if _is_sensitive_browser(
                url=snap.active_url or "", title=snap.active_title or ""
            ):
                lines.append(f"  · [正在看] 敏感类标签（已打开）{sess}")
            else:
                lines.append(
                    f"  · [正在看] {snap.active_title or '(无标题)'}  "
                    f"{snap.active_url}{sess}"
                )
        elif not snap.frontmost and snap.tabs:
            lines.append("  · 非正在看（后台打开标签不播报标题）")
        shown = 0
        sensitive_others = 0
        # Detail inventory of other tabs only while browser is frontmost.
        if not snap.frontmost:
            continue
        for it in snap.items:
            if it.get("active"):
                continue
            title = str(it.get("title") or "")
            url = str(it.get("url") or "")
            if _is_sensitive_browser(url=url, title=title):
                sensitive_others += 1
                continue
            if shown >= 8:
                continue
            lines.append(f"  · {title or '(无标题)'}  {url}")
            shown += 1
        if sensitive_others:
            lines.append(f"  · 另有 {sensitive_others} 个敏感类标签")
        remaining = snap.tabs - shown - 1 - sensitive_others
        if remaining > 0:
            lines.append(f"  … 另有 {remaining} 个标签")
    return lines or ["  （无打开的浏览器）"]


def _render_events(source: str, events: list[AwareEvent], *, empty: str) -> list[str]:
    rows = [e for e in events if e.source == source]
    if not rows:
        return [f"  {empty}"]
    if source == "browser":
        return _summarize_browser_events(rows)
    if source == "fs":
        return _summarize_fs_events(rows)
    if source == "terminal":
        return _summarize_terminal_events(rows)
    if source == "git":
        return _summarize_git_events(rows)
    if source == "apps":
        return _summarize_apps_events(rows)
    return [f"  · {e.kind}: {e.title}" for e in rows[:12]]


def _summarize_apps_events(events: list[AwareEvent]) -> list[str]:
    """Detail view: recent raw samples (not used for LLM fact cards)."""
    lines = [f"  前台采样 {len(events)} 次:"]
    for e in events[-8:]:
        scene = e.data.get("scene") or ""
        eng = e.data.get("engagement") or ""
        dwell_sec = e.data.get("dwell_sec")
        focus_since = str(e.data.get("focus_since") or "").strip()
        when = format_period_span(focus_since or e.ts, e.ts)
        tags = [str(x) for x in (scene, eng) if x]
        if when:
            tags.append(when)
        if dwell_sec is not None:
            ds = float(dwell_sec)
            tags.append(f"{ds / 60.0:.0f}min" if ds >= 60 else f"{ds:.0f}s")
        suffix = f" [{'/'.join(tags)}]" if tags else ""
        lines.append(f"  · {e.title}{suffix}")
    return lines


def _session_key_apps(e: AwareEvent) -> str:
    fk = str(e.data.get("focus_key") or "").strip()
    if fk:
        return fk
    app = str(e.data.get("app") or "")
    focus_since = str(e.data.get("focus_since") or "").strip()
    return f"{app}|{focus_since or e.ts}"


def _rollup_apps_events(events: list[AwareEvent]) -> list[str]:
    """Collapse per-session max dwell, then bucket by day×period×scene×app."""
    sessions: dict[str, dict[str, Any]] = {}
    for e in events:
        key = _session_key_apps(e)
        dwell = float(e.data.get("dwell_sec") or 0)
        prev = sessions.get(key)
        if prev is not None and dwell < float(prev.get("dwell_sec") or 0):
            continue
        sessions[key] = {
            "app": str(e.data.get("app") or e.title or "(unknown)"),
            "scene": str(e.data.get("scene") or "other"),
            "eng": str(e.data.get("engagement") or ""),
            "dwell_sec": dwell,
            "focus_since": str(e.data.get("focus_since") or e.ts),
            "end": e.ts,
        }
    if not sessions:
        return ["  （无前台会话）"]

    buckets: dict[tuple[str, str, str, str], float] = {}
    for s in sessions.values():
        local = to_local(s["focus_since"])
        day = local.strftime("%m-%d") if local else ""
        period = period_label(s["focus_since"]) or ""
        key = (day, period, str(s["scene"]), str(s["app"]))
        buckets[key] = buckets.get(key, 0.0) + float(s["dwell_sec"]) / 60.0

    lines = [f"  前台会话汇总 {len(sessions)} 段（按时段×场景）:"]
    ranked = sorted(buckets.items(), key=lambda kv: (-kv[1], kv[0]))[:_ROLLUP_TOP_N]
    for (day, period, scene, app), mins in ranked:
        when = " ".join(x for x in (day, period) if x) or "—"
        lines.append(f"  · {when} · {scene} · {app} · {mins:.0f}min")
    if len(buckets) > _ROLLUP_TOP_N:
        lines.append(f"  … 另有 {len(buckets) - _ROLLUP_TOP_N} 个聚合桶")
    return lines


def _rollup_browser_events(events: list[AwareEvent]) -> list[str]:
    hosts: Counter[str] = Counter()
    period_hosts: dict[str, Counter[str]] = defaultdict(Counter)
    actives = [
        e
        for e in events
        if e.kind == "browser.active" and e.data.get("viewing") is True
    ]
    for e in events:
        if e.kind == "browser.summary":
            when = period_label(e.ts) or ""
            local = to_local(e.ts)
            day = local.strftime("%m-%d") if local else ""
            bucket = " ".join(x for x in (day, when) if x) or "—"
            for row in list(e.data.get("hosts") or []):
                if not isinstance(row, dict):
                    continue
                host = str(row.get("host") or "")
                count = int(row.get("count") or 1)
                if _is_sensitive_browser(host=host):
                    label = "敏感类"
                elif host:
                    label = host
                else:
                    continue
                hosts[label] += count
                period_hosts[bucket][label] += count
        elif e.kind not in {"browser.active", "browser.selected"}:
            hosts[e.title] += 1

    lines: list[str] = []
    if hosts:
        parts = [f"{h}×{c}" for h, c in hosts.most_common(10) if h]
        lines.append(f"  访问摘要（全窗 {len(events)} 条）: " + ", ".join(parts))
    for bucket, ctr in sorted(period_hosts.items())[:8]:
        top = ", ".join(f"{h}×{c}" for h, c in ctr.most_common(4) if h)
        if top:
            lines.append(f"  · {bucket}: {top}")
    if actives:
        # Collapse viewing sessions by focus_since / url
        sess: dict[str, AwareEvent] = {}
        for e in actives:
            key = str(e.data.get("focus_since") or e.data.get("active_url") or e.ts)
            prev = sess.get(key)
            if prev is None or float(e.data.get("dwell_sec") or 0) >= float(
                prev.data.get("dwell_sec") or 0
            ):
                sess[key] = e
        ranked = sorted(
            sess.values(),
            key=lambda e: float(e.data.get("dwell_sec") or 0),
            reverse=True,
        )[:6]
        for e in ranked:
            eng = str(e.data.get("engagement") or "")
            dwell_sec = float(e.data.get("dwell_sec") or 0)
            host = str(e.data.get("host") or "")
            title = str(e.data.get("active_title") or host or e.title)
            focus_since = str(e.data.get("focus_since") or "").strip()
            when = format_period_span(focus_since or e.ts, e.ts)
            if _is_sensitive_browser(host=host, title=title):
                bit = "  正在看: 敏感类浏览"
            else:
                bit = f"  正在看: {title[:60]}"
            if when:
                bit += f" · {when}"
            if eng:
                bit += f" · {eng}"
            if dwell_sec >= 60:
                bit += f" · {dwell_sec / 60.0:.0f}min"
            lines.append(bit)
    if not lines:
        return ["  （无浏览摘要）"]
    return lines


def _rollup_terminal_events(events: list[AwareEvent]) -> list[str]:
    cmds = [e for e in events if e.kind == "terminal.cmd"]
    if not cmds:
        return ["  （无新命令）"]
    lines = [f"  窗口内命令 {len(cmds)} 条:"]
    # Sample across the window: earliest, mid, latest
    samples = cmds
    if len(samples) > 10:
        idx = {0, len(samples) // 2, len(samples) - 1}
        step = max(1, len(samples) // 8)
        for i in range(0, len(samples), step):
            idx.add(i)
        picks = [samples[i] for i in sorted(idx)][:10]
    else:
        picks = samples
    for e in picks:
        when = period_label(e.ts) or ""
        local = to_local(e.ts)
        day = local.strftime("%m-%d") if local else ""
        prefix = " ".join(x for x in (day, when) if x)
        bit = f"  $ {e.title}"
        if prefix:
            bit = f"  · {prefix} · $ {e.title}"
        lines.append(bit)
    return lines


def _rollup_git_events(events: list[AwareEvent]) -> list[str]:
    if not events:
        return ["  （无 git 变化）"]
    lines = [f"  窗口内 git {len(events)} 条:"]
    for e in events[:12]:
        when = format_period_span(e.ts, e.ts) or period_label(e.ts) or ""
        if when:
            lines.append(f"  · {when} · {e.kind}: {e.title}")
        else:
            lines.append(f"  · {e.kind}: {e.title}")
    if len(events) > 12:
        lines.append(f"  … 另有 {len(events) - 12} 条")
    return lines


def _rollup_fs_events(events: list[AwareEvent]) -> list[str]:
    base = _summarize_fs_events(events)
    if base and base[0].startswith("  （"):
        return base
    # Prefix count line already present; add period hint from first/last
    stamps = [e.ts for e in events if e.ts]
    if stamps:
        when = format_period_span(stamps[0], stamps[-1])
        if when:
            return [f"  文件变化时段: {when}", *base]
    return base


def _rollup_events(source: str, events: list[AwareEvent], *, empty: str) -> list[str]:
    rows = [e for e in events if e.source == source]
    if not rows:
        return [f"  {empty}"]
    if source == "apps":
        return _rollup_apps_events(rows)
    if source == "browser":
        return _rollup_browser_events(rows)
    if source == "terminal":
        return _rollup_terminal_events(rows)
    if source == "git":
        return _rollup_git_events(rows)
    if source == "fs":
        return _rollup_fs_events(rows)
    return [f"  · {e.kind}: {e.title}" for e in rows[:12]]


def _render_window(source: str, since: str) -> list[str]:
    start = since_to_datetime(since)
    events = load_events(source=source, since=start, limit=500)
    lines = _render_events(source, events, empty=f"{label_since(since)}内无已记录事件")
    if source == "fs":
        scanned = _scan_fs_mtime_window(start)
        if scanned:
            lines.append(f"  时间窗内 mtime 触及（扫描）· {len(scanned)}：")
            for path in scanned[:15]:
                lines.append(f"  ~ {path}")
            if len(scanned) > 15:
                lines.append(f"  … 另有 {len(scanned) - 15} 个")
    if source == "browser" and not any(e.kind == "browser.summary" for e in events):
        # Optional: could query history DB for window — keep events-first for MVP
        pass
    return lines


def _render_window_rollup(source: str, since: str) -> list[str]:
    """Window facts for LLM overview: aggregated across the full since range."""
    start = since_to_datetime(since)
    events = load_events(source=source, since=start, limit=_WINDOW_EVENT_LIMIT)
    lines = _rollup_events(
        source, events, empty=f"{label_since(since)}内无已记录事件"
    )
    if source == "fs":
        scanned = _scan_fs_mtime_window(start)
        if scanned:
            lines.append(f"  时间窗内 mtime 触及（扫描）· {len(scanned)}：")
            for path in scanned[:8]:
                lines.append(f"  ~ {path}")
            if len(scanned) > 8:
                lines.append(f"  … 另有 {len(scanned) - 8} 个")
    return lines


def _scan_fs_mtime_window(start: datetime) -> list[str]:
    profile = load_profile()
    if not profile.is_granted("fs"):
        return []
    from localagent.aware.sensors.fs import walk_watch_files

    roots = [
        Path(p).expanduser()
        for p in (
            profile.grant_for("fs").paths or [str(p) for p in default_fs_watch_paths()]
        )
    ]
    start_ts = start.timestamp()
    files, _scanned, _truncated = walk_watch_files(roots, noise_suffixes=_NOISE)
    hits: list[tuple[float, str]] = []
    for path, st in files:
        if st.st_mtime >= start_ts:
            hits.append((st.st_mtime, str(path)))
    hits.sort(reverse=True)
    return [p for _m, p in hits[:80]]


def _summarize_browser_events(events: list[AwareEvent]) -> list[str]:
    hosts: Counter[str] = Counter()
    actives = [
        e
        for e in events
        if e.kind == "browser.active" and e.data.get("viewing") is True
    ]
    selected = [e for e in events if e.kind == "browser.selected"]
    for e in events:
        if e.kind == "browser.summary":
            for row in list(e.data.get("hosts") or []):
                if isinstance(row, dict):
                    host = str(row.get("host") or "")
                    count = int(row.get("count") or 1)
                    if _is_sensitive_browser(host=host):
                        hosts["敏感类"] += count
                    elif host:
                        hosts[host] += count
        elif e.kind not in {"browser.active", "browser.selected"}:
            hosts[e.title] += 1
    lines: list[str] = []
    if hosts:
        parts = [f"{h}×{c}" for h, c in hosts.most_common(10) if h]
        lines.append("  访问摘要: " + ", ".join(parts))
    # Surface visit-time span from history summaries when available.
    for e in events:
        if e.kind != "browser.summary":
            continue
        first = str(e.data.get("first_visit") or "").strip()
        last_v = str(e.data.get("last_visit") or "").strip()
        when = format_period_span(first, last_v) if first or last_v else ""
        if when:
            lines.append(f"  访问时段: {when}")
            break

    if actives:
        last = actives[-1]
        eng = str(last.data.get("engagement") or "")
        dwell_sec = float(last.data.get("dwell_sec") or 0)
        host = str(last.data.get("host") or "")
        title = str(last.data.get("active_title") or host or last.title)
        url = str(last.data.get("active_url") or "")
        focus_since = str(last.data.get("focus_since") or "").strip()
        when = format_period_span(focus_since or last.ts, last.ts)
        if _is_sensitive_browser(host=host, url=url, title=title):
            bit = "  正在看: 敏感类浏览（仅时长信号）"
        else:
            bit = f"  正在看: {title[:60]}"
        if when:
            bit += f" · {when}"
        if eng:
            bit += f" · {eng}"
        if dwell_sec >= 60:
            bit += f" · {dwell_sec / 60.0:.0f}min"
        lines.append(bit)
    elif selected:
        # Background-selected tabs are not attention; do not surface titles.
        lines.append("  非正在看（后台打开标签不播报标题）")
    if not lines:
        return ["  （无浏览摘要）"]
    return lines


def _is_noise_path(path: str) -> bool:
    p = Path(path)
    if p.name in {".DS_Store", "Thumbs.db"}:
        return True
    return p.suffix.lower() in _NOISE


def _summarize_fs_events(events: list[AwareEvent]) -> list[str]:
    created = [
        e
        for e in events
        if e.kind == "file.created" and not _is_noise_path(str(e.data.get("path") or e.title))
    ]
    modified = [
        e
        for e in events
        if e.kind == "file.modified" and not _is_noise_path(str(e.data.get("path") or e.title))
    ]
    if not created and not modified:
        return ["  （无新增/编辑文件）"]
    lines = [f"  新增 {len(created)} · 编辑 {len(modified)}"]
    for e in created[:10]:
        lines.append(f"  + {e.data.get('path') or e.title}")
    for e in modified[:8]:
        lines.append(f"  ~ {e.data.get('path') or e.title}")
    return lines


def _summarize_terminal_events(events: list[AwareEvent]) -> list[str]:
    cmds = [e.title for e in events if e.kind == "terminal.cmd"][-12:]
    if not cmds:
        return ["  （无新命令）"]
    lines = [f"  最近命令 {len(cmds)} 条:"]
    for c in cmds:
        lines.append(f"  $ {c}")
    return lines


def _summarize_git_events(events: list[AwareEvent]) -> list[str]:
    if not events:
        return ["  （无 git 变化）"]
    lines = []
    for e in events[:12]:
        lines.append(f"  · {e.kind}: {e.title}")
    return lines


def group_events_by_source(events: list[AwareEvent]) -> dict[str, list[AwareEvent]]:
    out: dict[str, list[AwareEvent]] = defaultdict(list)
    for e in events:
        out[e.source].append(e)
    return dict(out)
