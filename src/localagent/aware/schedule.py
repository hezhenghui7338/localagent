"""OS-level schedule for `la aware tick` (launchd / crontab / schtasks)."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from localagent import config
from localagent.aware.profile import load_profile, save_profile
from localagent.i18n import t

LAUNCH_LABEL = "dev.localagent.aware-tick"
CRON_MARKER = "# localagent-aware-tick"
SCHTASKS_NAME = "LocalAgentAwareTick"


@dataclass
class ScheduleStatus:
    enabled: bool
    backend: str  # launchd | cron | schtasks | none
    detail: str
    interval_minutes: int


def _resolve_la_bin() -> str:
    which = shutil.which("la") or shutil.which("LA")
    if which:
        return which
    import sys

    return f"{sys.executable} -m localagent.cli"


def _launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _plist_path() -> Path:
    return _launch_agents_dir() / f"{LAUNCH_LABEL}.plist"


def _plist_body(*, interval_minutes: int, la_bin: str) -> str:
    parts = la_bin.split()
    if len(parts) == 1:
        args_xml = (
            f"        <string>{parts[0]}</string>\n"
            "        <string>aware</string>\n"
            "        <string>tick</string>\n"
        )
    else:
        arg_lines = "\n".join(f"        <string>{p}</string>" for p in parts)
        args_xml = f"{arg_lines}\n        <string>aware</string>\n        <string>tick</string>\n"
    log = config.AWARE_TICK_LOG_FILE
    seconds = max(60, int(interval_minutes) * 60)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCH_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}    </array>
    <key>StartInterval</key>
    <integer>{seconds}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>ProcessType</key>
    <string>Background</string>
    <key>Nice</key>
    <integer>10</integer>
    <key>LowPriorityIO</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
    <key>WorkingDirectory</key>
    <string>{config.PROJECT_ROOT}</string>
</dict>
</plist>
"""


def _cron_line(*, interval_minutes: int, la_bin: str) -> str:
    # cron has no pure "every N minutes" for arbitrary N; use */N when N divides 60
    n = max(1, int(interval_minutes))
    if 60 % n == 0:
        spec = f"*/{n} * * * *"
    else:
        spec = "*/15 * * * *"
    return f"{spec} {la_bin} aware tick {CRON_MARKER}\n"


def schedule_status() -> ScheduleStatus:
    profile = load_profile()
    minutes = profile.interval_minutes or config.AWARE_TICK_INTERVAL_MINUTES
    system = platform.system()

    if system == "Darwin":
        path = _plist_path()
        if path.exists():
            return ScheduleStatus(True, "launchd", str(path), minutes)
        return ScheduleStatus(False, "launchd", t("aware.sched_launchd_missing"), minutes)

    if system == "Windows":
        listed = subprocess.run(
            ["schtasks", "/Query", "/TN", SCHTASKS_NAME],
            capture_output=True,
            text=True,
            check=False,
        )
        if listed.returncode == 0:
            return ScheduleStatus(True, "schtasks", SCHTASKS_NAME, minutes)
        return ScheduleStatus(False, "schtasks", t("aware.sched_schtasks_missing"), minutes)

    # Linux / others
    try:
        out = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, check=False
        )
        text = out.stdout or ""
        enabled = CRON_MARKER in text
        return ScheduleStatus(
            enabled,
            "cron",
            t("aware.sched_cron_on") if enabled else t("aware.sched_cron_off"),
            minutes,
        )
    except FileNotFoundError:
        return ScheduleStatus(False, "none", t("aware.sched_no_crontab"), minutes)


def enable_schedule(*, interval_minutes: int | None = None) -> ScheduleStatus:
    profile = load_profile()
    minutes = interval_minutes if interval_minutes is not None else (
        profile.interval_minutes or config.AWARE_TICK_INTERVAL_MINUTES
    )
    profile.schedule_enabled = True
    profile.interval_minutes = minutes
    save_profile(profile)
    config.ensure_data_dirs()
    la_bin = _resolve_la_bin()
    system = platform.system()

    if system == "Darwin":
        agents = _launch_agents_dir()
        agents.mkdir(parents=True, exist_ok=True)
        path = _plist_path()
        path.write_text(_plist_body(interval_minutes=minutes, la_bin=la_bin), encoding="utf-8")
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True, check=False)
        loaded = subprocess.run(
            ["launchctl", "load", str(path)], capture_output=True, text=True, check=False
        )
        detail = str(path)
        if loaded.returncode != 0:
            msg = (loaded.stderr or loaded.stdout or "").strip() or t(
                "aware.sched_launchctl_manual"
            )
            detail += t("aware.sched_launchctl_suffix", msg=msg)
        return ScheduleStatus(True, "launchd", detail, minutes)

    if system == "Windows":
        # schtasks /SC MINUTE /MO N
        cmd = [
            "schtasks",
            "/Create",
            "/F",
            "/TN",
            SCHTASKS_NAME,
            "/TR",
            f'"{la_bin}" aware tick',
            "/SC",
            "MINUTE",
            "/MO",
            str(max(1, minutes)),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(
                (proc.stderr or proc.stdout or t("aware.sched_schtasks_fail")).strip()
                + t("aware.sched_schtasks_hint")
            )
        return ScheduleStatus(True, "schtasks", SCHTASKS_NAME, minutes)

    existing = ""
    listed = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if listed.returncode == 0:
        existing = listed.stdout or ""
    lines = [ln for ln in existing.splitlines() if CRON_MARKER not in ln]
    lines.append(_cron_line(interval_minutes=minutes, la_bin=la_bin).rstrip())
    proc = subprocess.run(
        ["crontab", "-"],
        input="\n".join(lines) + "\n",
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or t("aware.sched_cron_write_fail"))
    return ScheduleStatus(True, "cron", t("aware.sched_cron_written"), minutes)


def disable_schedule() -> ScheduleStatus:
    profile = load_profile()
    profile.schedule_enabled = False
    save_profile(profile)
    minutes = profile.interval_minutes or config.AWARE_TICK_INTERVAL_MINUTES
    system = platform.system()

    if system == "Darwin":
        path = _plist_path()
        if path.exists():
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True, check=False)
            try:
                path.unlink()
            except OSError:
                pass
        return ScheduleStatus(False, "launchd", t("aware.sched_launchd_unloaded"), minutes)

    if system == "Windows":
        subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", SCHTASKS_NAME],
            capture_output=True,
            check=False,
        )
        return ScheduleStatus(False, "schtasks", t("aware.sched_schtasks_deleted"), minutes)

    listed = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if listed.returncode == 0 and listed.stdout:
        lines = [ln for ln in listed.stdout.splitlines() if CRON_MARKER not in ln]
        subprocess.run(
            ["crontab", "-"],
            input=("\n".join(lines) + "\n") if lines else "",
            text=True,
            capture_output=True,
            check=False,
        )
    return ScheduleStatus(False, "cron", t("aware.sched_cron_removed"), minutes)
