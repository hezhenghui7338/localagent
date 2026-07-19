"""Manual text ingest: source note → Cold chunk → Warm direct write → Hot pin."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from localagent import config
from localagent.ingest.chunker import TextChunk, chunk_for_rag
from localagent.ingest.types import IngestContext, IngestReport, IngestStage, SourceKind
from localagent.knowledge.indexer import get_knowledge_indexer
from localagent.memory.save import save_facts


class TextAdapter:
    kind = SourceKind.TEXT

    def run(self, ctx: IngestContext) -> IngestReport:
        report = IngestReport(source=self.kind.value)
        text = (ctx.text or "").strip()
        if not text and ctx.paths:
            # Allow: LA ingest text --file note.txt  OR path as first arg via engine paths
            try:
                text = Path(ctx.paths[0]).expanduser().read_text(encoding="utf-8").strip()
            except OSError as exc:
                report.errors.append(str(exc))
                return report
        if not text:
            report.errors.append('请提供文本: LA ingest text "…"')
            return report

        # 1) Persist source note under data/ingest_notes/
        config.ensure_data_dirs()
        notes_dir = config.DATA_DIR / "ingest_notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        note_path = notes_dir / f"note_{stamp}.md"
        note_path.write_text(text + "\n", encoding="utf-8")
        report.persisted_paths.append(str(note_path))
        report.stages_done.append(IngestStage.PERSIST.value)

        # 2) Cold: single-source chunks
        source_key = f"text:{note_path.name}"
        rag_chunks = chunk_for_rag(text, filename=source_key)
        chunks: list[TextChunk] = []
        for chunk in rag_chunks:
            meta = dict(chunk.metadata or {})
            meta.update(
                {
                    "origin": "text",
                    "archive_path": str(note_path),
                    "chunk_kind": "body",
                }
            )
            chunk.metadata = meta
            chunks.append(chunk)
        report.cold_chunks = get_knowledge_indexer().index_chunks(
            filename=source_key,
            chunks=chunks,
        )
        report.stages_done.append(IngestStage.COLD.value)

        # 3) Warm direct write (bypass pending) + 4) Hot pin via save_facts
        ids = save_facts(
            [text],
            metadata={
                "source": "manual_add",
                "source_file": "LA ingest text",
                "section_heading": "",
                "archive_path": str(note_path),
            },
        )
        report.warm_saved = len(ids)
        report.stages_done.append(IngestStage.WARM.value)
        if ids:
            report.profile_pins = len(ids)
            report.stages_done.append(IngestStage.HOT.value)
            report.detail = f"id={ids[0][:8]}…"
        else:
            report.errors.append("内容太短或无价值，未写入 Warm")
        return report
