"""Application diagnostic logging (loguru) — separate from audit JSONL and CLI UX."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from loguru import logger

from localagent import config

_CONFIGURED = False

_LEVEL_NAMES = ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL")
_LEVEL_RANK = {name: i for i, name in enumerate(_LEVEL_NAMES)}

# Map stdlib logging levels into loguru.
_STD_TO_LOGURU = {
    logging.CRITICAL: "CRITICAL",
    logging.ERROR: "ERROR",
    logging.WARNING: "WARNING",
    logging.INFO: "INFO",
    logging.DEBUG: "DEBUG",
    logging.NOTSET: "DEBUG",
}


class InterceptHandler(logging.Handler):
    """Forward stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = _STD_TO_LOGURU.get(record.levelno, "INFO")
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def resolve_log_level(*, debug: bool = False) -> str:
    """Return effective log level (DEBUG wins over LA_LOG_LEVEL when debug=True)."""
    if debug:
        return "DEBUG"
    raw = (os.environ.get("LA_LOG_LEVEL") or "INFO").strip().upper()
    if raw in _LEVEL_RANK:
        return raw
    return "INFO"


def setup_logging(*, level: str | None = None, debug_stderr: bool | None = None) -> None:
    """Configure loguru file sink (+ stderr when DEBUG).

    Safe to call multiple times; reconfigures sinks each call (tests / --debug).
    """
    global _CONFIGURED
    resolved = (level or resolve_log_level()).upper()
    if resolved not in _LEVEL_RANK:
        resolved = "INFO"
    use_stderr = debug_stderr if debug_stderr is not None else (resolved == "DEBUG")

    config.ensure_data_dirs()
    log_path = config.APP_LOG_FILE
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(
        str(log_path),
        level=resolved,
        rotation="5 MB",
        retention=3,
        encoding="utf-8",
        enqueue=False,
        backtrace=False,
        diagnose=False,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | "
            "{name}:{function}:{line} | {message}"
        ),
    )
    if use_stderr:
        logger.add(
            sys.stderr,
            level=resolved,
            colorize=True,
            backtrace=False,
            diagnose=False,
            format=(
                "<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | "
                "<cyan>{name}</cyan> | {message}"
            ),
        )

    # Intercept stdlib logging used across the codebase.
    logging.root.handlers.clear()
    logging.root.setLevel(logging.DEBUG)
    logging.root.addHandler(InterceptHandler())
    for name in list(logging.root.manager.loggerDict):
        std_logger = logging.getLogger(name)
        std_logger.handlers.clear()
        std_logger.propagate = True

    _CONFIGURED = True
    logger.debug("logging configured level={} stderr={}", resolved, use_stderr)


def truncate_for_log(text: str, *, limit: int = 80) -> str:
    """Short one-line snippet for DEBUG causal-chain context (no full payloads)."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1]}…"


def _parse_line_level(line: str) -> str | None:
    """Extract level name from a loguru file line, if present."""
    # Format: time | LEVEL | name:function:line | message
    parts = line.split("|", 2)
    if len(parts) < 2:
        return None
    level = parts[1].strip().upper()
    return level if level in _LEVEL_RANK else None


def read_app_log(*, tail: int = 80, level_filter: str | None = None) -> str:
    """Return recent application log lines (optionally filtered by min level)."""
    path = config.APP_LOG_FILE
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8").splitlines()
    min_rank = None
    if level_filter:
        name = level_filter.strip().upper()
        min_rank = _LEVEL_RANK.get(name)
    if min_rank is not None:
        filtered: list[str] = []
        for line in lines:
            lvl = _parse_line_level(line)
            if lvl is None:
                continue
            if _LEVEL_RANK[lvl] >= min_rank:
                filtered.append(line)
        lines = filtered
    if tail <= 0 or tail >= len(lines):
        return "\n".join(lines)
    return "\n".join(lines[-tail:])


def app_log_path() -> Path:
    return config.APP_LOG_FILE
