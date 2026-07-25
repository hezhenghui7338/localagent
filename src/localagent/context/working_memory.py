"""ReAct working memory — tool observation compression and turn evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from localagent.context.compress import (
    EvidenceEntry,
    compact_prior_observations,
    compress_observation,
    extract_evidence_bullet,
    format_turn_evidence,
    resolve_context_tier,
    tool_path_signature,
)
from localagent.models.router import ChatMessage


@dataclass
class ReactWorkingMemory:
    """Manages ReAct-turn evidence accumulation and observation compression."""

    goal: str
    user_query: str
    prefer: str | None = None
    router: Any = None
    rebuild_system: Any = None
    evidence_entries: list[EvidenceEntry] = field(default_factory=list)
    evidence_signatures: set[str] = field(default_factory=set)

    def tier(self):
        return resolve_context_tier(
            self.prefer,
            getattr(self.router, "last_provider", None) if self.router else None,
        )

    def compress_tool_observation(
        self,
        tool_name: str,
        result: str,
        *,
        budget: int | None = None,
    ) -> str:
        limit = budget if budget is not None else self.tier().observe_budget
        return compress_observation(
            tool_name,
            result,
            user_query=self.user_query,
            budget=limit,
        )

    def append_evidence(
        self,
        tool_name: str,
        annotated: str,
        *,
        arguments: dict[str, Any] | None = None,
    ) -> EvidenceEntry:
        entry = extract_evidence_bullet(
            tool_name,
            annotated,
            user_query=self.user_query,
            arguments=arguments or {},
            step=len(self.evidence_entries) + 1,
        )
        self.evidence_entries.append(entry)
        self.evidence_signatures.add(entry.signature)
        return entry

    def format_evidence_block(self) -> str:
        tier = self.tier()
        return format_turn_evidence(
            self.evidence_entries,
            goal=self.goal,
            budget=tier.evidence_budget,
        )

    def refresh_system(self, messages: list[ChatMessage]) -> None:
        if not self.rebuild_system or not messages:
            return
        messages[0] = ChatMessage(
            role="system",
            content=self.rebuild_system(turn_evidence=self.format_evidence_block()),
        )

    def compact_prior_observations(self, messages: list[ChatMessage]) -> None:
        compact_prior_observations(
            messages,
            keep_full_rounds=self.tier().keep_full_rounds,
        )

    def repeat_breaker_message(self) -> str:
        content = (
            "你重复调用了相同工具与参数。请根据已有结果直接给出最终回答，"
            "不要再次调用相同工具。"
        )
        evidence_block = self.format_evidence_block()
        if evidence_block:
            content = f"{content}\n\n{evidence_block}"
        return content

    def path_signature_seen(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        return tool_path_signature(tool_name, arguments) in self.evidence_signatures
