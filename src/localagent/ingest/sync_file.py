"""LA sync-file: scan data/kb/ and incrementally index all documents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from localagent import config
from localagent.ingest.pipeline import IngestResult, IngestStatus, ingest_file
from localagent.ingest.progress import ProgressEvent, ProgressReporter


@dataclass
class SyncSummary:
    results: list[IngestResult]

    @property
    def new_count(self) -> int:
        return sum(1 for r in self.results if r.status == IngestStatus.NEW)

    @property
    def updated_count(self) -> int:
        return sum(1 for r in self.results if r.status == IngestStatus.UPDATED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.results if r.status == IngestStatus.SKIPPED)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if r.status == IngestStatus.FAILED)

    def format_summary(self) -> str:
        return (
            f"+{self.new_count} new, ~{self.updated_count} updated, "
            f"={self.skipped_count} skipped, !{self.failed_count} failed"
        )


def list_kb_files() -> list[Path]:
    config.ensure_data_dirs()
    if not config.KB_DIR.exists():
        return []
    files: list[Path] = []
    for path in sorted(config.KB_DIR.iterdir()):
        if not path.is_file() and not path.is_symlink():
            continue
        if path.suffix.lower() not in config.SUPPORTED_SUFFIXES:
            continue
        files.append(path)
    return files


def sync_files(*, force: bool = False, reporter: ProgressReporter | None = None) -> SyncSummary:
    """Index all supported documents under data/kb/."""
    config.ensure_data_dirs()
    kb_files = list_kb_files()
    results: list[IngestResult] = []
    total = len(kb_files)

    if reporter is not None:
        reporter.update(
            ProgressEvent(
                phase="scan",
                message=f"发现 {total} 个文件",
                current=0,
                total=total,
            )
        )

    for index, path in enumerate(kb_files, start=1):
        if reporter is not None:
            reporter.update(
                ProgressEvent(
                    phase="file",
                    message=f"处理 {path.name}",
                    current=index,
                    total=total,
                )
            )
        results.append(ingest_file(path, force=force, reporter=reporter))

    return SyncSummary(results=results)
