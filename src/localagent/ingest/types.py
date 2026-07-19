"""Shared types for the unified ingest engine (persist → Cold → Warm → Hot)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol


class SourceKind(str, Enum):
    CHAT = "chat"
    CHATGPT = "chatgpt"
    DOC = "doc"
    KB = "kb"
    TEXT = "text"
    ALL = "all"
    AWARE = "aware"
    NEWS = "news"
    SUMMARIZE = "summarize"
    POLISH = "polish"
    REBUILD = "rebuild"


class IngestStage(str, Enum):
    PERSIST = "persist"
    COLD = "cold"
    WARM = "warm"
    HOT = "hot"


CORE_SOURCES: tuple[SourceKind, ...] = (
    SourceKind.CHAT,
    SourceKind.CHATGPT,
    SourceKind.DOC,
    SourceKind.KB,
    SourceKind.TEXT,
)

ALL_PIPELINE_SOURCES: tuple[SourceKind, ...] = (
    SourceKind.CHAT,
    SourceKind.CHATGPT,
    SourceKind.KB,
)

STUB_SOURCES: frozenset[SourceKind] = frozenset(
    {
        SourceKind.AWARE,
        SourceKind.NEWS,
        SourceKind.SUMMARIZE,
        SourceKind.POLISH,
    }
)


@dataclass
class IngestContext:
    """Runtime options passed to every SourceAdapter."""

    force: bool = False
    interactive: bool = False
    include_disabled: bool = False
    background: bool = False
    session_id: str | None = None
    paths: list[Path] = field(default_factory=list)
    directory: Path | None = None
    text: str | None = None
    reporter: Any | None = None


@dataclass
class IngestReport:
    """Aggregated outcome of one ingest run."""

    source: str
    persisted_paths: list[str] = field(default_factory=list)
    cold_chunks: int = 0
    warm_saved: int = 0
    warm_pending: int = 0
    profile_pins: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    stages_done: list[str] = field(default_factory=list)
    detail: str = ""

    def merge(self, other: IngestReport) -> IngestReport:
        self.persisted_paths.extend(other.persisted_paths)
        self.cold_chunks += other.cold_chunks
        self.warm_saved += other.warm_saved
        self.warm_pending += other.warm_pending
        self.profile_pins += other.profile_pins
        self.skipped += other.skipped
        self.errors.extend(other.errors)
        for stage in other.stages_done:
            if stage not in self.stages_done:
                self.stages_done.append(stage)
        if other.detail:
            self.detail = f"{self.detail}; {other.detail}".strip("; ")
        return self

    def format_summary(self) -> str:
        parts = [
            f"source={self.source}",
            f"cold={self.cold_chunks}",
            f"warm={self.warm_saved}",
        ]
        if self.warm_pending:
            parts.append(f"pending={self.warm_pending}")
        if self.profile_pins:
            parts.append(f"profile={self.profile_pins}")
        if self.skipped:
            parts.append(f"skipped={self.skipped}")
        if self.persisted_paths:
            parts.append(f"files={len(self.persisted_paths)}")
        if self.errors:
            parts.append(f"errors={len(self.errors)}")
        return " · ".join(parts)

    @property
    def ok(self) -> bool:
        return not self.errors or self.cold_chunks > 0 or self.warm_saved > 0


class SourceAdapter(Protocol):
    """Adapter contract: each source implements a full persist→Cold→Warm→Hot run."""

    kind: SourceKind

    def run(self, ctx: IngestContext) -> IngestReport:
        """Execute ingest for this source."""
        ...
