"""News → unified ingest (explicit keep path)."""

from __future__ import annotations

from localagent.ingest.types import IngestContext, IngestReport, SourceKind


class NewsAdapter:
    kind = SourceKind.NEWS

    def run(self, ctx: IngestContext) -> IngestReport:
        if ctx.paths:
            from localagent.ingest.adapters.doc import DocAdapter

            return DocAdapter().run(ctx)
        return IngestReport(
            source=self.kind.value,
            errors=[
                "新闻默认不入库。精读后 --keep，或: LA ingest news <path> / LA ingest doc <path>"
            ],
            detail="stub: pass a kept article file path",
        )
