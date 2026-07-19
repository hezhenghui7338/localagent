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
        print(f"[aware] 未知子命令: {action}")
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
    print("LocalAgent · Aware")
    print(f"上次 tick · {profile.last_tick_at or '尚未运行'}")
    print(
        f"定时 · {'开' if sched.enabled else '关'} "
        f"({sched.backend}, 每 {sched.interval_minutes} 分钟) · {sched.detail}"
    )
    print(f"今日事件 · {events_count_today()}  |  suggestion · {suggestion_count()}")
    print("授权（grant / ungrant）：")
    for name in ALL_SOURCES:
        g = profile.grant_for(name)
        mark = "✓" if g.granted else "·"
        impl = "" if name in IMPLEMENTED_SOURCES else " (尚未实现)"
        hint = f"  → ungrant {name}" if g.granted and name in IMPLEMENTED_SOURCES else ""
        print(f"  {mark} {name}{impl}{hint}")
    print("查看: la aware · la aware --since 1w · la aware tick")
    print("解除: la aware ungrant <source>|all")
    print("建议: la aware suggestion · approve|reject")
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
        print("[aware] 用法: la aware grant <source>|all …")
        print(f"[aware] 可选: all {' '.join(ALL_SOURCES)}")
        return 1
    yes = bool(getattr(args, "yes", False))

    for source in sources:
        if source not in ALL_SOURCES:
            print(f"[aware] 未知 source: {source}")
            return 1
        if source not in IMPLEMENTED_SOURCES:
            print(f"[aware] {source} 尚未实现，跳过")
            continue

        grant = load_profile().grant_for(source)
        sensor = build_sensor(source, grant)
        print(f"[aware] 将授权读取 ({source})：")
        for line in sensor.describe_access():
            print(f"  - {line}")
        if source in SENSITIVE_SOURCES and not yes:
            if not _confirm(f"确认授权 {source}？"):
                print(f"[aware] 已取消: {source}")
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
            print("[aware] 未发现浏览器 History；仍写入授权")

        grant_source(
            source,
            paths=paths,
            repos=repos,
            history_files=history_files,
        )
        log_event("aware.grant", source=source, summary=f"granted {source}")
        print(f"[aware] 已授权: {source}")
    return 0


def _cmd_ungrant(args: argparse.Namespace) -> int:
    sources = list(getattr(args, "sources", []) or [])
    if not sources:
        print("[aware] 用法: la aware ungrant <source>|all")
        return 1
    for source in sources:
        if source != "all" and source not in ALL_SOURCES:
            print(f"[aware] 未知 source: {source}")
            return 1
        ungrant_source(source)
        log_event("aware.ungrant", source=source, summary=f"ungranted {source}")
        print(f"[aware] 已解除: {source} · 可用 la aware grant {source} 重新授权")
    return 0


def _cmd_paths(args: argparse.Namespace) -> int:
    sub = getattr(args, "paths_action", "list") or "list"
    profile = load_profile()
    grant = profile.grant_for("fs")
    if sub == "list":
        paths = grant.paths or [str(p) for p in default_fs_watch_paths()]
        print("[aware] fs 监视路径：")
        for p in paths:
            print(f"  - {p}")
        return 0
    if sub == "add":
        path = Path(getattr(args, "path", "")).expanduser().resolve()
        if not path.is_dir():
            print(f"[aware] 不是目录: {path}")
            return 1
        paths = list(grant.paths) if grant.paths else [
            str(p) for p in default_fs_watch_paths()
        ]
        s = str(path)
        if s not in paths:
            paths.append(s)
        grant.paths = paths
        if not grant.granted:
            print("[aware] 提示: fs 尚未 grant；请再运行 la aware grant fs")
        save_profile(profile)
        print(f"[aware] 已添加: {s}")
        return 0
    if sub == "rm":
        target = str(Path(getattr(args, "path", "")).expanduser().resolve())
        grant.paths = [p for p in (grant.paths or []) if p != target]
        save_profile(profile)
        print(f"[aware] 已移除: {target}")
        return 0
    print("[aware] paths 子命令: list | add | rm")
    return 1


def _cmd_schedule(args: argparse.Namespace) -> int:
    sub = getattr(args, "schedule_action", "status") or "status"
    if sub == "status":
        st = schedule_status()
        print(
            f"[aware] schedule: {'on' if st.enabled else 'off'} "
            f"backend={st.backend} every={st.interval_minutes}m · {st.detail}"
        )
        return 0
    if sub == "on":
        try:
            st = enable_schedule(interval_minutes=getattr(args, "interval", None))
        except RuntimeError as exc:
            print(f"[aware] schedule on 失败: {exc}")
            return 1
        print(f"[aware] schedule on · {st.backend} · {st.detail}")
        return 0
    if sub == "off":
        st = disable_schedule()
        print(f"[aware] schedule off · {st.detail}")
        return 0
    print("[aware] schedule 子命令: on | off | status")
    return 1


def _cmd_tick(args: argparse.Namespace) -> int:
    source = getattr(args, "source", None) or None
    detail = bool(getattr(args, "detail", False))
    result = run_tick()
    if result.skipped:
        print(f"[aware] tick 跳过: {result.skipped}")
        return 0
    for line in result.auto:
        print(f"  auto · {line}")
    if result.suggestions:
        print(f"  suggestion 新增 · {len(result.suggestions)}（la aware suggestion）")
    for err in result.errors:
        print(f"  ! {err}")
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
    print("[aware] suggestion 子命令: list | approve | reject")
    return 1


def _cmd_suggestion_list() -> int:
    items = load_suggestions()
    if not items:
        print("[aware] suggestion 为空")
        return 0
    print(f"[aware] suggestion ({len(items)})：")
    for item in items:
        print(f"  [{item.id}] ({item.source}) {item.title}")
        print(f"      {item.rationale}")
        print(f"      → {item.suggested_cmd}")
    print(
        "批准: la aware suggestion approve <id>|all\n"
        "拒绝: la aware suggestion reject <id>|all"
    )
    return 0


def _cmd_suggestion_approve(args: argparse.Namespace) -> int:
    target = getattr(args, "target", "") or ""
    items = load_suggestions()
    if target == "all":
        chosen = list(items)
    else:
        item = get_item(target)
        if not item:
            print(f"[aware] 未找到: {target}")
            return 1
        chosen = [item]
    ok = 0
    for item in chosen:
        cmd = item.suggested_cmd.strip()
        if not is_allowed_cmd(cmd):
            print(f"[aware] 拒绝执行非白名单命令: {cmd}")
            continue
        if is_ack_only_cmd(cmd):
            remove_items([item.id])
            kind = str(item.data.get("kind") or "insight")
            print(f"[aware] 已确认 {kind} · {item.title}")
            log_event("aware.approve", summary=cmd, item_id=item.id, exit_code=0)
            ok += 1
            continue
        if cmd.startswith("LA "):
            cmd = "la " + cmd[3:]
        argv = shlex.split(cmd)
        if argv and argv[0] in {"la", "LA"}:
            argv = [sys.executable, "-m", "localagent.cli", *argv[1:]]
        print(f"[aware] 执行: {item.suggested_cmd}")
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
            print(f"[aware] 命令退出码 {proc.returncode}")
    print(f"[aware] 已批准执行 {ok}/{len(chosen)}")
    return 0 if ok == len(chosen) else 1


def _cmd_suggestion_reject(args: argparse.Namespace) -> int:
    target = getattr(args, "target", "") or ""
    if target == "all":
        n = remove_items(all_items=True)
    else:
        n = remove_items([target])
    print(f"[aware] 已拒绝 {n} 条")
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
        print("[aware] 无事件")
        return 0
    if not raw:
        by_src = Counter(e.source for e in events)
        print(f"[aware] 近 {since_hours}h 事件摘要（--raw 看明细）")
        for src, n in by_src.most_common():
            sample = [e.title for e in events if e.source == src][-3:]
            print(f"  {src} · {n}  · {', '.join(sample)}")
        print(f"[aware] 共 {len(events)} 条")
        return 0
    for ev in events[:limit]:
        print(f"[{ev.ts}] {ev.source}/{ev.kind} · {ev.title}")
    print(f"[aware] 共 {min(len(events), limit)} 条")
    return 0
