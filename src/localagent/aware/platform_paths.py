"""Cross-platform path discovery for aware sensors."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


def home() -> Path:
    return Path.home()


def default_fs_watch_paths() -> list[Path]:
    """Default directories for fs sensor (common user folders + workspace)."""
    paths: list[Path] = []
    h = home()
    for name in ("Downloads", "Desktop", "Documents"):
        candidate = h / name
        if candidate.is_dir() and candidate not in paths:
            paths.append(candidate)
    ws = os.getenv("LA_WORKSPACE", "").strip()
    if ws:
        root = Path(ws).expanduser()
        if root.is_dir() and root not in paths:
            paths.append(root)
    return paths


def discover_history_files() -> list[Path]:
    """Shell / PowerShell history files that exist on this machine."""
    h = home()
    candidates: list[Path] = [
        h / ".zsh_history",
        h / ".bash_history",
        h / ".local" / "share" / "fish" / "fish_history",
    ]
    system = platform.system()
    if system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidates.append(
                Path(appdata)
                / "Microsoft"
                / "Windows"
                / "PowerShell"
                / "PSReadLine"
                / "ConsoleHost_history.txt"
            )
        candidates.append(h / ".bash_history")
    elif system == "Darwin":
        # zsh default on modern macOS
        pass
    out: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        key = str(resolved)
        if key in seen:
            continue
        if resolved.is_file():
            seen.add(key)
            out.append(resolved)
    return out


@dataclass(frozen=True)
class BrowserDb:
    browser: str
    engine: str  # chromium | safari | firefox
    path: Path
    profile: str = "Default"


def discover_browser_dbs() -> list[BrowserDb]:
    """Find installed browser history databases (existence only; may still need FDA)."""
    h = home()
    system = platform.system()
    found: list[BrowserDb] = []

    chromium_specs: list[tuple[str, Path]] = []
    if system == "Darwin":
        support = h / "Library" / "Application Support"
        chromium_specs = [
            ("chrome", support / "Google" / "Chrome"),
            ("edge", support / "Microsoft Edge"),
            ("brave", support / "BraveSoftware" / "Brave-Browser"),
            ("chromium", support / "Chromium"),
        ]
        safari = h / "Library" / "Safari" / "History.db"
        if safari.is_file():
            found.append(BrowserDb("safari", "safari", safari, profile="default"))
    elif system == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", h / "AppData" / "Local"))
        chromium_specs = [
            ("chrome", local / "Google" / "Chrome" / "User Data"),
            ("edge", local / "Microsoft" / "Edge" / "User Data"),
            ("brave", local / "BraveSoftware" / "Brave-Browser" / "User Data"),
            ("chromium", local / "Chromium" / "User Data"),
        ]
    else:  # Linux and others
        chromium_specs = [
            ("chrome", h / ".config" / "google-chrome"),
            ("edge", h / ".config" / "microsoft-edge"),
            ("brave", h / ".config" / "BraveSoftware" / "Brave-Browser"),
            ("chromium", h / ".config" / "chromium"),
        ]

    for name, root in chromium_specs:
        if not root.is_dir():
            continue
        for profile in ("Default", "Profile 1", "Profile 2"):
            hist = root / profile / "History"
            if hist.is_file():
                found.append(BrowserDb(name, "chromium", hist, profile=profile))

    # Firefox places.sqlite
    ff_roots: list[Path] = []
    if system == "Darwin":
        ff_roots.append(h / "Library" / "Application Support" / "Firefox" / "Profiles")
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            ff_roots.append(Path(appdata) / "Mozilla" / "Firefox" / "Profiles")
    else:
        ff_roots.append(h / ".mozilla" / "firefox")

    for root in ff_roots:
        if not root.is_dir():
            continue
        try:
            for profile_dir in root.iterdir():
                if not profile_dir.is_dir():
                    continue
                places = profile_dir / "places.sqlite"
                if places.is_file():
                    found.append(
                        BrowserDb("firefox", "firefox", places, profile=profile_dir.name)
                    )
        except OSError:
            continue

    return found


def default_app_dirs() -> list[Path]:
    """Application install directories (for future apps sensor)."""
    system = platform.system()
    h = home()
    if system == "Darwin":
        return [Path("/Applications"), h / "Applications"]
    if system == "Windows":
        return [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
        ]
    return [h / ".local" / "share" / "applications", Path("/usr/share/applications")]
