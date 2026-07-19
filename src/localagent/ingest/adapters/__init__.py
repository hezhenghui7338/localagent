"""Source adapters for the unified ingest engine (lazy registry)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from localagent.ingest.types import SourceKind

if TYPE_CHECKING:
    from localagent.ingest.types import SourceAdapter


def get_adapter(kind: SourceKind) -> SourceAdapter:
    """Resolve adapter by kind (imports deferred to avoid circular imports)."""
    if kind == SourceKind.CHAT:
        from localagent.ingest.adapters.chat import ChatAdapter

        return ChatAdapter()
    if kind == SourceKind.CHATGPT:
        from localagent.ingest.adapters.chatgpt import ChatGPTAdapter

        return ChatGPTAdapter()
    if kind == SourceKind.DOC:
        from localagent.ingest.adapters.doc import DocAdapter

        return DocAdapter()
    if kind == SourceKind.KB:
        from localagent.ingest.adapters.kb import KbAdapter

        return KbAdapter()
    if kind == SourceKind.TEXT:
        from localagent.ingest.adapters.text import TextAdapter

        return TextAdapter()
    if kind == SourceKind.AWARE:
        from localagent.ingest.adapters.aware import AwareAdapter

        return AwareAdapter()
    if kind == SourceKind.NEWS:
        from localagent.ingest.adapters.news import NewsAdapter

        return NewsAdapter()
    if kind == SourceKind.SUMMARIZE:
        from localagent.ingest.adapters.summarize import SummarizeAdapter

        return SummarizeAdapter()
    if kind == SourceKind.POLISH:
        from localagent.ingest.adapters.polish import PolishAdapter

        return PolishAdapter()
    raise ValueError(f"无 adapter: {kind.value}")
