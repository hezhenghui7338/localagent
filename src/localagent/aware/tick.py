"""Run one aware collection + reaction cycle."""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from localagent import config
from localagent.audit.events import log_event
from localagent.aware.policy import react_to_events
from localagent.aware.profile import load_profile, save_profile
from localagent.aware.sensors import iter_active_sensors
from localagent.aware.store import append_events, load_cursors, save_cursors
from localagent.aware.types import AwareEvent, utc_now


@dataclass
class TickResult:
    sources: list[str] = field(default_factory=list)
    event_count: int = 0
    events: list[AwareEvent] = field(default_factory=list)
    auto: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: str = ""


def _lock_path() -> Path:
    return Path(getattr(config, "AWARE_TICK_LOCK_FILE", config.AWARE_DIR / "tick.lock"))


def try_acquire_tick_lock() -> TextIO[Any] | None:
    """Non-blocking exclusive lock so overlapping schedules cannot stack."""
    path = _lock_path()
    config.ensure_data_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+", encoding="utf-8")
    try:
        if sys.platform == "win32":
            import msvcrt

            fh.seek(0)
            if fh.read(1) == "":
                fh.write("0")
                fh.flush()
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        return fh
    except OSError:
        fh.close()
        return None


def release_tick_lock(fh: TextIO[Any] | None) -> None:
    if fh is None:
        return
    try:
        if sys.platform == "win32":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        fh.close()
    except OSError:
        pass


def run_tick() -> TickResult:
    lock_fh = try_acquire_tick_lock()
    if lock_fh is None:
        return TickResult(skipped="another tick is already running")

    try:
        return _run_tick_locked()
    finally:
        release_tick_lock(lock_fh)


def _run_tick_locked() -> TickResult:
    profile = load_profile()
    active = iter_active_sensors(profile)
    if not active:
        return TickResult(
            skipped="无已授权且已实现的传感器；先 la aware grant fs git terminal browser apps"
        )

    deadline_sec = float(getattr(config, "AWARE_TICK_DEADLINE_SEC", 20) or 20)
    deadline = time.monotonic() + max(1.0, deadline_sec)
    cursors = load_cursors()
    all_events: list[AwareEvent] = []
    sources: list[str] = []
    errors: list[str] = []

    for name, sensor in active:
        if time.monotonic() >= deadline:
            errors.append("tick deadline exceeded; remaining sensors skipped")
            log_event("aware.tick", summary="deadline exceeded", sources=sources)
            break
        sources.append(name)
        cursor = dict(cursors.get(name) or {})
        try:
            events, new_cursor = sensor.collect(cursor)
        except Exception as exc:  # noqa: BLE001
            log_event("aware.tick", source=name, summary=f"sensor error: {exc}")
            errors.append(f"{name}: {exc}")
            continue
        cursors[name] = new_cursor
        all_events.extend(events)

    # Refresh browser "now" snapshot alongside tick when granted
    if profile.is_granted("browser") and time.monotonic() < deadline:
        try:
            from localagent.aware.digest import _render_browser_now

            _render_browser_now()
        except Exception:  # noqa: BLE001
            pass

    append_events(all_events)
    save_cursors(cursors)

    if all_events:
        try:
            from localagent.aware.episode import ingest_tick_episodes

            ingest_tick_episodes(all_events)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"episode: {exc}")

    # Drop legacy mislabeled browser dwell cards (pre-frontmost-gate) once.
    try:
        from localagent.aware.episode import maybe_rebuild_stale_episodes

        maybe_rebuild_stale_episodes(since_hours=24)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"episode-rebuild: {exc}")

    # Policy only enqueues suggestions (never auto-ingests into kb).
    reaction = (
        react_to_events(all_events)
        if all_events
        else {"auto": [], "suggestions": [], "errors": []}
    )
    # Wellness / hypothesis may still run from accumulated history on an empty tick.
    if not all_events:
        try:
            from localagent.aware.episode import maybe_enqueue_active_hours_wellness

            maybe_enqueue_active_hours_wellness()
        except Exception:  # noqa: BLE001
            pass
        try:
            from localagent.aware.hypothesis import run_hypothesis_loop

            run_hypothesis_loop(force=False)
        except Exception:  # noqa: BLE001
            pass

    profile.last_tick_at = utc_now()
    save_profile(profile)
    log_event(
        "aware.tick",
        summary=f"events={len(all_events)} sources={','.join(sources)}",
        event_count=len(all_events),
        sources=sources,
    )

    return TickResult(
        sources=sources,
        event_count=len(all_events),
        events=all_events,
        auto=list(reaction.get("auto") or []),
        suggestions=list(reaction.get("suggestions") or []),
        errors=list(reaction.get("errors") or []) + errors,
    )
