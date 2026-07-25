"""Replan gate — revise remaining milestones after failure."""

from __future__ import annotations

import logging

from localagent import config
from localagent.agent.planner.milestone import parse_revised_milestones
from localagent.agent.planner.state import ActionPlan, Milestone

logger = logging.getLogger(__name__)


def replan_remaining(
    plan: ActionPlan,
    *,
    user_message: str,
    current: Milestone,
    last_observation: str,
) -> list[Milestone] | None:
    """Ask the model to revise remaining milestones; None on failure."""
    if plan.replans_used >= config.PLANNER_MAX_REPLAN:
        return None

    try:
        from localagent.models.router import ChatMessage, get_model_router
    except Exception:
        return None

    completed_lines = [
        f"- {m.id}: {m.objective} → {m.summary or '完成'}"
        for m in plan.milestones
        if m.status == "done"
    ]
    prompt = (
        "你是行动任务规划器。当前 milestone 未成功完成，请修订后续步骤。\n"
        "只输出 JSON（不要 markdown）：\n"
        '{"status":"revise","milestones":[\n'
        '  {"id":"m2","objective":"修订后的子目标","done_when":"可观察完成条件"}\n'
        "]}\n"
        "规则：\n"
        "- 只输出尚未完成的后续 milestone（不要重复已完成步骤）\n"
        "- 根据失败原因调整策略\n"
        "- 最多 3 个后续 milestone\n\n"
        f"原始目标：{plan.goal}\n"
        f"用户请求：{user_message}\n"
        f"当前失败步骤：{current.objective}\n"
        f"完成条件：{current.done_when}\n"
        f"最近观察：{(last_observation or '')[:800]}\n"
        f"已完成：\n" + ("\n".join(completed_lines) if completed_lines else "（无）") + "\n"
    )
    try:
        reply = get_model_router().chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.0,
            usage_command="action_replan",
        )
    except Exception as exc:
        logger.debug("replan failed: %s", exc)
        return None

    start_id = len(plan.completed) + 1
    revised = parse_revised_milestones(reply, start_id=start_id)
    if not revised:
        return None
    plan.replans_used += 1
    return revised
