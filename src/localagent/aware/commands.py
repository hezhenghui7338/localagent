"""CLI handlers for `la aware …`."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from localagent.audit.events import log_event
from localagent.aware.digest import format_view
from localagent.aware.platform_paths import (
    default_fs_watch_paths,
    discover_browser_dbs,
    discover_history_files,
)
from localagent.aware.profile import (
    grant_source,
    load_profile,
    save_profile,
    ungrant_source,
)
from localagent.aware.schedule import disable_schedule, enable_schedule, schedule_status
from localagent.aware.sensors import build_sensor
from localagent.aware.store import events_count_today, load_events
from localagent.aware.suggestion import (
    get_item,
    is_ack_only_cmd,
    is_allowed_cmd,
    load_suggestions,
    remove_items,
    suggestion_count,
)
from localagent.aware.tick import run_tick
from localagent.aware.timewin import DEFAULT_SINCE, parse_since
from localagent.aware.types import ALL_SOURCES, IMPLEMENTED_SOURCES, SENSITIVE_SOURCES
from localagent.i18n import t
from localagent.workspace.context import resolve_workspace


def cmd_aware(args: argparse.Namespace) -> int:
    action = getattr(args, "aware_action", None) or getattr(args, "action", None)
    if not action:
        return _cmd_view(args)
    handlers = {
        "status": _cmd_status,
        "grant": _cmd_grant,
        "ungrant": _cmd_ungrant,
        "paths": _cmd_paths,
        "schedule": _cmd_schedule,
        "tick": _cmd_tick,
        "suggestion": _cmd_suggestion,
        "events": _cmd_events,
    }
    fn = handlers.get(action)
    if not fn:
        print(t("aware.cmd_unknown", action=action))
        return 1
    return fn(args)


def _cmd_view(args: argparse.Namespace) -> int:
    source = getattr(args, "source", None) or None
    if source == "all":
        source = None
    detail = bool(getattr(args, "detail", False))
    since_raw = getattr(args, "since", None)
    since: str | None = None
    mode = "now"
    if since_raw is not None:
        try:
            since = parse_since(since_raw if since_raw != "" else DEFAULT_SINCE)
        except ValueError as exc:
            print(f"[aware] {exc}")
            return 1
        mode = "window"
        print(
            format_view(mode="window", since=since, source=source, detail=detail),
            end="",
        )
    else:
        print(format_view(mode="now", source=source, detail=detail), end="")

    from localagent.aware.repl import run_aware_chat, should_enter_aware_chat

    if should_enter_aware_chat(no_chat=bool(getattr(args, "no_chat", False))):
        return run_aware_chat(
            mode=mode,
            since=since,
            source=source,
            provider=str(getattr(args, "provider", None) or "auto"),
        )
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    profile = load_profile()
    sched = schedule_status()
    print(t("aware.status_title"))
    when = profile.last_tick_at or t("aware.status_never")
    print(t("aware.status_last_tick", when=when))
    state = t("aware.status_sched_on") if sched.enabled else t("aware.status_sched_off")
    print(
        t(
            "aware.status_schedule",
            state=state,
            backend=sched.backend,
            minutes=sched.interval_minutes,
            detail=sched.detail,
        )
    )
    print(
        t(
            "aware.status_counts",
            events=events_count_today(),
            sug=suggestion_count(),
        )
    )
    print(t("aware.status_grants"))
    for name in ALL_SOURCES:
        g = profile.grant_for(name)
        mark = "✓" if g.granted else "·"
        impl = "" if name in IMPLEMENTED_SOURCES else t("aware.status_not_impl")
        hint = (
            t("aware.status_hint_ungrant", name=name)
            if g.granted and name in IMPLEMENTED_SOURCES
            else ""
        )
        print(f"  {mark} {name}{impl}{hint}")
    print(t("aware.status_view_hint"))
    print(t("aware.status_ungrant_hint"))
    print(t("aware.status_sug_hint"))
    return 0


def _confirm(prompt: str) -> bool:
    try:
        ans = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return ans in {"y", "yes"}


def _expand_grant_sources(sources: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for s in sources:
        batch = sorted(IMPLEMENTED_SOURCES) if s == "all" else [s]
        for name in batch:
            if name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _cmd_grant(args: argparse.Namespace) -> int:
    sources = _expand_grant_sources(list(getattr(args, "sources", []) or []))
    if not sources:
        print(t("aware.grant_usage"))
        print(t("aware.grant_choices", sources=" ".join(ALL_SOURCES)))
        return 1
    yes = bool(getattr(args, "yes", False))

    for source in sources:
        if source not in ALL_SOURCES:
            print(t("aware.grant_unknown", source=source))
            return 1
        if source not in IMPLEMENTED_SOURCES:
            print(t("aware.grant_not_impl", source=source))
            continue

        grant = load_profile().grant_for(source)
        sensor = build_sensor(source, grant)
        print(t("aware.grant_will", source=source))
        for line in sensor.describe_access():
            print(f"  - {line}")
        if source in SENSITIVE_SOURCES and not yes:
            if not _confirm(t("aware.grant_confirm", source=source)):
                print(t("aware.grant_cancelled", source=source))
                continue

        paths = None
        repos = None
        history_files = None
        if source == "fs":
            paths = list(grant.paths) if grant.paths else [
                str(p) for p in default_fs_watch_paths()
            ]
        elif source == "git":
            repos = list(grant.repos) if grant.repos else [str(resolve_workspace())]
        elif source == "terminal":
            history_files = [str(p) for p in discover_history_files()]
        elif source == "browser" and not discover_browser_dbs():
            print(t("aware.grant_no_browser"))

        grant_source(
            source,
            paths=paths,
            repos=repos,
            history_files=history_files,
        )
        log_event("aware.grant", source=source, summary=f"granted {source}")
        print(t("aware.grant_ok", source=source))
    return 0


def _cmd_ungrant(args: argparse.Namespace) -> int:
    sources = list(getattr(args, "sources", []) or [])
    if not sources:
        print(t("aware.ungrant_usage"))
        return 1
    for source in sources:
        if source != "all" and source not in ALL_SOURCES:
            print(t("aware.ungrant_unknown", source=source))
            return 1
        ungrant_source(source)
        log_event("aware.ungrant", source=source, summary=f"ungranted {source}")
        print(t("aware.ungrant_ok", source=source))
    return 0


def _cmd_paths(args: argparse.Namespace) -> int:
    sub = getattr(args, "paths_action", "list") or "list"
    profile = load_profile()
    grant = profile.grant_for("fs")
    if sub == "list":
        paths = grant.paths or [str(p) for p in default_fs_watch_paths()]
        print(t("aware.paths_list"))
        for p in paths:
            print(f"  - {p}")
        return 0
    if sub == "add":
        path = Path(getattr(args, "path", "")).expanduser().resolve()
        if not path.is_dir():
            print(t("aware.paths_not_dir", path=path))
            return 1
        paths = list(grant.paths) if grant.paths else [
            str(p) for p in default_fs_watch_paths()
        ]
        s = str(path)
        if s not in paths:
            paths.append(s)
        grant.paths = paths
        if not grant.granted:
            print(t("aware.paths_hint_grant"))
        save_profile(profile)
        print(t("aware.paths_added", path=s))
        return 0
    if sub == "rm":
        target = str(Path(getattr(args, "path", "")).expanduser().resolve())
        grant.paths = [p for p in (grant.paths or []) if p != target]
        save_profile(profile)
        print(t("aware.paths_removed", path=target))
        return 0
    print(t("aware.paths_usage"))
    return 1


def _cmd_schedule(args: argparse.Namespace) -> int:
    sub = getattr(args, "schedule_action", "status") or "status"
    if sub == "status":
        st = schedule_status()
        print(
            t(
                "aware.schedule_status",
                state="on" if st.enabled else "off",
                backend=st.backend,
                minutes=st.interval_minutes,
                detail=st.detail,
            )
        )
        return 0
    if sub == "on":
        try:
            st = enable_schedule(interval_minutes=getattr(args, "interval", None))
        except RuntimeError as exc:
            print(t("aware.schedule_on_fail", exc=exc))
            return 1
        print(t("aware.schedule_on_ok", backend=st.backend, detail=st.detail))
        return 0
    if sub == "off":
        st = disable_schedule()
        print(t("aware.schedule_off_ok", detail=st.detail))
        return 0
    print(t("aware.schedule_usage"))
    return 1


def _cmd_tick(args: argparse.Namespace) -> int:
    source = getattr(args, "source", None) or None
    detail = bool(getattr(args, "detail", False))
    result = run_tick()
    if result.skipped:
        print(t("aware.tick_skipped", reason=result.skipped))
        return 0
    for line in result.auto:
        print(t("aware.tick_auto", line=line))
    if result.suggestions:
        print(t("aware.tick_sug_new", n=len(result.suggestions)))
    for err in result.errors:
        print(t("aware.tick_error", err=err))
    print(
        format_view(
            mode="delta",
            source=source,
            delta_events=result.events,
            detail=detail,
        ),
        end="",
    )
    from localagent.aware.repl import run_aware_chat, should_enter_aware_chat

    if should_enter_aware_chat(no_chat=bool(getattr(args, "no_chat", False))):
        return run_aware_chat(
            mode="delta",
            source=source,
            provider=str(getattr(args, "provider", None) or "auto"),
        )
    return 0


def _cmd_suggestion(args: argparse.Namespace) -> int:
    action = getattr(args, "suggestion_action", None) or "list"
    if action in (None, "list"):
        return _cmd_suggestion_list()
    if action == "approve":
        return _cmd_suggestion_approve(args)
    if action == "reject":
        return _cmd_suggestion_reject(args)
    print(t("aware.sug_usage"))
    return 1


def _cmd_suggestion_list() -> int:
    items = load_suggestions()
    if not items:
        print(t("aware.sug_empty"))
        return 0
    print(t("aware.sug_list_header", n=len(items)))
    for item in items:
        print(f"  [{item.id}] ({item.source}) {item.title}")
        print(f"      {item.rationale}")
        print(f"      → {item.suggested_cmd}")
    print(t("aware.sug_help"))
    return 0


def _cmd_suggestion_approve(args: argparse.Namespace) -> int:
    target = getattr(args, "target", "") or ""
    items = load_suggestions()
    if target == "all":
        chosen = list(items)
    else:
        item = get_item(target)
        if not item:
            print(t("aware.sug_not_found", target=target))
            return 1
        chosen = [item]
    ok = 0
    for item in chosen:
        cmd = item.suggested_cmd.strip()
        if not is_allowed_cmd(cmd):
            print(t("aware.sug_deny_cmd", cmd=cmd))
            continue
        if is_ack_only_cmd(cmd):
            remove_items([item.id])
            kind = str(item.data.get("kind") or "insight")
            print(t("aware.sug_acked", kind=kind, title=item.title))
            log_event("aware.approve", summary=cmd, item_id=item.id, exit_code=0)
            ok += 1
            continue
        if cmd.startswith("LA "):
            cmd = "la " + cmd[3:]
        argv = shlex.split(cmd)
        if argv and argv[0] in {"la", "LA"}:
            argv = [sys.executable, "-m", "localagent.cli", *argv[1:]]
        print(t("aware.sug_exec", cmd=item.suggested_cmd))
        proc = subprocess.run(argv, check=False)
        log_event(
            "aware.approve",
            summary=item.suggested_cmd,
            item_id=item.id,
            exit_code=proc.returncode,
        )
        if proc.returncode == 0:
            remove_items([item.id])
            ok += 1
        else:
            print(t("aware.sug_exit_code", code=proc.returncode))
    print(t("aware.sug_approved", ok=ok, total=len(chosen)))
    return 0 if ok == len(chosen) else 1


def _cmd_suggestion_reject(args: argparse.Namespace) -> int:
    target = getattr(args, "target", "") or ""
    if target == "all":
        n = remove_items(all_items=True)
    else:
        n = remove_items([target])
    print(t("aware.sug_rejected", n=n))
    return 0 if n else 1


def _cmd_events(args: argparse.Namespace) -> int:
    from collections import Counter

    source = getattr(args, "source", None) or None
    since_hours = int(getattr(args, "since_hours", 24) or 24)
    limit = int(getattr(args, "limit", 50) or 50)
    raw = bool(getattr(args, "raw", False))
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    events = load_events(source=source, since=since, limit=limit if raw else 500)
    if not events:
        print(t("aware.events_none"))
        return 0
    if not raw:
        by_src = Counter(e.source for e in events)
        print(t("aware.events_summary", hours=since_hours))
        for src, n in by_src.most_common():
            sample = [e.title for e in events if e.source == src][-3:]
            print(f"  {src} · {n}  · {', '.join(sample)}")
        print(t("aware.events_total", n=len(events)))
        return 0
    for ev in events[:limit]:
        print(f"[{ev.ts}] {ev.source}/{ev.kind} · {ev.title}")
    print(t("aware.events_total", n=min(len(events), limit)))
    return 0
