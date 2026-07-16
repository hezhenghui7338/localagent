"""STM benchmark thresholds and aggregation."""

from __future__ import annotations

from typing import Any

THRESHOLDS: dict[str, float] = {
    "routing_accuracy": 0.95,
    "session_hit": 0.90,
    "in_session_coverage": 0.95,
    "priority_win_rate": 0.90,
    "hot_profile_hit": 0.90,
}


def _rate(hits: int, n: int) -> float:
    if n <= 0:
        return 0.0
    return round(hits / n, 4)


def summarize_stm(payload: dict[str, Any]) -> dict[str, Any]:
    """Aggregate scenario rows into rates + pass/fail vs thresholds."""
    routing = payload.get("routing") or []
    in_session = payload.get("in_session") or []
    same_day = payload.get("same_day") or []
    priority = payload.get("priority") or []
    hot = payload.get("hot_profile") or []

    routing_hits = sum(1 for r in routing if r.get("ok"))
    in_cov = sum(1 for r in in_session if r.get("context_coverage"))
    in_ans = sum(1 for r in in_session if r.get("answer_hit"))
    session_hits = sum(1 for r in same_day if r.get("session_hit"))
    priority_wins = sum(1 for r in priority if r.get("priority_win"))
    hot_hits = sum(1 for r in hot if r.get("profile_hit"))

    metrics = {
        "routing_accuracy": _rate(routing_hits, len(routing)),
        "in_session_coverage": _rate(in_cov, len(in_session)),
        "in_session_answer_hit": _rate(in_ans, len(in_session)),
        "session_hit": _rate(session_hits, len(same_day)),
        "priority_win_rate": _rate(priority_wins, len(priority)),
        "hot_profile_hit": _rate(hot_hits, len(hot)),
        "n": {
            "routing": len(routing),
            "in_session": len(in_session),
            "same_day": len(same_day),
            "priority": len(priority),
            "hot_profile": len(hot),
        },
    }
    gates = {
        key: metrics[key] >= THRESHOLDS[key]
        for key in (
            "routing_accuracy",
            "session_hit",
            "in_session_coverage",
            "priority_win_rate",
        )
        if metrics["n"].get(
            {
                "routing_accuracy": "routing",
                "session_hit": "same_day",
                "in_session_coverage": "in_session",
                "priority_win_rate": "priority",
            }[key],
            0,
        )
        > 0
    }
    if metrics["n"]["hot_profile"] > 0:
        gates["hot_profile_hit"] = metrics["hot_profile_hit"] >= THRESHOLDS["hot_profile_hit"]
    metrics["gates"] = gates
    metrics["passed"] = all(gates.values()) if gates else False
    return metrics
