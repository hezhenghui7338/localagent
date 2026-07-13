"""Claude Code–style welcome banner for chat startup."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from localagent import __version__, config

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
    cwd_display: str
    session_id: str
    memory_count: int
    kb_count: int
    git_line: str
    tagline: str = "Your AI. Your Data. Your Mac."


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


def _kb_file_count() -> int:
    kb = config.KB_DIR
    if not kb.is_dir():
        return 0
    try:
        return sum(1 for p in kb.iterdir() if p.is_file() or p.is_symlink())
    except OSError:
        return 0


def _memory_count() -> int:
    try:
        from localagent.memory.store import get_memory_store

        return get_memory_store().count()
    except Exception:
        return 0


def _git_line(workspace: Path) -> str:
    try:
        from localagent.workspace.context import git_summary

        summary = git_summary(workspace)
    except Exception:
        return "Git: —"
    if not summary.is_repo:
        return "非 Git 仓库"
    if summary.error:
        return f"Git: {summary.error}"
    state = "干净" if summary.clean else "有变更"
    return f"{summary.branch} · {state}"


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
        cwd_display=_home_display(workspace),
        session_id=session_id,
        memory_count=_memory_count(),
        kb_count=_kb_file_count(),
        git_line=_git_line(workspace),
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

    tips = [
        _c("入门提示", _BOLD, _CYAN, enabled=use_color),
        "直接输入问题开始对话",
        ":provider 切换模型路径",
        ":deepsearch <主题> 研究",
        ":q / Ctrl+C×2 退出",
        _c("───────────────", _DIM, enabled=use_color),
        _c("项目状态", _BOLD, _CYAN, enabled=use_color),
        f"记忆 {info.memory_count} · kb {info.kb_count}",
        _truncate(info.git_line, right_w - 2),
    ]
    if info.session_id:
        tips.append(_truncate(f"session {info.session_id}", right_w - 2))

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
        _center(_c(_truncate(info.cwd_display, inner), _DIM, enabled=use_color)),
    ]

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
