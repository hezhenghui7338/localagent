"""Polish output has no durable artifact by default."""

from __future__ import annotations

from localagent.ingest.types import IngestContext, IngestReport, SourceKind


class PolishAdapter:
    kind = SourceKind.POLISH

    def run(self, ctx: IngestContext) -> IngestReport:
        if ctx.text:
            from localagent.ingest.adapters.text import TextAdapter

            return TextAdapter().run(ctx)
        if ctx.paths:
            from localagent.ingest.adapters.doc import DocAdapter

            return DocAdapter().run(ctx)
        return IngestReport(
            source=self.kind.value,
            errors=[
                "polish 默认不持久化。若要入库: LA ingest polish \"…\" 或 LA ingest text \"…\""
            ],
            detail="stub: pass text or file to persist",
        )
