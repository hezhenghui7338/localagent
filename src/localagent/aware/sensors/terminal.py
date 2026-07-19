"""Shell / PowerShell history sensor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from localagent import config
from localagent.aware.platform_paths import discover_history_files
from localagent.aware.profile import SourceGrant
from localagent.aware.sensors.base import int_cursor, redact_secrets
from localagent.aware.types import AwareEvent

_MAX_LINES_PER_TICK = 50


def _history_max_bytes() -> int:
    return int(getattr(config, "AWARE_HISTORY_MAX_BYTES", 8 * 1024 * 1024) or 8 * 1024 * 1024)


def _read_history_bounded(path: Path, *, start_byte: int, max_bytes: int) -> tuple[bytes, int]:
    """Read at most max_bytes from start_byte. Returns (data, new_byte_offset)."""
    try:
        size = path.stat().st_size
    except OSError:
        return b"", start_byte
    start = min(max(0, start_byte), size)
    try:
        with path.open("rb") as fh:
            fh.seek(start)
            data = fh.read(min(max_bytes, max(0, size - start)))
    except OSError:
        return b"", start
    return data, start + len(data)


class TerminalSensor:
    name = "terminal"

    def __init__(self, grant: SourceGrant) -> None:
        self.grant = grant

    def _files(self) -> list[Path]:
        if self.grant.history_files:
            return [Path(p).expanduser() for p in self.grant.history_files if Path(p).expanduser().is_file()]
        return discover_history_files()

    def describe_access(self) -> list[str]:
        files = self._files()
        return [str(f) for f in files] or ["（未发现 shell history 文件）"]

    def collect(self, cursor: dict[str, Any]) -> tuple[list[AwareEvent], dict[str, Any]]:
        events: list[AwareEvent] = []
        offsets: dict[str, int] = dict(cursor.get("offsets") or {})
        byte_offsets: dict[str, int] = {
            str(k): int(v) for k, v in dict(cursor.get("byte_offsets") or {}).items()
        }
        new_offsets: dict[str, int] = dict(offsets)
        new_byte_offsets: dict[str, int] = dict(byte_offsets)
        max_b = _history_max_bytes()

        for path in self._files():
            if len(events) >= _MAX_LINES_PER_TICK:
                break
            key = str(path.resolve())
            try:
                size = path.stat().st_size
            except OSError:
                continue

            if size > max_b:
                # Byte-offset mode: never load the whole file.
                if key not in byte_offsets and key not in offsets:
                    new_byte_offsets[key] = size
                    continue
                start = byte_offsets.get(key, size)
                data, end = _read_history_bounded(path, start_byte=start, max_bytes=max_b)
                new_byte_offsets[key] = end
                # Drop a leading fragment only when we resumed mid-line.
                if start > 0 and data:
                    try:
                        with path.open("rb") as fh:
                            fh.seek(start - 1)
                            prev = fh.read(1)
                    except OSError:
                        prev = b"\n"
                    if prev != b"\n":
                        nl = data.find(b"\n")
                        if nl >= 0:
                            data = data[nl + 1 :]
                        else:
                            data = b""
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = data.decode("utf-8", errors="replace")
                new_lines = text.splitlines()
            else:
                try:
                    data = path.read_bytes()
                except OSError:
                    continue
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = data.decode("utf-8", errors="replace")
                lines = text.splitlines()
                # First sight: seed offset, do not replay the whole history.
                if key not in offsets and key not in byte_offsets:
                    new_offsets[key] = len(lines)
                    continue
                offset = int_cursor({"o": offsets.get(key, 0)}, "o", 0)
                if offset > len(lines):
                    offset = max(0, len(lines) - _MAX_LINES_PER_TICK)
                new_lines = lines[offset:]
                new_offsets[key] = len(lines)

            for raw_line in new_lines:
                if len(events) >= _MAX_LINES_PER_TICK:
                    break
                cmd = _normalize_history_line(raw_line)
                if not cmd:
                    continue
                safe = redact_secrets(cmd)
                events.append(
                    AwareEvent(
                        source="terminal",
                        kind="terminal.cmd",
                        title=safe[:120],
                        data={"command": safe, "history_file": key},
                    )
                )

        return events, {"offsets": new_offsets, "byte_offsets": new_byte_offsets}


def _normalize_history_line(line: str) -> str:
    text = line.strip()
    if not text:
        return ""
    # zsh EXTENDED_HISTORY
    if text.startswith(":") and ";" in text:
        text = text.split(";", 1)[1].strip()
    # fish yaml-ish
    if text.startswith("- cmd:"):
        text = text[len("- cmd:") :].strip().strip("'\"")
    return text.strip()
