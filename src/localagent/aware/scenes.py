"""Rule-table scene classification for aware focus / browser signals."""

from __future__ import annotations

import re
from urllib.parse import urlparse

# (priority, scene, matcher kwargs checked in classify_focus)
_CODING_APPS = frozenset(
    {
        "cursor",
        "code",
        "visual studio code",
        "code - insiders",
        "pycharm",
        "intellij idea",
        "webstorm",
        "goland",
        "xcode",
        "sublime text",
        "zed",
        "neovim",
        "vim",
        "emacs",
        "terminal",
        "iterm2",
        "warp",
        "kitty",
        "alacritty",
    }
)
_CODING_BUNDLES = (
    "com.todesktop.",
    "com.microsoft.vscode",
    "com.jetbrains.",
    "com.apple.dt.xcode",
    "dev.zed.zed",
)

_CALL_APPS = frozenset(
    {
        "zoom",
        "zoom.us",
        "zoom workplace",
        "microsoft teams",
        "teams",
        "facetime",
        "skype",
        "webex",
        "slack",
        "discord",
        "飞书",
        "lark",
        "企业微信",
        "tencent meeting",
        "腾讯会议",
        "voov meeting",
    }
)
_CALL_TITLE_RE = re.compile(
    r"(zoom|meeting|meetup|面试|1:1|standup|stand-up|sync|腾讯会议|飞书|teams)",
    re.I,
)

_MUSIC_APPS = frozenset(
    {
        "music",
        "spotify",
        "网易云音乐",
        "qqmusic",
        "qq 音乐",
        "foobar2000",
        "vox",
        "audirvana",
    }
)

_MOVIE_APPS = frozenset(
    {
        "iina",
        "vlc",
        "quicktime player",
        "mpv",
        "infuse",
        "plex",
        "netflix",
    }
)

_BROWSER_APPS = frozenset(
    {
        "google chrome",
        "chromium",
        "safari",
        "firefox",
        "microsoft edge",
        "brave browser",
        "arc",
        "opera",
    }
)

# Map browser_tabs ids / short names → apps.focus process names.
_BROWSER_ID_ALIASES = {
    "chrome": "google chrome",
    "brave": "brave browser",
    "edge": "microsoft edge",
}


def is_browser_app(app: str) -> bool:
    """True if *app* is a known browser process / tab-sensor id."""
    name = (app or "").strip().lower()
    if not name:
        return False
    if name in _BROWSER_APPS:
        return True
    return _BROWSER_ID_ALIASES.get(name, "") in _BROWSER_APPS

_MUSIC_HOST_HINTS = (
    "music.163.com",
    "y.qq.com",
    "open.spotify.com",
    "music.apple.com",
    "liblib",
    "soundcloud.com",
    "music.youtube.com",
)
_VIDEO_HOST_HINTS = (
    "youtube.com",
    "youtu.be",
    "bilibili.com",
    "b23.tv",
    "vimeo.com",
    "iqiyi.com",
    "v.qq.com",
    "youku.com",
    "netflix.com",
    "tv.apple.com",
)
_SENSITIVE_HOST_HINTS = (
    "pornhub",
    "xvideos",
    "xhamster",
    "missav",
    "jav",
    "avgle",
    "spankbang",
)


def classify_focus(
    *,
    app: str = "",
    bundle_id: str = "",
    window_title: str = "",
    media_title: str = "",
    media_app: str = "",
    url_host: str = "",
) -> str:
    """Return scene: call|game|coding|movie|music|video|browser|writing|other."""
    app_l = (app or "").strip().lower()
    bundle_l = (bundle_id or "").strip().lower()
    title = window_title or ""
    host = (url_host or "").strip().lower()

    if media_title or (media_app and media_app.lower() in _MUSIC_APPS):
        return "music"
    if app_l in _CALL_APPS or _CALL_TITLE_RE.search(title):
        return "call"
    if app_l in _CODING_APPS or any(bundle_l.startswith(p) for p in _CODING_BUNDLES):
        return "coding"
    if app_l in _MOVIE_APPS:
        return "movie"
    if app_l in _MUSIC_APPS:
        return "music"
    if host:
        return classify_host(host, title=title)
    if app_l in _BROWSER_APPS:
        # Browser without host: try title heuristics
        if _looks_music_title(title):
            return "music"
        if _looks_video_title(title):
            return "video"
        return "browser"
    if app_l in {"notes", "备忘录", "textedit", "pages", "word", "microsoft word", "notion"}:
        return "writing"
    return "other"


def classify_host(host: str, *, title: str = "") -> str:
    h = (host or "").lower().removeprefix("www.")
    if any(x in h for x in _SENSITIVE_HOST_HINTS):
        return "sensitive_video"
    if any(x in h for x in _MUSIC_HOST_HINTS):
        return "music"
    if any(x in h for x in _VIDEO_HOST_HINTS):
        # Netflix etc. often movies; keep video unless title suggests film length
        if re.search(r"(电影|film|movie|剧场版)", title or "", re.I):
            return "movie"
        return "video"
    return "browser"


def classify_browser_event_hosts(hosts: list[str]) -> str:
    """Pick dominant scene from a list of hosts."""
    if not hosts:
        return "browser"
    scores: dict[str, int] = {}
    for h in hosts:
        scene = classify_host(h)
        scores[scene] = scores.get(scene, 0) + 1
    return max(scores.items(), key=lambda kv: kv[1])[0]


def host_from_url(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _looks_music_title(title: str) -> bool:
    return bool(re.search(r"(♪|spotify|网易云|qq音乐|playlist|歌单|正在播放)", title or "", re.I))


def _looks_video_title(title: str) -> bool:
    return bool(re.search(r"(youtube|bilibili|哔哩|watch\b|视频)", title or "", re.I))
