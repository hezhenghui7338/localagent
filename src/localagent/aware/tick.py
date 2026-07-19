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
from localagent.i18n import t


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


def _record_tick_input(events: list[AwareEvent]) -> None:
    """Record input/presence once per tick using apps focus + same-tick corroboration."""
    apps = [e for e in events if e.source == "apps" and e.kind == "apps.focus"]
    if not apps:
        return
    from localagent.aware.input_activity import counts_as_input, record_input_activity

    last = apps[-1]
    idle = last.data.get("idle_seconds")
    idle_f = float(idle) if idle is not None else None
    scene = str(last.data.get("scene") or "")
    corroborated = any(e.source in {"fs", "terminal", "git"} for e in events)
    record_input_activity(
        app=str(last.data.get("app") or ""),
        idle_seconds=idle_f,
        error=str(last.data.get("error") or ""),
        scene=scene,
        corroborated=corroborated,
    )
    # Align event flag with final accounting (sensor path has no same-tick corroboration).
    if idle_f is not None:
        from localagent.aware.input_activity import is_input_active

        hid = is_input_active(
            idle_seconds=idle_f,
            app=str(last.data.get("app") or ""),
            error=str(last.data.get("error") or ""),
        )
        last.data["input_active"] = bool(
            hid and counts_as_input(scene=scene, corroborated=corroborated)
        )


def run_tick() -> TickResult:
    lock_fh = try_acquire_tick_lock()
    if lock_fh is None:
        return TickResult(skipped=t("aware.tick_skip_busy"))

    try:
        return _run_tick_locked()
    finally:
        release_tick_lock(lock_fh)


def _run_tick_locked() -> TickResult:
    profile = load_profile()
    active = iter_active_sensors(profile)
    if not active:
        return TickResult(skipped=t("aware.tick_skip_no_sensors"))

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
            # Defer input accounting until all sensors finish (same-tick corroboration).
            if name == "apps":
                events, new_cursor = sensor.collect(cursor, record_activity=False)
            else:
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

    try:
        _record_tick_input(all_events)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"input: {exc}")

    # Reduce: episodes (no LLM). Reason/summary runs only on user pull.
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

    # Reduce: hot/diff cards for Reason injection.
    try:
        from localagent.aware.context_store import refresh_context_artifacts

        refresh_context_artifacts(all_events)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"context: {exc}")

    # Reduce: daily rollups for historical queries (coarse, no URLs).
    try:
        from localagent.aware.rollup import refresh_recent_rollups

        refresh_recent_rollups(days=2)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"rollup: {exc}")

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
