"""Aware → unified ingest (explicit only; does not auto-run on tick)."""

from __future__ import annotations

from localagent.ingest.types import IngestContext, IngestReport, SourceKind


class AwareAdapter:
    kind = SourceKind.AWARE

    def run(self, ctx: IngestContext) -> IngestReport:
        _ = ctx
        return IngestReport(
            source=self.kind.value,
            errors=[
                "aware 默认不自动入库。"
                "请将可索引文件 suggestion 确认后执行: LA ingest doc <path>"
            ],
            detail="stub: use LA ingest doc for suggested files",
        )
