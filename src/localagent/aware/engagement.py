"""Engagement tiers for aware focus / browser dwell sessions."""

from __future__ import annotations

from typing import Any

from localagent import config

ENGAGEMENT_GLANCE = "glance"
ENGAGEMENT_DWELL = "dwell"
ENGAGEMENT_ENGAGE = "engage"

ENGAGEMENT_RANK = {
    ENGAGEMENT_GLANCE: 0,
    ENGAGEMENT_DWELL: 1,
    ENGAGEMENT_ENGAGE: 2,
}

_DEFAULT_IDLE_ACTIVE_SEC = 120.0
_DEFAULT_VISIT_ENGAGE = 3


def tick_interval_minutes() -> float:
    return float(getattr(config, "AWARE_TICK_INTERVAL_MINUTES", 15) or 15)


def tick_interval_sec() -> float:
    return max(60.0, tick_interval_minutes() * 60.0)


def idle_active_threshold_sec() -> float:
    return float(
        getattr(config, "AWARE_ENGAGE_IDLE_SEC", _DEFAULT_IDLE_ACTIVE_SEC)
        or _DEFAULT_IDLE_ACTIVE_SEC
    )


def visit_engage_threshold() -> int:
    return int(
        getattr(config, "AWARE_ENGAGE_VISIT_COUNT", _DEFAULT_VISIT_ENGAGE)
        or _DEFAULT_VISIT_ENGAGE
    )


def classify_engagement(
    *,
    ticks_seen: int,
    dwell_sec: float = 0.0,
    idle_seconds: float | None = None,
    has_interaction: bool = False,
    visit_count: int = 0,
    interval_sec: float | None = None,
) -> str:
    """Return glance | dwell | engage from session continuity + activity proxies."""
    quantum = interval_sec if interval_sec is not None else tick_interval_sec()
    ticks = max(0, int(ticks_seen))
    dwell = max(0.0, float(dwell_sec or 0.0))
    if ticks <= 1 or dwell < quantum:
        return ENGAGEMENT_GLANCE

    idle_thr = idle_active_threshold_sec()
    if has_interaction:
        return ENGAGEMENT_ENGAGE
    if idle_seconds is not None and float(idle_seconds) < idle_thr:
        return ENGAGEMENT_ENGAGE
    if int(visit_count or 0) >= visit_engage_threshold():
        return ENGAGEMENT_ENGAGE
    return ENGAGEMENT_DWELL


def max_engagement(*values: str) -> str:
    best = ENGAGEMENT_GLANCE
    best_rank = -1
    for v in values:
        rank = ENGAGEMENT_RANK.get(str(v or ""), -1)
        if rank > best_rank:
            best = str(v)
            best_rank = rank
    return best


def update_idle_stats(session: dict[str, Any], idle: float | None) -> dict[str, Any]:
    out = dict(session)
    if idle is None:
        return out
    idle_f = float(idle)
    out["last_idle"] = idle_f
    prev_min = out.get("idle_min")
    prev_max = out.get("idle_max")
    out["idle_min"] = idle_f if prev_min is None else min(float(prev_min), idle_f)
    out["idle_max"] = idle_f if prev_max is None else max(float(prev_max), idle_f)
    return out


_SOURCE_WEIGHT = {
    "apps": 100.0,
    "terminal": 80.0,
    "git": 70.0,
    "fs": 50.0,
    "browser": 40.0,
}


def attention_score(
    *,
    source: str = "",
    scene: str = "",
    title: str = "",
    duration_min: float = 0.0,
    signals: dict[str, Any] | None = None,
) -> float:
    """Higher = more of the user's attention. Used to rank overview episodes/narrative."""
    sig = dict(signals or {})
    eng = str(sig.get("engagement") or "")
    eng_rank = float(ENGAGEMENT_RANK.get(eng, 0))
    dur = max(0.0, float(duration_min or 0.0))
    title_s = str(title or "")
    src = str(source or "")
    sc = str(scene or "")

    # Background selected / legacy mislabeled browser dwell → near zero.
    if src == "browser":
        if title_s.startswith("前台页:") or title_s.startswith("选中标签:"):
            return 0.01 * max(dur, 0.1)
        if sig.get("viewing") is False:
            return 0.01 * max(dur, 0.1)

    base = _SOURCE_WEIGHT.get(src, 30.0)
    if sc == "coding":
        base += 25.0
    elif sc in {"video", "music", "movie"}:
        base += 8.0
    elif sc == "sensitive_video":
        # Duration-only signal; do not elevate narrative.
        base = min(base, 15.0)
        eng_rank = min(eng_rank, float(ENGAGEMENT_RANK[ENGAGEMENT_GLANCE]))

    return base + eng_rank * 50.0 + min(dur, 120.0) * 0.5


def episode_attention_score(ep: Any) -> float:
    """Duck-typed wrapper for AwareEpisode (or similar)."""
    return attention_score(
        source=str(getattr(ep, "source", "") or ""),
        scene=str(getattr(ep, "scene", "") or ""),
        title=str(getattr(ep, "title", "") or ""),
        duration_min=float(getattr(ep, "duration_min", 0) or 0),
        signals=dict(getattr(ep, "signals", None) or {}),
    )
