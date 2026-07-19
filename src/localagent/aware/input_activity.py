"""Daily input-activity aggregates from HID idle + scene / cross-sensor corroboration."""

from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from localagent import config
from localagent.aware.engagement import idle_active_threshold_sec, tick_interval_minutes
from localagent.i18n import t

# Scenes that imply real keyboard/editing work (from classify_focus), not just HID motion.
INPUT_SCENES = frozenset({"coding", "writing", "terminal"})


def _path() -> Path:
    explicit = getattr(config, "AWARE_INPUT_ACTIVITY_FILE", None)
    if explicit:
        return Path(explicit)
    return Path(config.AWARE_DIR) / "input_activity.json"


def _keep_days() -> int:
    return max(1, int(getattr(config, "AWARE_INPUT_ACTIVITY_KEEP_DAYS", 30) or 30))


def load_all() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def save_all(data: dict[str, Any]) -> None:
    config.ensure_data_dirs()
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        suffix=".tmp",
    ) as tmp:
        tmp.write(json.dumps(data, ensure_ascii=False, indent=2))
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _prune(data: dict[str, Any], *, keep_days: int | None = None) -> dict[str, Any]:
    days = keep_days if keep_days is not None else _keep_days()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return {k: v for k, v in data.items() if isinstance(k, str) and k >= cutoff}


def _empty_day() -> dict[str, Any]:
    return {
        "active_minutes": 0.0,
        "presence_minutes": 0.0,
        "by_app": {},
        "presence_by_app": {},
        "ticks_active": 0,
        "ticks_presence": 0,
        "ticks_total": 0,
    }


def load_day(day: date | None = None) -> dict[str, Any]:
    key = (day or date.today()).isoformat()
    raw = load_all().get(key)
    if not isinstance(raw, dict):
        return _empty_day()
    by_app = raw.get("by_app") if isinstance(raw.get("by_app"), dict) else {}
    presence_by_app = (
        raw.get("presence_by_app") if isinstance(raw.get("presence_by_app"), dict) else {}
    )
    return {
        "active_minutes": float(raw.get("active_minutes") or 0.0),
        "presence_minutes": float(raw.get("presence_minutes") or 0.0),
        "by_app": {str(k): float(v or 0.0) for k, v in by_app.items()},
        "presence_by_app": {str(k): float(v or 0.0) for k, v in presence_by_app.items()},
        "ticks_active": int(raw.get("ticks_active") or 0),
        "ticks_presence": int(raw.get("ticks_presence") or 0),
        "ticks_total": int(raw.get("ticks_total") or 0),
    }


def is_input_active(
    *,
    idle_seconds: float | None,
    app: str,
    error: str = "",
) -> bool:
    """True when HID idle is below threshold and a foreground app is known."""
    if error or not (app or "").strip():
        return False
    if idle_seconds is None:
        return False
    return float(idle_seconds) < idle_active_threshold_sec()


def counts_as_input(
    *,
    scene: str = "",
    corroborated: bool = False,
) -> bool:
    """Input minutes require coding/writing/terminal scene or cross-sensor corroboration."""
    if corroborated:
        return True
    return str(scene or "").strip().lower() in INPUT_SCENES


def record_input_activity(
    *,
    app: str,
    idle_seconds: float | None,
    error: str = "",
    minutes: float | None = None,
    day: date | None = None,
    scene: str = "",
    corroborated: bool = False,
) -> dict[str, Any]:
    """Accumulate one tick toward today's input / presence minutes. Returns day bucket."""
    day_key = (day or date.today()).isoformat()
    all_data = _prune(load_all())
    prev = all_data.get(day_key) if isinstance(all_data.get(day_key), dict) else {}
    by_app_prev = prev.get("by_app") if isinstance(prev.get("by_app"), dict) else {}
    presence_prev = (
        prev.get("presence_by_app") if isinstance(prev.get("presence_by_app"), dict) else {}
    )
    bucket: dict[str, Any] = {
        "active_minutes": float(prev.get("active_minutes") or 0.0),
        "presence_minutes": float(prev.get("presence_minutes") or 0.0),
        "by_app": {str(k): float(v or 0.0) for k, v in by_app_prev.items()},
        "presence_by_app": {str(k): float(v or 0.0) for k, v in presence_prev.items()},
        "ticks_active": int(prev.get("ticks_active") or 0),
        "ticks_presence": int(prev.get("ticks_presence") or 0),
        "ticks_total": int(prev.get("ticks_total") or 0),
    }

    bucket["ticks_total"] = int(bucket["ticks_total"]) + 1
    hid_active = is_input_active(idle_seconds=idle_seconds, app=app, error=error)
    if hid_active:
        add = max(0.0, float(minutes if minutes is not None else tick_interval_minutes()))
        label = (app or "").strip() or "(unknown)"
        if counts_as_input(scene=scene, corroborated=corroborated):
            bucket["active_minutes"] = float(bucket["active_minutes"]) + add
            by_app = dict(bucket["by_app"])
            by_app[label] = float(by_app.get(label) or 0.0) + add
            bucket["by_app"] = by_app
            bucket["ticks_active"] = int(bucket["ticks_active"]) + 1
            bucket["last_active_at"] = datetime.now().astimezone().isoformat(
                timespec="seconds"
            )
        else:
            bucket["presence_minutes"] = float(bucket["presence_minutes"]) + add
            p_by = dict(bucket["presence_by_app"])
            p_by[label] = float(p_by.get(label) or 0.0) + add
            bucket["presence_by_app"] = p_by
            bucket["ticks_presence"] = int(bucket["ticks_presence"]) + 1
            bucket["last_presence_at"] = datetime.now().astimezone().isoformat(
                timespec="seconds"
            )

    all_data[day_key] = bucket
    save_all(all_data)
    return bucket


def aggregate_days(
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """Sum day buckets from start..end inclusive (local dates)."""
    end_d = end or date.today()
    start_d = start or end_d
    if start_d > end_d:
        start_d, end_d = end_d, start_d
    merged = _empty_day()
    all_data = load_all()
    cur = start_d
    while cur <= end_d:
        raw = all_data.get(cur.isoformat())
        cur += timedelta(days=1)
        if not isinstance(raw, dict):
            continue
        merged["active_minutes"] += float(raw.get("active_minutes") or 0.0)
        merged["presence_minutes"] += float(raw.get("presence_minutes") or 0.0)
        merged["ticks_active"] += int(raw.get("ticks_active") or 0)
        merged["ticks_presence"] += int(raw.get("ticks_presence") or 0)
        merged["ticks_total"] += int(raw.get("ticks_total") or 0)
        by_app = raw.get("by_app") if isinstance(raw.get("by_app"), dict) else {}
        for k, v in by_app.items():
            merged["by_app"][str(k)] = float(merged["by_app"].get(str(k)) or 0.0) + float(
                v or 0.0
            )
        p_by = (
            raw.get("presence_by_app")
            if isinstance(raw.get("presence_by_app"), dict)
            else {}
        )
        for k, v in p_by.items():
            merged["presence_by_app"][str(k)] = float(
                merged["presence_by_app"].get(str(k)) or 0.0
            ) + float(v or 0.0)
    return merged


def _resolve_since_start(since: datetime | date | str) -> tuple[date, str]:
    """Return (local start date, optional window label for i18n)."""
    from localagent.aware.timewin import label_since, parse_since, since_to_datetime, to_local

    if isinstance(since, datetime):
        local = to_local(since)
        return (local.date() if local else date.today()), ""
    if isinstance(since, date):
        return since, ""
    text = str(since).strip().lower()
    try:
        key = parse_since(text)
        local = to_local(since_to_datetime(key))
        return (local.date() if local else date.today()), label_since(key)
    except ValueError:
        return date.today(), ""


def format_input_activity_line(
    day: date | None = None,
    *,
    top_n: int = 4,
    since: datetime | date | str | None = None,
) -> str | None:
    """Human line for digest/summary, or None when there is no sample yet.

    When *since* is set, aggregate all local days from that instant through today.
    """
    if since is not None:
        start_d, window = _resolve_since_start(since)
        bucket = aggregate_days(start=start_d, end=date.today())
    else:
        bucket = load_day(day)
        window = ""

    if int(bucket.get("ticks_total") or 0) <= 0:
        return None
    minutes = float(bucket.get("active_minutes") or 0.0)
    by_app = dict(bucket.get("by_app") or {})
    ranked = sorted(by_app.items(), key=lambda kv: (-kv[1], kv[0]))[: max(1, top_n)]
    bits = [f"{name} {val:.0f}" for name, val in ranked if val > 0]

    if window:
        if minutes <= 0:
            return t("aware.input_idle_window", window=window)
        if bits:
            return t(
                "aware.input_active_apps_window",
                window=window,
                minutes=minutes,
                apps=" · ".join(bits),
            )
        return t("aware.input_active_window", window=window, minutes=minutes)

    if minutes <= 0:
        return t("aware.input_idle")
    if bits:
        return t(
            "aware.input_active_apps",
            minutes=minutes,
            apps=" · ".join(bits),
        )
    return t("aware.input_active", minutes=minutes)
