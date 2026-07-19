"""Document file ingest: symlink into kb/ → Cold → Warm summary → Hot pin."""

from __future__ import annotations

from localagent.ingest.add_file import SensitiveIngestError, add_file, add_file_background
from localagent.ingest.types import IngestContext, IngestReport, IngestStage, SourceKind


class DocAdapter:
    kind = SourceKind.DOC

    def run(self, ctx: IngestContext) -> IngestReport:
        report = IngestReport(source=self.kind.value)
        if not ctx.paths:
            report.errors.append("请指定文档路径: LA ingest doc <path>")
            return report
        if len(ctx.paths) > 1:
            report.errors.append("doc 一次只支持一个路径；多个文件请分别调用或放入 kb/ 后 LA ingest kb")
            return report

        path = ctx.paths[0]
        try:
            if ctx.background:
                target, task, pid = add_file_background(path)
                report.persisted_paths.append(str(target))
                report.stages_done.append(IngestStage.PERSIST.value)
                log_hint = f" log={task.log_path}" if task.log_path else ""
                report.detail = f"background task={task.id} pid={pid}{log_hint}"
                return report

            target, result = add_file(path, reporter=ctx.reporter)
        except KeyboardInterrupt:
            report.errors.append("interrupted")
            return report
        except (FileNotFoundError, ValueError, FileExistsError, SensitiveIngestError) as exc:
            report.errors.append(str(exc))
            return report

        report.persisted_paths.append(str(target))
        report.stages_done.append(IngestStage.PERSIST.value)
        report.cold_chunks = int(result.knowledge_chunk_count or 0)
        report.warm_saved = int(result.memory_fact_count or 0)
        if result.status.value == "skipped":
            report.skipped = 1
        if result.status.value == "failed":
            report.errors.append(result.error or "ingest failed")
        report.stages_done.extend(
            [IngestStage.COLD.value, IngestStage.WARM.value, IngestStage.HOT.value]
        )
        if report.warm_saved:
            report.profile_pins = report.warm_saved
        report.detail = f"{result.status.value} chunks={report.cold_chunks} warm={report.warm_saved}"
        return report
