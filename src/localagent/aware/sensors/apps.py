"""Frontmost app + Now Playing sensor (macOS JXA; best-effort elsewhere)."""

from __future__ import annotations

import json
import platform
import subprocess
from typing import Any

from localagent.aware.engagement import (
    classify_engagement,
    tick_interval_sec,
    update_idle_stats,
)
from localagent.aware.profile import SourceGrant
from localagent.aware.types import AwareEvent, utc_now
from localagent.i18n import t

_JXA = r"""
function run() {
  var out = {
    app: "",
    bundle_id: "",
    window_title: "",
    media_title: "",
    media_artist: "",
    media_app: "",
    error: ""
  };
  try {
    var se = Application("System Events");
    var procs = se.applicationProcesses.whose({frontmost: true});
    if (procs.length) {
      var front = procs[0];
      try { out.app = String(front.name() || ""); } catch (e1) {}
      try { out.bundle_id = String(front.bundleIdentifier() || ""); } catch (e2) {}
      try {
        var wins = front.windows();
        if (wins.length) out.window_title = String(wins[0].name() || "");
      } catch (e3) {}
    }
  } catch (err) {
    out.error = String(err);
  }
  // Prefer Spotify if playing, else Music.app
  try {
    var spot = Application("Spotify");
    if (spot.running() && String(spot.playerState()) === "playing") {
      out.media_title = String(spot.currentTrack.name() || "");
      out.media_artist = String(spot.currentTrack.artist() || "");
      out.media_app = "Spotify";
    }
  } catch (e4) {}
  if (!out.media_title) {
    try {
      var music = Application("Music");
      if (music.running() && String(music.playerState()) === "playing") {
        out.media_title = String(music.currentTrack.name() || "");
        out.media_artist = String(music.currentTrack.artist() || "");
        out.media_app = "Music";
      }
    } catch (e5) {}
  }
  return JSON.stringify(out);
}
"""


class AppsSensor:
    name = "apps"

    def __init__(self, grant: SourceGrant) -> None:
        self.grant = grant

    def describe_access(self) -> list[str]:
        return [
            t("aware.sensor_apps_front"),
            t("aware.sensor_apps_media"),
            t("aware.sensor_apps_idle"),
            t("aware.sensor_apps_note"),
        ]

    def collect(
        self,
        cursor: dict[str, Any],
        *,
        record_activity: bool = True,
    ) -> tuple[list[AwareEvent], dict[str, Any]]:
        snap = _collect_focus_snapshot()
        idle = _idle_seconds()
        if idle is not None:
            snap["idle_seconds"] = idle

        app = str(snap.get("app") or "")
        title = str(snap.get("window_title") or "")
        media_title = str(snap.get("media_title") or "")
        err = str(snap.get("error") or "")
        label = app or "(unknown)"
        if media_title:
            headline = f"{label} · ♪ {media_title}"
        elif title:
            headline = f"{label} · {title[:80]}"
        else:
            headline = label

        focus_key = f"{app}|{title}|{media_title}"
        now = utc_now()
        quantum = tick_interval_sec()
        prev_session = dict(cursor.get("session") or {})
        same = (
            bool(focus_key.strip("|"))
            and prev_session.get("focus_key") == focus_key
            and not err
        )

        if same:
            ticks_seen = int(prev_session.get("ticks_seen") or 1) + 1
            focus_since = str(prev_session.get("focus_since") or now)
            session = update_idle_stats(prev_session, idle)
        else:
            ticks_seen = 1
            focus_since = now
            session = update_idle_stats({}, idle)

        dwell_sec = float(ticks_seen) * quantum
        engagement = classify_engagement(
            ticks_seen=ticks_seen,
            dwell_sec=dwell_sec,
            idle_seconds=idle,
            interval_sec=quantum,
        )

        from localagent.aware.input_activity import (
            counts_as_input,
            is_input_active,
            record_input_activity,
        )
        from localagent.aware.scenes import classify_focus

        scene = classify_focus(
            app=app,
            bundle_id=str(snap.get("bundle_id") or ""),
            window_title=title,
            media_title=media_title,
            media_app=str(snap.get("media_app") or ""),
        )
        hid_active = is_input_active(idle_seconds=idle, app=app, error=err)
        # Sensor-local recording has no same-tick fs/term/git yet; tick may re-record
        # with corroborated=True. input_active on the event means corroborated input.
        input_active = hid_active and counts_as_input(scene=scene, corroborated=False)
        if record_activity:
            record_input_activity(
                app=app,
                idle_seconds=idle,
                error=err,
                scene=scene,
                corroborated=False,
            )
        event = AwareEvent(
            source="apps",
            kind="apps.focus",
            title=headline[:120],
            data={
                "app": app,
                "bundle_id": snap.get("bundle_id") or "",
                "window_title": title,
                "media_title": media_title,
                "media_artist": snap.get("media_artist") or "",
                "media_app": snap.get("media_app") or "",
                "idle_seconds": snap.get("idle_seconds"),
                "scene": scene,
                "error": err,
                "focus_key": focus_key,
                "focus_since": focus_since,
                "ticks_seen": ticks_seen,
                "dwell_sec": dwell_sec,
                "engagement": engagement,
                "input_active": input_active,
            },
        )

        session.update(
            {
                "focus_key": focus_key,
                "focus_since": focus_since,
                "last_seen_at": now,
                "ticks_seen": ticks_seen,
                "dwell_sec": dwell_sec,
                "engagement": engagement,
            }
        )
        new_cursor = {
            "last": {
                "app": app,
                "window_title": title,
                "media_title": media_title,
                "media_artist": snap.get("media_artist") or "",
                "media_app": snap.get("media_app") or "",
                "bundle_id": snap.get("bundle_id") or "",
            },
            "session": session,
        }
        return [event], new_cursor


def _collect_focus_snapshot() -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {
            "app": "",
            "error": t("aware.sensor_apps_macos_only"),
        }
    try:
        proc = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", _JXA],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"app": "", "error": t("aware.sensor_apps_osascript_fail", exc=exc)}
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or t("aware.sensor_apps_unknown_err")).strip()
        return {"app": "", "error": err[:200]}
    text = (proc.stdout or "").strip()
    if not text:
        return {"app": "", "error": t("aware.sensor_apps_no_front")}
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        return {"app": "", "error": t("aware.sensor_apps_parse_fail")}
    if not isinstance(raw, dict):
        return {"app": "", "error": t("aware.sensor_apps_format_bad")}
    return {
        "app": str(raw.get("app") or ""),
        "bundle_id": str(raw.get("bundle_id") or ""),
        "window_title": str(raw.get("window_title") or ""),
        "media_title": str(raw.get("media_title") or ""),
        "media_artist": str(raw.get("media_artist") or ""),
        "media_app": str(raw.get("media_app") or ""),
        "error": str(raw.get("error") or ""),
    }


def _idle_seconds() -> float | None:
    """Best-effort HID idle seconds on macOS."""
    if platform.system() != "Darwin":
        return None
    try:
        proc = subprocess.run(
            ["ioreg", "-c", "IOHIDSystem"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in (proc.stdout or "").splitlines():
        if "HIDIdleTime" not in line:
            continue
        # "HIDIdleTime" = 1234567890
        parts = line.split("=")
        if len(parts) < 2:
            continue
        try:
            ns = int(parts[-1].strip())
        except ValueError:
            continue
        return max(0.0, ns / 1_000_000_000.0)
    return None
