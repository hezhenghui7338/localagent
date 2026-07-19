"""Daily input-activity aggregates from HID idle + foreground app (no key content)."""

from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from localagent import config
from localagent.aware.engagement import idle_active_threshold_sec, tick_interval_minutes


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


def load_day(day: date | None = None) -> dict[str, Any]:
    key = (day or date.today()).isoformat()
    raw = load_all().get(key)
    if not isinstance(raw, dict):
        return {
            "active_minutes": 0.0,
            "by_app": {},
            "ticks_active": 0,
            "ticks_total": 0,
        }
    by_app = raw.get("by_app") if isinstance(raw.get("by_app"), dict) else {}
    return {
        "active_minutes": float(raw.get("active_minutes") or 0.0),
        "by_app": {str(k): float(v or 0.0) for k, v in by_app.items()},
        "ticks_active": int(raw.get("ticks_active") or 0),
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


def record_input_activity(
    *,
    app: str,
    idle_seconds: float | None,
    error: str = "",
    minutes: float | None = None,
    day: date | None = None,
) -> dict[str, Any]:
    """Accumulate one tick toward today's input-active minutes. Returns day bucket."""
    day_key = (day or date.today()).isoformat()
    all_data = _prune(load_all())
    prev = all_data.get(day_key) if isinstance(all_data.get(day_key), dict) else {}
    by_app_prev = prev.get("by_app") if isinstance(prev.get("by_app"), dict) else {}
    bucket: dict[str, Any] = {
        "active_minutes": float(prev.get("active_minutes") or 0.0),
        "by_app": {str(k): float(v or 0.0) for k, v in by_app_prev.items()},
        "ticks_active": int(prev.get("ticks_active") or 0),
        "ticks_total": int(prev.get("ticks_total") or 0),
    }

    bucket["ticks_total"] = int(bucket["ticks_total"]) + 1
    active = is_input_active(idle_seconds=idle_seconds, app=app, error=error)
    if active:
        add = max(0.0, float(minutes if minutes is not None else tick_interval_minutes()))
        label = (app or "").strip() or "(unknown)"
        bucket["active_minutes"] = float(bucket["active_minutes"]) + add
        by_app = dict(bucket["by_app"])
        by_app[label] = float(by_app.get(label) or 0.0) + add
        bucket["by_app"] = by_app
        bucket["ticks_active"] = int(bucket["ticks_active"]) + 1
        bucket["last_active_at"] = datetime.now().astimezone().isoformat(timespec="seconds")

    all_data[day_key] = bucket
    save_all(all_data)
    return bucket


def format_input_activity_line(day: date | None = None, *, top_n: int = 4) -> str | None:
    """Human line for digest/summary, or None when there is no sample yet."""
    bucket = load_day(day)
    if int(bucket.get("ticks_total") or 0) <= 0:
        return None
    minutes = float(bucket.get("active_minutes") or 0.0)
    by_app = dict(bucket.get("by_app") or {})
    ranked = sorted(by_app.items(), key=lambda kv: (-kv[1], kv[0]))[: max(1, top_n)]
    if minutes <= 0:
        return "今日输入活跃: 尚无（已采样，空闲较高）"
    bits = [f"{name} {val:.0f}" for name, val in ranked if val > 0]
    head = f"今日输入活跃: 约 {minutes:.0f} 分钟"
    if bits:
        return f"{head}（{' · '.join(bits)}）"
    return head
