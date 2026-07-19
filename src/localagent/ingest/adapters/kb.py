"""Scan data/kb/ and run the document ingest pipeline."""

from __future__ import annotations

from localagent import config
from localagent.ingest.sync_file import sync_files
from localagent.ingest.types import IngestContext, IngestReport, IngestStage, SourceKind


class KbAdapter:
    kind = SourceKind.KB

    def run(self, ctx: IngestContext) -> IngestReport:
        report = IngestReport(source=self.kind.value)
        report.persisted_paths.append(str(config.KB_DIR))
        report.stages_done.append(IngestStage.PERSIST.value)

        summary = sync_files(force=ctx.force, reporter=ctx.reporter)
        if not summary.results:
            report.detail = f"no supported files in {config.KB_DIR}/"
            return report

        for result in summary.results:
            report.cold_chunks += int(result.knowledge_chunk_count or 0)
            report.warm_saved += int(result.memory_fact_count or 0)
            if result.status.value == "skipped":
                report.skipped += 1
            if result.status.value == "failed" and result.error:
                report.errors.append(f"{result.filename}: {result.error}")

        report.stages_done.extend(
            [IngestStage.COLD.value, IngestStage.WARM.value, IngestStage.HOT.value]
        )
        if report.warm_saved:
            report.profile_pins = report.warm_saved
        report.detail = summary.format_summary()
        return report
