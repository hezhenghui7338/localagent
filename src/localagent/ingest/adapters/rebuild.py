"""Rebuild Cold indexes (kb/ + conversation archives)."""

from __future__ import annotations

from localagent.ingest.types import IngestContext, IngestReport, IngestStage, SourceKind
from localagent.memory.reset import rebuild_knowledge


class RebuildAdapter:
    kind = SourceKind.REBUILD

    def run(self, ctx: IngestContext) -> IngestReport:
        report = IngestReport(source="rebuild")
        reset_stats, summary = rebuild_knowledge(reporter=ctx.reporter)
        report.cold_chunks = int(reset_stats.get("knowledge_chunks_removed") or 0)
        report.cold_chunks += int(reset_stats.get("conversation_cold_chunks") or 0)
        for result in summary.results:
            report.cold_chunks += int(result.knowledge_chunk_count or 0)
            report.warm_saved += int(result.memory_fact_count or 0)
            if result.status.value == "failed" and result.error:
                report.errors.append(f"{result.filename}: {result.error}")
        report.stages_done.extend(
            [IngestStage.COLD.value, IngestStage.WARM.value, IngestStage.HOT.value]
        )
        report.detail = (
            f"kb={summary.format_summary()} · "
            f"conv_cold={reset_stats.get('conversation_cold_chunks', 0)}"
        )
        return report
