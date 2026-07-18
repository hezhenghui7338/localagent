"""OS-level schedule for daily news sync (launchd / crontab)."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from localagent import config
from localagent.news.profile import load_news_profile, save_news_profile

LAUNCH_LABEL = "dev.localagent.news-sync"
CRON_MARKER = "# localagent-news-sync"


@dataclass
class ScheduleStatus:
    enabled: bool
    backend: str  # launchd | cron | none
    detail: str
    hour: int
    minute: int


def _resolve_la_bin() -> str:
    """Prefer the running interpreter's `la` console script."""
    which = shutil.which("la") or shutil.which("LA")
    if which:
        return which
    # Fallback: python -m
    import sys

    return f"{sys.executable} -m localagent.cli"


def _launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _plist_path() -> Path:
    return _launch_agents_dir() / f"{LAUNCH_LABEL}.plist"


def _plist_body(*, hour: int, minute: int, la_bin: str) -> str:
    # Split "python -m ..." into ProgramArguments
    parts = la_bin.split()
    if len(parts) == 1:
        args_xml = f"        <string>{parts[0]}</string>\n        <string>news</string>\n        <string>sync</string>\n"
    else:
        arg_lines = "\n".join(f"        <string>{p}</string>" for p in parts)
        args_xml = f"{arg_lines}\n        <string>news</string>\n        <string>sync</string>\n"
    log = config.NEWS_SYNC_LOG_FILE
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCH_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>{hour}</integer>
        <key>Minute</key>
        <integer>{minute}</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
    <key>WorkingDirectory</key>
    <string>{config.PROJECT_ROOT}</string>
</dict>
</plist>
"""


def _cron_line(*, hour: int, minute: int, la_bin: str) -> str:
    return f"{minute} {hour} * * * {la_bin} news sync {CRON_MARKER}\n"


def schedule_status() -> ScheduleStatus:
    profile = load_news_profile()
    hour = profile.auto_sync_hour
    minute = profile.auto_sync_minute
    system = platform.system()
    if system == "Windows":
        return ScheduleStatus(
            enabled=False,
            backend="none",
            detail="Windows 暂不支持 la news schedule（请手动运行: la news sync）",
            hour=hour,
            minute=minute,
        )
    if system == "Darwin":
        path = _plist_path()
        if path.exists():
            return ScheduleStatus(
                enabled=True,
                backend="launchd",
                detail=str(path),
                hour=hour,
                minute=minute,
            )
        return ScheduleStatus(
            enabled=False,
            backend="launchd",
            detail="未安装 LaunchAgent",
            hour=hour,
            minute=minute,
        )
    # Linux / others: crontab
    try:
        out = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            check=False,
        )
        text = out.stdout or ""
        enabled = CRON_MARKER in text
        return ScheduleStatus(
            enabled=enabled,
            backend="cron",
            detail="crontab 已含 news sync" if enabled else "crontab 未配置",
            hour=hour,
            minute=minute,
        )
    except FileNotFoundError:
        return ScheduleStatus(
            enabled=False,
            backend="none",
            detail="本机无 crontab",
            hour=hour,
            minute=minute,
        )


def enable_schedule(*, hour: int | None = None, minute: int | None = None) -> ScheduleStatus:
    if not config.NEWS_AUTO_SYNC:
        raise RuntimeError("LA_NEWS_AUTO_SYNC=0，拒绝安装定时任务。设为 1 后再试。")

    if platform.system() == "Windows":
        raise RuntimeError(
            "Windows 暂不支持 la news schedule。"
            "请手动运行: la news sync；或用系统「任务计划程序」定时执行该命令。"
        )

    profile = load_news_profile()
    h = hour if hour is not None else profile.auto_sync_hour
    m = minute if minute is not None else profile.auto_sync_minute
    profile.auto_sync_enabled = True
    profile.auto_sync_hour = h
    profile.auto_sync_minute = m
    save_news_profile(profile)

    config.ensure_data_dirs()
    la_bin = _resolve_la_bin()
    system = platform.system()

    if system == "Darwin":
        agents = _launch_agents_dir()
        agents.mkdir(parents=True, exist_ok=True)
        path = _plist_path()
        path.write_text(_plist_body(hour=h, minute=m, la_bin=la_bin), encoding="utf-8")
        # Load (best-effort; may fail in sandbox)
        subprocess.run(
            ["launchctl", "unload", str(path)],
            capture_output=True,
            check=False,
        )
        loaded = subprocess.run(
            ["launchctl", "load", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        detail = str(path)
        if loaded.returncode != 0:
            detail += f" （launchctl load 提示: {(loaded.stderr or loaded.stdout or '').strip() or '需本机手动 load'}）"
        return ScheduleStatus(
            enabled=True, backend="launchd", detail=detail, hour=h, minute=m
        )

    # crontab
    existing = ""
    listed = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True, check=False
    )
    if listed.returncode == 0:
        existing = listed.stdout or ""
    lines = [ln for ln in existing.splitlines() if CRON_MARKER not in ln]
    lines.append(_cron_line(hour=h, minute=m, la_bin=la_bin).rstrip())
    new_cron = "\n".join(lines) + "\n"
    proc = subprocess.run(
        ["crontab", "-"],
        input=new_cron,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "crontab 写入失败")
    return ScheduleStatus(
        enabled=True, backend="cron", detail="已写入用户 crontab", hour=h, minute=m
    )


def disable_schedule() -> ScheduleStatus:
    profile = load_news_profile()
    profile.auto_sync_enabled = False
    save_news_profile(profile)

    system = platform.system()
    if system == "Windows":
        return ScheduleStatus(
            enabled=False,
            backend="none",
            detail="Windows 无新闻定时任务可卸载；请手动运行: la news sync",
            hour=profile.auto_sync_hour,
            minute=profile.auto_sync_minute,
        )
    if system == "Darwin":
        path = _plist_path()
        if path.exists():
            subprocess.run(
                ["launchctl", "unload", str(path)],
                capture_output=True,
                check=False,
            )
            try:
                path.unlink()
            except OSError:
                pass
        return ScheduleStatus(
            enabled=False,
            backend="launchd",
            detail="已卸载 LaunchAgent",
            hour=profile.auto_sync_hour,
            minute=profile.auto_sync_minute,
        )

    listed = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True, check=False
    )
    if listed.returncode == 0 and listed.stdout:
        lines = [ln for ln in listed.stdout.splitlines() if CRON_MARKER not in ln]
        subprocess.run(
            ["crontab", "-"],
            input=("\n".join(lines) + "\n") if lines else "",
            text=True,
            capture_output=True,
            check=False,
        )
    return ScheduleStatus(
        enabled=False,
        backend="cron",
        detail="已从 crontab 移除",
        hour=profile.auto_sync_hour,
        minute=profile.auto_sync_minute,
    )
