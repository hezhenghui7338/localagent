"""Session working memory — structured cross-turn task continuation.

Stores a small JSON snapshot (active milestone plan, touched file paths) so
partial multi-step tasks survive turn boundaries without loading full tool
traces into the LLM context. See docs/TDD.md §1.1 Runtime state layers.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from localagent import config

_CONTINUE_RE = re.compile(
    r"(?:继续|接着|往下|下一步|continue|go\s+on|resume)",
    re.IGNORECASE,
)
_FILE_TOOL_NAMES = frozenset({"read_file", "write_file", "edit_file"})
_DEFAULT_PREFETCH_BUDGET = 200


def work_path(session_id: str) -> Path:
    return config.SESSIONS_WORK_DIR / f"{session_id}.work.json"


def is_continue_query(user_message: str) -> bool:
    """True when the user likely wants to resume an in-progress task."""
    return bool(_CONTINUE_RE.search((user_message or "").strip()))


def load_session_work(session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    path = work_path(session_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_session_work(session_id: str, payload: dict[str, Any]) -> None:
    config.ensure_data_dirs()
    path = work_path(session_id)
    out = dict(payload)
    out["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_session_work(session_id: str | None) -> None:
    if not session_id:
        return
    path = work_path(session_id)
    if path.is_file():
        path.unlink(missing_ok=True)


def tool_targets_from_calls(tool_calls: list[dict[str, Any]] | None) -> list[str]:
    """Collect file paths touched by read/write/edit tools in a turn."""
    seen: set[str] = set()
    out: list[str] = []
    for call in tool_calls or []:
        name = str(call.get("name") or call.get("tool") or "")
        if name not in _FILE_TOOL_NAMES:
            continue
        args = call.get("arguments") or {}
        if not isinstance(args, dict):
            continue
        path = str(args.get("path") or "").strip()
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def plan_to_work_dict(plan: Any, *, partial: bool) -> dict[str, Any]:
    """Serialize an ActionPlan for session work storage."""
    return {
        "goal": plan.goal,
        "partial": partial,
        "replans_used": getattr(plan, "replans_used", 0),
        "milestones": [
            {
                "id": m.id,
                "objective": m.objective,
                "done_when": m.done_when,
                "status": m.status,
                "summary": m.summary,
            }
            for m in plan.milestones
        ],
    }


def work_to_action_plan(plan_dict: dict[str, Any] | None) -> Any | None:
    """Deserialize stored session work into an ActionPlan."""
    if not isinstance(plan_dict, dict):
        return None
    from localagent.agent.planner.state import ActionPlan, Milestone

    raw_milestones = plan_dict.get("milestones")
    if not isinstance(raw_milestones, list) or not raw_milestones:
        return None
    milestones: list[Milestone] = []
    for item in raw_milestones:
        if not isinstance(item, dict):
            continue
        objective = str(item.get("objective") or "").strip()
        if not objective:
            continue
        milestones.append(
            Milestone(
                id=str(item.get("id") or f"m{len(milestones) + 1}"),
                objective=objective,
                done_when=str(item.get("done_when") or "").strip(),
                status=str(item.get("status") or "pending"),
                summary=str(item.get("summary") or "").strip(),
            )
        )
    if not milestones:
        return None
    goal = str(plan_dict.get("goal") or milestones[0].objective).strip()
    replans_used = plan_dict.get("replans_used")
    try:
        replans = int(replans_used) if replans_used is not None else 0
    except (TypeError, ValueError):
        replans = 0
    return ActionPlan(goal=goal, milestones=milestones, replans_used=max(0, replans))


def resume_action_plan(
    session_id: str | None,
    user_message: str,
) -> Any | None:
    """Load a partial milestone plan when the user asks to continue."""
    if not session_id or not is_continue_query(user_message):
        return None
    work = load_session_work(session_id)
    if not work or work_stale(work):
        return None
    plan_dict = work.get("active_plan")
    if not isinstance(plan_dict, dict):
        return None
    plan = work_to_action_plan(plan_dict)
    if plan is None:
        return None
    if not plan.pending and not plan_dict.get("partial"):
        return None
    return plan


def format_work_prefetch(
    work: dict[str, Any] | None,
    *,
    budget: int = _DEFAULT_PREFETCH_BUDGET,
) -> str:
    """Format session work as a compact prefetch block (~200 chars default)."""
    if not work:
        return ""
    plan = work.get("active_plan")
    if not isinstance(plan, dict):
        return ""

    lines: list[str] = ["【进行中的任务】"]
    goal = str(plan.get("goal") or "").strip()
    if goal:
        lines.append(f"目标: {goal}")

    milestones = plan.get("milestones") or []
    if isinstance(milestones, list):
        done = [m for m in milestones if isinstance(m, dict) and m.get("status") == "done"]
        pending = [
            m for m in milestones if isinstance(m, dict) and m.get("status") == "pending"
        ]
        if done:
            lines.append(f"已完成 ({len(done)}):")
            for m in done[:3]:
                obj = str(m.get("objective") or m.get("summary") or "").strip()
                if obj:
                    lines.append(f"  ✓ {obj}")
        if pending:
            lines.append(f"待完成 ({len(pending)}):")
            for m in pending[:2]:
                obj = str(m.get("objective") or "").strip()
                if obj:
                    lines.append(f"  ○ {obj}")

    targets = work.get("last_tool_targets") or []
    if isinstance(targets, list) and targets:
        shown = ", ".join(str(t) for t in targets[:3])
        lines.append(f"相关文件: {shown}")

    if plan.get("partial"):
        lines.append("（部分完成，用户可能说「继续」以推进剩余步骤）")

    text = "\n".join(lines)
    if len(text) <= budget:
        return text
    return text[: max(40, budget - 1)] + "…"


def sync_session_work(
    session_id: str | None,
    *,
    user_message: str,
    action_plan: Any | None = None,
    partial: bool = False,
    tool_calls: list[dict[str, Any]] | None = None,
) -> None:
    """Persist or clear session work after an agent turn."""
    if not session_id:
        return

    new_targets = tool_targets_from_calls(tool_calls)
    existing = load_session_work(session_id) or {}
    merged_targets = list(
        dict.fromkeys(new_targets + list(existing.get("last_tool_targets") or []))
    )[:8]

    if action_plan is not None:
        has_pending = any(m.status == "pending" for m in action_plan.milestones)
        if partial or has_pending:
            save_session_work(
                session_id,
                {
                    "active_plan": plan_to_work_dict(action_plan, partial=partial or has_pending),
                    "last_tool_targets": merged_targets,
                },
            )
            return
        clear_session_work(session_id)
        return

    if is_continue_query(user_message) and existing.get("active_plan"):
        save_session_work(
            session_id,
            {
                "active_plan": existing["active_plan"],
                "last_tool_targets": merged_targets or existing.get("last_tool_targets") or [],
            },
        )


def work_stale(work: dict[str, Any] | None, *, max_age_hours: float = 72.0) -> bool:
    """True when stored work is older than max_age_hours."""
    if not work:
        return True
    raw = work.get("updated_at")
    if not raw:
        return False
    try:
        text = str(raw).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = time.time() - dt.timestamp()
        return age > max_age_hours * 3600
    except ValueError:
        return False
