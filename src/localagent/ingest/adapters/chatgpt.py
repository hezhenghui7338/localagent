"""ChatGPT export ingest: archive → Cold → Warm → Hot."""

from __future__ import annotations

from pathlib import Path

from localagent import config
from localagent.ingest.chatgpt_archive import archive_chatgpt_export
from localagent.ingest.types import IngestContext, IngestReport, IngestStage, SourceKind
from localagent.memory.chatgpt_import import (
    import_chatgpt_dir,
    import_chatgpt_file,
    import_chatgpt_files,
)


class ChatGPTAdapter:
    kind = SourceKind.CHATGPT

    def run(self, ctx: IngestContext) -> IngestReport:
        report = IngestReport(source=self.kind.value)
        interactive = bool(ctx.interactive)

        try:
            if ctx.paths and ctx.directory:
                report.errors.append("不能同时指定 path/--file 与 --dir")
                return report

            if len(ctx.paths) > 1:
                archived = [self._archive(p, report) for p in ctx.paths]
                archived = [p for p in archived if p is not None]
                if not archived:
                    return report
                summary = import_chatgpt_files(
                    archived,
                    force=ctx.force,
                    include_disabled=ctx.include_disabled,
                    reporter=ctx.reporter,
                    interactive=interactive,
                )
            elif len(ctx.paths) == 1:
                archived = self._archive(ctx.paths[0], report)
                if archived is None:
                    return report
                summary = import_chatgpt_file(
                    archived,
                    force=ctx.force,
                    include_disabled=ctx.include_disabled,
                    reporter=ctx.reporter,
                    interactive=interactive,
                )
            elif ctx.directory is not None:
                summary = import_chatgpt_dir(
                    Path(ctx.directory),
                    force=ctx.force,
                    include_disabled=ctx.include_disabled,
                    reporter=ctx.reporter,
                    interactive=interactive,
                )
                report.persisted_paths.append(str(ctx.directory))
                report.stages_done.append(IngestStage.PERSIST.value)
            else:
                default_dir = config.CHATGPT_DATA_DIR
                if default_dir.is_dir() and any(default_dir.glob("*.json")):
                    summary = import_chatgpt_dir(
                        default_dir,
                        force=ctx.force,
                        include_disabled=ctx.include_disabled,
                        reporter=ctx.reporter,
                        interactive=interactive,
                    )
                    report.persisted_paths.append(str(default_dir))
                    report.stages_done.append(IngestStage.PERSIST.value)
                else:
                    # Empty default archive: skip silently (used by `ingest all`)
                    report.skipped = 1
                    report.detail = "no chatgpt exports"
                    return report
        except Exception as exc:
            report.errors.append(str(exc))
            return report

        report.errors.extend(summary.errors)
        report.cold_chunks = int(getattr(summary, "cold_chunks", 0) or 0)
        report.warm_saved = int(summary.saved_count or 0)
        report.skipped = (
            int(summary.skipped_duplicate or 0)
            + int(getattr(summary, "skipped_disabled", 0) or 0)
            + int(getattr(summary, "skipped_empty", 0) or 0)
            + int(getattr(summary, "skipped_do_not_remember", 0) or 0)
        )
        report.stages_done.extend(
            [IngestStage.COLD.value, IngestStage.WARM.value, IngestStage.HOT.value]
        )
        if report.warm_saved:
            report.profile_pins = report.warm_saved
        report.detail = summary.format_summary()
        return report

    def _archive(self, path: Path, report: IngestReport) -> Path | None:
        try:
            archived = archive_chatgpt_export(path)
        except (OSError, FileNotFoundError, ValueError) as exc:
            report.errors.append(str(exc))
            return None
        report.persisted_paths.append(str(archived))
        if IngestStage.PERSIST.value not in report.stages_done:
            report.stages_done.append(IngestStage.PERSIST.value)
        return archived
