"""Planner state dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Milestone:
    id: str
    objective: str
    done_when: str
    status: str = "pending"  # pending | done | failed | skipped
    summary: str = ""


@dataclass
class ActionPlan:
    goal: str
    milestones: list[Milestone]
    replans_used: int = 0

    @property
    def completed(self) -> list[Milestone]:
        return [m for m in self.milestones if m.status == "done"]

    @property
    def pending(self) -> list[Milestone]:
        return [m for m in self.milestones if m.status == "pending"]

    def progress_line(self) -> str:
        done = len(self.completed)
        total = len(self.milestones)
        return f"{done}/{total}"


@dataclass
class PlannerOutcome:
    """Result of a milestone-mode agent turn."""

    response: str
    tool_calls: list[dict]
    plan: ActionPlan | None = None
    partial: bool = False
