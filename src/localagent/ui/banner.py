"""Claude Code–style welcome banner for chat startup."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from localagent import __version__

# Braille-block "LA" mark (Claude Code–style glyph art)
_LA_GLYPH = (
    r"  ▗▖  ▗▄▖  ",
    r" ▐▌  ▐▌ ▐▌ ",
    r" ▐▌  ▐▛▀▜▌ ",
    r" ▐▙▖ ▐▌ ▐▌ ",
)

_CSI = "\x1b["
_RESET = f"{_CSI}0m"
_BOLD = f"{_CSI}1m"
_DIM = f"{_CSI}2m"
_CYAN = f"{_CSI}36m"
_BRIGHT_CYAN = f"{_CSI}96m"
_WHITE = f"{_CSI}97m"


@dataclass(frozen=True)
class WelcomeInfo:
    version: str
    provider_line: str
    web_search_line: str
    cwd_display: str
    session_id: str
    layer_lines: tuple[str, ...] = ()
    tagline: str = "Local First. Memory Forever. Actions Automated."


def format_web_search_hint() -> str:
    """Human-readable web backend for the welcome banner (resolved from config)."""
    from localagent.i18n import t
    from localagent.tools.web_search import resolve_web_search_provider

    provider = resolve_web_search_provider()
    if provider == "ddgs":
        label = t("web_search.ddgs")
    elif provider == "tavily":
        label = "Tavily"
    elif provider == "searxng":
        label = "SearXNG"
    else:
        label = provider
    return t("banner.web_search", label=label)


def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def _c(text: str, *codes: str, enabled: bool) -> str:
    if not enabled or not codes:
        return text
    return f"{''.join(codes)}{text}{_RESET}"


def _display_width(text: str) -> int:
    """Approximate terminal columns (CJK = 2, ANSI ignored)."""
    width = 0
    i = 0
    while i < len(text):
        if text[i] == "\x1b" and i + 1 < len(text) and text[i + 1] == "[":
            i += 2
            while i < len(text) and not text[i].isalpha():
                i += 1
            i += 1
            continue
        ch = text[i]
        o = ord(ch)
        if (
            0x1100 <= o <= 0x115F
            or 0x2E80 <= o <= 0xA4CF
            or 0xAC00 <= o <= 0xD7A3
            or 0xF900 <= o <= 0xFAFF
            or 0xFE10 <= o <= 0xFE6F
            or 0xFF00 <= o <= 0xFF60
            or 0xFFE0 <= o <= 0xFFE6
            or 0x1F300 <= o <= 0x1FAFF
        ):
            width += 2
        else:
            width += 1
        i += 1
    return width


def _pad(text: str, width: int) -> str:
    pad = width - _display_width(text)
    if pad <= 0:
        return text
    return text + (" " * pad)


def _truncate(text: str, width: int) -> str:
    """Truncate plain (or ANSI) text to a display width, preserving escape codes."""
    if _display_width(text) <= width:
        return text
    if width <= 1:
        return "…"[:width]
    out: list[str] = []
    visible = 0
    i = 0
    limit = width - 1
    while i < len(text):
        if text[i] == "\x1b" and i + 1 < len(text) and text[i + 1] == "[":
            j = i + 2
            while j < len(text) and not text[j].isalpha():
                j += 1
            j = min(j + 1, len(text))
            out.append(text[i:j])
            i = j
            continue
        ch = text[i]
        ch_w = 2 if _display_width(ch) > 1 else 1
        if visible + ch_w > limit:
            out.append("…")
            break
        out.append(ch)
        visible += ch_w
        i += 1
    return "".join(out)


def _home_display(path: Path) -> str:
    try:
        return "~/" + path.resolve().relative_to(Path.home().resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def _layer_lines() -> tuple[str, ...]:
    try:
        from localagent.status.layers import format_data_layer_banner_lines

        return tuple(format_data_layer_banner_lines())
    except Exception:
        return ("la status 查看数据层",)


def collect_welcome_info(
    *,
    provider: str = "auto",
    session_id: str = "",
    cwd: Path | None = None,
) -> WelcomeInfo:
    from localagent.models.router import get_model_router
    from localagent.workspace.context import resolve_workspace

    workspace = cwd or resolve_workspace()
    router = get_model_router()
    provider_hint = router.format_provider_hint(provider)
    model_name = router.format_model_hint(provider)
    if model_name:
        provider_line = f"{model_name} · {provider_hint}"
    else:
        provider_line = provider_hint

    return WelcomeInfo(
        version=__version__,
        provider_line=provider_line,
        web_search_line=format_web_search_hint(),
        cwd_display=_home_display(workspace),
        session_id=session_id,
        layer_lines=_layer_lines(),
    )


def render_welcome(info: WelcomeInfo, *, width: int | None = None, color: bool | None = None) -> str:
    """Render a two-column Claude Code–style startup panel."""
    use_color = _use_color() if color is None else color
    term_width = width or shutil.get_terminal_size((88, 24)).columns
    term_width = max(72, min(term_width, 100))

    right_w = 34
    # outer: │ left │ right │  → 3 borders + 2 padding gaps accounted in cells
    left_w = term_width - right_w - 3
    if left_w < 28:
        right_w = max(24, term_width // 3)
        left_w = term_width - right_w - 3

    title = f"LocalAgent v{info.version}"
    rule_len = max(1, term_width - _display_width(title) - 2)
    header = (
        f"{_c(title, _BOLD, _WHITE, enabled=use_color)}"
        f"{_c('─' * rule_len, _DIM, enabled=use_color)}╮"
    )

    from localagent.i18n import t

    tips = [
        _c(t("banner.tips_title"), _BOLD, _CYAN, enabled=use_color),
        t("banner.tip_chat"),
        t("banner.tip_tab"),
        t("banner.tip_help"),
        t("banner.tip_status"),
        t("banner.tip_provider"),
        t("banner.tip_model"),
        t("banner.tip_websearch"),
        t("banner.tip_deepsearch"),
        t("banner.tip_quit"),
        _c("───────────────", _DIM, enabled=use_color),
        _c(t("banner.daily_actions"), _BOLD, _CYAN, enabled=use_color),
    ]
    try:
        from localagent.status.daily import format_daily_actions_lines

        for line in format_daily_actions_lines():
            tips.append(_truncate(line, right_w - 2))
    except Exception:
        tips.append(t("banner.daily_fallback"))
    tips.extend(
        [
            _c("───────────────", _DIM, enabled=use_color),
            _c(t("banner.data_layers"), _BOLD, _CYAN, enabled=use_color),
        ]
    )
    layer_lines = info.layer_lines or (t("banner.layers_fallback"),)
    for line in layer_lines:
        tips.append(_truncate(line, right_w - 2))

    inner = left_w - 2

    def _center(text: str) -> str:
        pad = max(0, (inner - _display_width(text)) // 2)
        return (" " * pad) + text

    brand = (
        f"{_c('LOCAL', _BOLD, _WHITE, enabled=use_color)}"
        f"{_c('AGENT', _BOLD, _BRIGHT_CYAN, enabled=use_color)}"
    )
    left_rows: list[str] = [
        "",
        "",
        *(_center(_c(line, _BRIGHT_CYAN, enabled=use_color)) for line in _LA_GLYPH),
        "",
        _center(brand),
        _center(_c(info.tagline, _DIM, enabled=use_color)),
        "",
        _center(_c(_truncate(info.provider_line, inner), _CYAN, enabled=use_color)),
        _center(_c(_truncate(info.web_search_line, inner), _DIM, enabled=use_color)),
        _center(_c(_truncate(info.cwd_display, inner), _DIM, enabled=use_color)),
    ]
    if info.session_id:
        left_rows.append(
            _center(_c(_truncate(f"session {info.session_id}", inner), _DIM, enabled=use_color))
        )

    rows = max(len(left_rows), len(tips))
    while len(left_rows) < rows:
        left_rows.append("")
    while len(tips) < rows:
        tips.append("")

    lines = [header]
    for left, right in zip(left_rows, tips):
        left_cell = _pad(_truncate(left, left_w - 2), left_w - 2)
        right_cell = _pad(_truncate(right, right_w - 2), right_w - 2)
        border = _c("│", _DIM, enabled=use_color)
        lines.append(f"{border} {left_cell} {border} {right_cell} {border}")

    return "\n".join(lines)


def print_welcome(
    *,
    provider: str = "auto",
    session_id: str = "",
    cwd: Path | None = None,
) -> WelcomeInfo:
    info = collect_welcome_info(provider=provider, session_id=session_id, cwd=cwd)
    print(render_welcome(info))
    return info
