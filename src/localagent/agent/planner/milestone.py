"""Milestone planning and verification."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from localagent import config
from localagent.agent.planner.state import ActionPlan, Milestone

logger = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_BLOCKED_RE = re.compile(r"rm\s+-rf\s+/|format\s+c:|del\s+/[sfq]", re.IGNORECASE)


def _parse_plan_payload(reply: str) -> dict[str, Any] | None:
    raw = (reply or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = _JSON_RE.search(raw)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _normalize_milestones(raw: Any, *, max_count: int) -> list[Milestone]:
    if not isinstance(raw, list):
        return []
    out: list[Milestone] = []
    for idx, item in enumerate(raw[:max_count]):
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or f"m{idx + 1}").strip() or f"m{idx + 1}"
        objective = str(item.get("objective") or "").strip()
        done_when = str(item.get("done_when") or "").strip()
        if not objective:
            continue
        out.append(Milestone(id=mid, objective=objective, done_when=done_when))
    return out


def plan_milestones(user_message: str) -> ActionPlan | None:
    """Ask the model for an ordered milestone plan; None on failure."""
    try:
        from localagent.models.router import ChatMessage, get_model_router
    except Exception:
        return None

    prompt = (
        "你是行动任务规划器。根据用户请求，拆成 2-4 个有序子目标（milestone）。\n"
        "只输出 JSON（不要 markdown）：\n"
        '{"mode":"milestone","goal":"单行摘要","milestones":[\n'
        '  {"id":"m1","objective":"子目标描述","done_when":"可观察完成条件"}\n'
        "]}\n"
        "规则：\n"
        "- objective 描述要做什么，不要写工具名\n"
        "- done_when 必须是可观察条件（如「已知路径」「文件已修改」「命令已执行」）\n"
        "- 2-4 个 milestone，按执行顺序\n"
        "- 简单单步任务也至少 1 个 milestone\n\n"
        f"用户请求：{user_message}\n"
    )
    try:
        reply = get_model_router().chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.0,
            usage_command="action_plan",
        )
    except Exception as exc:
        logger.debug("milestone plan failed: %s", exc)
        return None

    data = _parse_plan_payload(reply)
    if not data:
        return None
    goal = str(data.get("goal") or user_message).strip()
    milestones = _normalize_milestones(
        data.get("milestones"),
        max_count=config.PLANNER_MAX_MILESTONES,
    )
    if not milestones:
        return None
    return ActionPlan(goal=goal, milestones=milestones)


def verify_plan(plan: ActionPlan, user_message: str) -> tuple[bool, str]:
    """Validate plan structure; return (ok, reason)."""
    if _BLOCKED_RE.search(user_message):
        return False, "blocked_intent"
    if not plan.milestones:
        return False, "empty_milestones"
    if len(plan.milestones) > config.PLANNER_MAX_MILESTONES:
        return False, "too_many_milestones"
    for m in plan.milestones:
        if not m.objective or len(m.objective) > 120:
            return False, "invalid_objective"
    return True, "ok"


def parse_revised_milestones(reply: str, *, start_id: int = 1) -> list[Milestone]:
    """Parse replan output — remaining milestones only."""
    data = _parse_plan_payload(reply)
    if not data:
        return []
    raw = data.get("milestones") or data.get("remaining") or []
    milestones = _normalize_milestones(raw, max_count=config.PLANNER_MAX_MILESTONES)
    for idx, m in enumerate(milestones):
        if not m.id.startswith("m"):
            m.id = f"m{start_id + idx}"
    return milestones
