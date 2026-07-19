"""Aware event log and sensor cursors."""

from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from localagent import config
from localagent.aware.types import AwareEvent


def _cursors_path() -> Path:
    return Path(config.AWARE_CURSORS_FILE)


def _events_path() -> Path:
    return Path(config.AWARE_EVENTS_FILE)


def load_cursors() -> dict[str, Any]:
    path = _cursors_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def save_cursors(cursors: dict[str, Any]) -> None:
    config.ensure_data_dirs()
    path = _cursors_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        suffix=".tmp",
    ) as tmp:
        tmp.write(json.dumps(cursors, ensure_ascii=False, indent=2))
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _maybe_rotate_events(path: Path) -> None:
    max_bytes = int(getattr(config, "AWARE_EVENTS_MAX_BYTES", 5 * 1024 * 1024) or 5 * 1024 * 1024)
    try:
        if not path.exists() or path.stat().st_size < max_bytes:
            return
        bak = path.with_name(path.name + ".1")
        if bak.exists():
            bak.unlink()
        path.replace(bak)
    except OSError:
        return


def append_events(events: list[AwareEvent]) -> int:
    if not events:
        return 0
    config.ensure_data_dirs()
    path = _events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    _maybe_rotate_events(path)
    with path.open("a", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    return len(events)


def load_events(
    *,
    source: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
) -> list[AwareEvent]:
    path = _events_path()
    if not path.exists():
        return []
    rows: list[AwareEvent] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        if source and raw.get("source") != source:
            continue
        if since:
            ts = str(raw.get("ts") or "")
            try:
                event_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=timezone.utc)
            if event_dt < since:
                continue
        rows.append(AwareEvent.from_dict(raw))
        if len(rows) >= limit:
            break
    rows.reverse()
    return rows


def events_count_today() -> int:
    today = date.today().isoformat()
    path = _events_path()
    if not path.exists():
        return 0
    count = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = str(raw.get("ts") or "")
            if ts.startswith(today):
                count += 1
                continue
            # UTC dates may differ; also accept date part after parse
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.astimezone().date().isoformat() == today:
                    count += 1
            except ValueError:
                continue
    except OSError:
        return 0
    return count
