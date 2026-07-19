"""Daily rollups: coarse historical facts (no URLs / titles / commands)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from localagent import config
from localagent.aware.timewin import period_key, to_local
from localagent.aware.types import utc_now


@dataclass
class DailyRollup:
    local_day: str
    tz_offset_min: int = 0
    as_of: str = ""
    by_period: dict[str, dict[str, float]] = field(default_factory=dict)
    by_scene: dict[str, float] = field(default_factory=dict)
    top_entities: list[str] = field(default_factory=list)
    active_minutes: float = 0.0
    episode_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DailyRollup:
        return cls(
            local_day=str(raw.get("local_day") or ""),
            tz_offset_min=int(raw.get("tz_offset_min") or 0),
            as_of=str(raw.get("as_of") or ""),
            by_period={
                str(k): {str(sk): float(sv) for sk, sv in dict(v or {}).items()}
                for k, v in dict(raw.get("by_period") or {}).items()
            },
            by_scene={str(k): float(v) for k, v in dict(raw.get("by_scene") or {}).items()},
            top_entities=[str(x) for x in list(raw.get("top_entities") or [])],
            active_minutes=float(raw.get("active_minutes") or 0),
            episode_count=int(raw.get("episode_count") or 0),
        )


def _rollups_path() -> Path:
    return Path(getattr(config, "AWARE_ROLLUPS_FILE", config.AWARE_DIR / "rollups.jsonl"))


def _load_all() -> list[DailyRollup]:
    path = _rollups_path()
    if not path.exists():
        return []
    rows: list[DailyRollup] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict) and raw.get("local_day"):
                rows.append(DailyRollup.from_dict(raw))
    except OSError:
        return []
    return rows


def load_rollups(
    *,
    since_day: str | None = None,
    until_day: str | None = None,
    limit: int = 90,
) -> list[DailyRollup]:
    rows = _load_all()
    if since_day:
        rows = [r for r in rows if r.local_day >= since_day]
    if until_day:
        rows = [r for r in rows if r.local_day <= until_day]
    rows.sort(key=lambda r: r.local_day)
    if limit > 0:
        rows = rows[-limit:]
    return rows


def _rewrite(rows: list[DailyRollup]) -> None:
    keep = int(getattr(config, "AWARE_ROLLUP_KEEP_DAYS", 180) or 180)
    if keep > 0 and len(rows) > keep:
        rows = sorted(rows, key=lambda r: r.local_day)[-keep:]
    path = _rollups_path()
    config.ensure_data_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in sorted(rows, key=lambda x: x.local_day):
            fh.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")


def upsert_rollup(rollup: DailyRollup) -> None:
    rows = _load_all()
    by_day = {r.local_day: r for r in rows}
    by_day[rollup.local_day] = rollup
    _rewrite(list(by_day.values()))


def build_rollup_for_local_day(local_day: str) -> DailyRollup | None:
    """Aggregate episodes whose local_day (or start local date) matches."""
    from localagent.aware.episode import load_episodes

    # Load a wide window then filter by local day.
    since = datetime.now(timezone.utc) - timedelta(days=400)
    episodes = load_episodes(since=since, limit=0)
    matched = []
    for ep in episodes:
        day = str(ep.signals.get("local_day") or "").strip()
        if not day:
            local = to_local(ep.start or ep.end)
            day = local.date().isoformat() if local else ""
        if day == local_day:
            matched.append(ep)
    if not matched:
        return None

    by_period: dict[str, dict[str, float]] = {}
    by_scene: Counter[str] = Counter()
    entities: Counter[str] = Counter()
    active = 0.0
    tz_off = 0
    for ep in matched:
        dur = float(ep.duration_min or 0)
        active += dur
        scene = ep.scene or "other"
        by_scene[scene] += dur
        pk = str(ep.signals.get("period") or period_key(ep.start) or "other")
        bucket = by_period.setdefault(pk, {})
        bucket[scene] = float(bucket.get(scene) or 0) + dur
        for ent in ep.entities[:5]:
            # Skip URL-like / sensitive long strings
            text = str(ent).strip()
            if not text or "://" in text or len(text) > 80:
                continue
            entities[text] += 1
        if ep.signals.get("tz_offset_min") is not None:
            try:
                tz_off = int(ep.signals["tz_offset_min"])
            except (TypeError, ValueError):
                pass
        elif tz_off == 0:
            local = to_local(ep.start)
            if local and local.utcoffset() is not None:
                tz_off = int(local.utcoffset().total_seconds() // 60)

    return DailyRollup(
        local_day=local_day,
        tz_offset_min=tz_off,
        as_of=utc_now(),
        by_period=by_period,
        by_scene=dict(by_scene),
        top_entities=[e for e, _ in entities.most_common(8)],
        active_minutes=round(active, 1),
        episode_count=len(matched),
    )


def refresh_recent_rollups(*, days: int = 2) -> list[str]:
    """Rebuild rollups for today and the previous ``days-1`` local days."""
    today = datetime.now().astimezone().date()
    written: list[str] = []
    for i in range(max(1, days)):
        day = (today - timedelta(days=i)).isoformat()
        rollup = build_rollup_for_local_day(day)
        if rollup is None:
            continue
        upsert_rollup(rollup)
        written.append(day)
    return written


def format_rollup_context_lines(
    *,
    since: datetime | None = None,
    limit: int = 14,
) -> list[str]:
    """Markdown lines for historical injection (aggregate only)."""
    since_day = None
    if since is not None:
        local = since.astimezone() if since.tzinfo else since.replace(tzinfo=timezone.utc)
        since_day = local.astimezone().date().isoformat()
    rows = load_rollups(since_day=since_day, limit=limit)
    if not rows:
        return []
    lines = ["### 日摘要（历史聚合 · 无 URL/片名）"]
    for r in rows:
        scene_bits = [
            f"{k}:{v:.0f}m"
            for k, v in sorted(r.by_scene.items(), key=lambda kv: -kv[1])[:4]
            if v >= 1
        ]
        period_bits = []
        for pk, scenes in sorted(r.by_period.items()):
            total = sum(scenes.values())
            if total >= 1:
                period_bits.append(f"{pk}:{total:.0f}m")
        bit = f"- {r.local_day}: 活跃~{r.active_minutes:.0f}min · {r.episode_count}段"
        if scene_bits:
            bit += " · " + ", ".join(scene_bits)
        if period_bits:
            bit += " · 时段 " + ", ".join(period_bits[:4])
        if r.top_entities:
            bit += " · " + ", ".join(r.top_entities[:3])
        lines.append(bit)
    return lines
