"""Unified turn-level intent classification for agent routing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from localagent.agent.planner.complexity import (
    has_action_intent,
    should_use_milestone_mode,
)
from localagent.agent.prefetch_route import route_prefetch_modules
from localagent.persist.session_work import is_continue_query, resume_action_plan

TurnIntentKind = Literal[
    "remember",
    "continue",
    "action_milestone",
    "action_simple",
    "qa",
]

_EXPLICIT_REMEMBER = re.compile(
    r"^(?:请)?(?:帮我)?(?:记录一下|记住一下|记住|记下|记一下)[:：\s]*(.+)$"
    r"|^(?:please\s+)?(?:remember|note|record)(?:\s+that)?[:：\s]+(.+)$",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class TurnIntent:
    """Execution-path intent for one ``run_agent_turn`` invocation."""

    kind: TurnIntentKind
    resume_plan: Any | None = None
    remember_content: str = ""

    @property
    def use_milestone_planner(self) -> bool:
        return self.kind in ("continue", "action_milestone")


def explicit_remember_content(user_message: str) -> str | None:
    """Extract content from an explicit remember request, or None."""
    match = _EXPLICIT_REMEMBER.match((user_message or "").strip())
    if not match:
        return None
    content = (match.group(1) or match.group(2) or "").strip()
    return content or None


def classify_turn_intent(
    user_message: str,
    session_id: str | None = None,
) -> TurnIntent:
    """Classify how ``run_agent_turn`` should route this user message."""
    text = (user_message or "").strip()

    remember = explicit_remember_content(text)
    if remember:
        return TurnIntent(kind="remember", remember_content=remember)

    resume_plan = resume_action_plan(session_id, text)
    if resume_plan is not None:
        return TurnIntent(kind="continue", resume_plan=resume_plan)

    if should_use_milestone_mode(text):
        return TurnIntent(kind="action_milestone")

    if has_action_intent(text):
        return TurnIntent(kind="action_simple")

    return TurnIntent(kind="qa")


def prefetch_route_for_turn(user_message: str):
    """JIT prefetch route (memory / web / archive …) for context assembly."""
    return route_prefetch_modules(user_message)


def is_continue_turn(user_message: str) -> bool:
    """True when the user likely wants to resume an in-progress task."""
    return is_continue_query(user_message)
