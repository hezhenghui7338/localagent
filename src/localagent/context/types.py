"""Turn-level context types for the Context Engine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from localagent.context.router import PrefetchRoute
from localagent.models.router import ChatMessage

if TYPE_CHECKING:
    from localagent.context.working_memory import ReactWorkingMemory


@dataclass(frozen=True)
class ContextBlocks:
    work: str = ""
    personal: str = ""
    archive: str = ""
    session: str = ""
    web: str = ""
    workspace: str = ""
    aware: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "work": self.work,
            "personal": self.personal,
            "archive": self.archive,
            "session": self.session,
            "web": self.web,
            "workspace": self.workspace,
            "aware": self.aware,
        }

    @classmethod
    def from_dict(cls, blocks: dict[str, str]) -> ContextBlocks:
        return cls(
            work=blocks.get("work", ""),
            personal=blocks.get("personal", ""),
            archive=blocks.get("archive", ""),
            session=blocks.get("session", ""),
            web=blocks.get("web", ""),
            workspace=blocks.get("workspace", ""),
            aware=blocks.get("aware", ""),
        )


@dataclass
class TurnContext:
    """Assembled LLM messages and prefetch state for one agent turn."""

    messages: list[ChatMessage]
    blocks: ContextBlocks
    route: PrefetchRoute
    rebuild_system: Callable[..., str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def open_working_memory(
        self,
        *,
        goal: str,
        user_query: str,
        prefer: str | None = None,
        router: Any = None,
    ) -> ReactWorkingMemory:
        """Start ReAct working memory for this turn (evidence + observation compression)."""
        from localagent.context.working_memory import ReactWorkingMemory

        return ReactWorkingMemory(
            goal=(goal or user_query).strip(),
            user_query=user_query,
            prefer=prefer,
            router=router,
            rebuild_system=self.rebuild_system,
        )
