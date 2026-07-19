"""LA chat conversation archive ingest (Cold → Warm → Hot)."""

from __future__ import annotations

from localagent.ingest.types import IngestContext, IngestReport, IngestStage, SourceKind
from localagent.memory.rememorize import ingest_chat


class ChatAdapter:
    kind = SourceKind.CHAT

    def run(self, ctx: IngestContext) -> IngestReport:
        report = IngestReport(source=self.kind.value)
        report.stages_done.append(IngestStage.PERSIST.value)  # archives already on disk

        ids = ingest_chat(
            session_id=ctx.session_id,
            force=ctx.force,
            reporter=ctx.reporter,
            interactive=ctx.interactive if ctx.interactive else None,
        )
        report.warm_saved = len(ids)
        report.stages_done.extend(
            [IngestStage.COLD.value, IngestStage.WARM.value, IngestStage.HOT.value]
        )

        # Approximate cold chunks from ingest index
        try:
            import json

            from localagent import config

            raw = json.loads(config.CHAT_INGEST_INDEX_FILE.read_text(encoding="utf-8"))
            for entry in (raw.get("processed") or {}).values():
                if isinstance(entry, dict):
                    report.cold_chunks += int(entry.get("cold_chunk_count") or 0)
        except Exception:
            pass

        if ids:
            report.profile_pins = len(ids)  # pin attempted for each saved fact
            report.detail = f"saved={len(ids)}"
        else:
            report.detail = f"未提取到新记忆 · cold≈{report.cold_chunks}"
        return report
