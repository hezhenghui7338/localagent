"""Unified ingest engine: dispatch by SourceKind → SourceAdapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from localagent.ingest.adapters import get_adapter
from localagent.ingest.types import (
    ALL_PIPELINE_SOURCES,
    STUB_SOURCES,
    IngestContext,
    IngestReport,
    SourceKind,
)


def parse_source_kind(raw: str) -> SourceKind:
    key = (raw or "").strip().lower()
    try:
        return SourceKind(key)
    except ValueError as exc:
        known = ", ".join(k.value for k in SourceKind if k != SourceKind.REBUILD)
        raise ValueError(f"未知来源: {raw}（可用: {known}）") from exc


def run_ingest(
    kind: str | SourceKind,
    *,
    force: bool = False,
    interactive: bool = False,
    include_disabled: bool = False,
    background: bool = False,
    session_id: str | None = None,
    paths: list[str | Path] | None = None,
    directory: str | Path | None = None,
    text: str | None = None,
    reporter: Any | None = None,
) -> IngestReport:
    """Run the unified persist → Cold → Warm → Hot pipeline for one source (or all)."""
    source = kind if isinstance(kind, SourceKind) else parse_source_kind(str(kind))

    if source == SourceKind.ALL:
        report = IngestReport(source="all")
        for sub in ALL_PIPELINE_SOURCES:
            sub_report = run_ingest(
                sub,
                force=force,
                interactive=interactive,
                include_disabled=include_disabled,
                background=False,
                session_id=session_id if sub == SourceKind.CHAT else None,
                paths=None,
                directory=None,
                text=None,
                reporter=reporter,
            )
            report.merge(sub_report)
        return report

    if source == SourceKind.REBUILD:
        from localagent.ingest.adapters.rebuild import RebuildAdapter

        ctx = IngestContext(force=force, reporter=reporter)
        return RebuildAdapter().run(ctx)

    adapter = get_adapter(source)
    ctx = IngestContext(
        force=force,
        interactive=interactive,
        include_disabled=include_disabled,
        background=background,
        session_id=session_id,
        paths=[Path(p) for p in (paths or [])],
        directory=Path(directory) if directory else None,
        text=text,
        reporter=reporter,
    )
    return adapter.run(ctx)


def list_sources(*, include_stubs: bool = True) -> list[str]:
    names = [k.value for k in SourceKind if k not in (SourceKind.ALL, SourceKind.REBUILD)]
    if not include_stubs:
        names = [n for n in names if SourceKind(n) not in STUB_SOURCES]
    return names
