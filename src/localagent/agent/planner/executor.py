"""Milestone plan executor."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from localagent import config
from localagent.agent.planner.checker import (
    check_milestone_done,
    observation_suggests_replan,
    summarize_observation,
)
from localagent.agent.planner.replan import replan_remaining
from localagent.agent.planner.state import ActionPlan, Milestone, PlannerOutcome
from localagent.agent.planner.tools_route import select_tools_for_turn
from localagent.agent.react_loop import run_react_loop
from localagent.audit.events import log_event
from localagent.models.router import ChatMessage

logger = logging.getLogger(__name__)


def _format_milestone_context(
    plan: ActionPlan,
    current: Milestone,
) -> str:
    lines = [f"[任务规划 — 总目标: {plan.goal}]"]
    done = [m for m in plan.milestones if m.status == "done"]
    if done:
        lines.append("已完成:")
        for m in done:
            summary = m.summary or "完成"
            lines.append(f"  ✓ {m.objective} ({summary})")
    lines.append(f"当前步骤 ({current.id}): {current.objective}")
    if current.done_when:
        lines.append(f"完成条件: {current.done_when}")
    lines.append("请专注完成当前步骤；完成后简要说明进展。")
    return "\n".join(lines)


def execute_milestone_plan(
    plan: ActionPlan,
    *,
    user_message: str,
    base_messages: list[ChatMessage],
    router: Any,
    prefer: str | None,
    session_id: str | None,
    on_status: Callable[[str], None] | None,
    on_token: Callable[[str], None] | None,
    gated_execute: Callable[[str, dict[str, Any]], str],
    rebuild_system: Callable[..., str],
) -> PlannerOutcome:
    """Execute milestones sequentially with per-milestone ReAct loops."""
    all_tool_calls: list[dict] = []
    max_total = min(
        config.PLANNER_MAX_MILESTONES * config.PLANNER_STEPS_PER_MILESTONE,
        12,
    )
    steps_used = 0
    partial = False
    final_response = ""

    idx = 0
    while idx < len(plan.milestones):
        if steps_used >= max_total:
            partial = True
            break

        current = plan.milestones[idx]
        if current.status == "done":
            idx += 1
            continue

        milestone_ctx = _format_milestone_context(plan, current)
        tools = select_tools_for_turn(
            user_message,
            milestone_mode=True,
            milestone_objective=current.objective,
        )
        system_content = rebuild_system(
            milestone_context=milestone_ctx,
            tool_definitions=tools,
        )

        messages = [ChatMessage(role="system", content=system_content)]
        # Re-use conversation history from base (skip original system).
        for msg in base_messages[1:]:
            messages.append(msg)

        remaining_budget = min(
            config.PLANNER_STEPS_PER_MILESTONE,
            max_total - steps_used,
        )
        loop_result = run_react_loop(
            messages=messages,
            user_message=user_message,
            router=router,
            prefer=prefer,
            session_id=session_id,
            max_iterations=max(1, remaining_budget),
            on_status=on_status,
            on_token=on_token,
            gated_execute=gated_execute,
            skip_file_retry=False,
            milestone_done_when=current.done_when or "",
            milestone_objective=current.objective or "",
            rebuild_system=rebuild_system,
            goal=plan.goal,
        )
        steps_used += len(loop_result.tool_calls)
        all_tool_calls.extend(loop_result.tool_calls)

        done_decision = check_milestone_done(
            current,
            tool_calls=loop_result.tool_calls,
            last_observation=loop_result.last_observation,
            last_tool_name=loop_result.last_tool_name,
            last_validation=loop_result.last_validation,
            router=router,
            agent_response=loop_result.response,
            semantic_calls=loop_result.semantic_calls,
        )
        if done_decision.done:
            current.status = "done"
            current.summary = summarize_observation(
                loop_result.last_tool_name,
                loop_result.last_observation,
            )
            final_response = loop_result.response
            idx += 1
            continue

        # Milestone not done — try replan once if observation suggests failure.
        if (
            observation_suggests_replan(loop_result.last_observation)
            or loop_result.exhausted
        ):
            revised = replan_remaining(
                plan,
                user_message=user_message,
                current=current,
                last_observation=loop_result.last_observation,
            )
            if revised:
                log_event(
                    "planner.replan",
                    session_id=session_id,
                    failed_milestone=current.id,
                    revised_count=len(revised),
                )
                current.status = "failed"
                plan.milestones = plan.milestones[:idx] + revised
                idx = len(plan.milestones) - len(revised)
                continue

            partial = True
            current.status = "failed"
            final_response = loop_result.response or (
                f"步骤「{current.objective}」未能完成。"
                f"已完成 {plan.progress_line()} 个里程碑。"
            )
            break

        # Accept partial progress when loop returned tools but done_when not verified.
        if loop_result.tool_calls:
            if done_decision.llm_rejected:
                partial = True
                current.status = "failed"
                final_response = loop_result.response or (
                    f"步骤「{current.objective}」尚未满足完成条件。"
                    f"已完成 {plan.progress_line()} 个里程碑。"
                )
                break
            current.status = "done"
            current.summary = summarize_observation(
                loop_result.last_tool_name,
                loop_result.last_observation,
            )
            final_response = loop_result.response
            idx += 1
        else:
            final_response = loop_result.response
            break

    if not final_response:
        done = plan.completed
        if done:
            final_response = (
                f"已完成 {plan.progress_line()} 个步骤。"
                f"最后一步: {done[-1].objective}"
            )
        else:
            final_response = "任务未能完成任何步骤。"

    if partial or plan.pending:
        partial = True

    return PlannerOutcome(
        response=final_response,
        tool_calls=all_tool_calls,
        plan=plan,
        partial=partial,
    )
