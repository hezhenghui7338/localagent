"""Summarize session → unified ingest (explicit keep path)."""

from __future__ import annotations

from localagent.ingest.types import IngestContext, IngestReport, SourceKind


class SummarizeAdapter:
    kind = SourceKind.SUMMARIZE

    def run(self, ctx: IngestContext) -> IngestReport:
        if ctx.paths:
            from localagent.ingest.adapters.doc import DocAdapter

            return DocAdapter().run(ctx)
        return IngestReport(
            source=self.kind.value,
            errors=[
                "总结默认不入库。使用 --keep / /keep，或: LA ingest summarize <path>"
            ],
            detail="stub: pass document path to keep",
        )
