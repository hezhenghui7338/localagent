"""Aware episode prefetch for local activity questions."""

from __future__ import annotations

from localagent.context.router import PrefetchRoute, prefetch_header


def prefetch_aware_context(
    user_message: str,
    *,
    route: PrefetchRoute | None = None,
) -> str:
    """Inject recent Aware episodes when the user asks about local activity."""
    try:
        from localagent.aware.episode import retrieve_aware_context
    except Exception:
        return ""
    try:
        card = retrieve_aware_context(user_message, limit=10)
    except Exception:
        return ""
    if not (card or "").strip():
        return ""
    cap = 1600 if "日摘要" in card else 1200
    clipped = card if len(card) <= cap else card[:cap] + "\n…"
    return (
        prefetch_header(
            route,
            "aware",
            strong="[本机感知上下文（已预加载；敏感类仅聚合时长/时段；用户追问本人行为时据证据回答；无证据勿编造）]",
            soft="[本机感知上下文（已预加载，可优先据此回答；不足时可再检索；敏感类仅聚合时长/时段；无证据勿编造）]",
        )
        + "\n"
        + clipped
    )
