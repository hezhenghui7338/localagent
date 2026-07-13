"""Shared ingest pipeline: load → chunk → retain + RAG → sync_index."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from localagent import config
from localagent.ingest.chunker import chunk_for_rag, split_into_sections
from localagent.ingest.loader import LoadedDoc, load_file
from localagent.ingest.progress import ProgressEvent, ProgressReporter
from localagent.ingest.sync_index import content_hash, get_sync_index
from localagent.knowledge.indexer import get_knowledge_indexer
from localagent.memory.backend import get_memory_backend
from localagent.memory.value_filter import should_retain_as_memory


class IngestStatus(str, Enum):
    NEW = "new"
    UPDATED = "updated"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class IngestResult:
    filename: str
    path: str
    status: IngestStatus
    memory_fact_count: int = 0
    knowledge_chunk_count: int = 0
    content_hash: str = ""
    error: str = ""

    @property
    def tag(self) -> str:
        return {
            IngestStatus.NEW: "+",
            IngestStatus.UPDATED: "~",
            IngestStatus.SKIPPED: "=",
            IngestStatus.FAILED: "!",
        }[self.status]


def ingest_file(
    path: Path,
    *,
    force: bool = False,
    reporter: ProgressReporter | None = None,
) -> IngestResult:
    """Index a single file into memory + knowledge stores."""
    path = Path(path).resolve()
    filename = path.name

    def _report(phase: str, message: str, current: int = 0, total: int = 0) -> None:
        if reporter is not None:
            reporter.update(ProgressEvent(phase=phase, message=message, current=current, total=total))

    _report("load", f"加载文件 {filename}")
    doc = load_file(path)
    if doc is None:
        return IngestResult(
            filename=filename,
            path=str(path),
            status=IngestStatus.FAILED,
            error="unsupported or empty file",
        )

    size_kb = max(len(doc.text.encode("utf-8")) / 1024, 0.1)
    _report("load", f"已加载 {filename} ({size_kb:.1f} KB)")

    file_hash = content_hash(doc.text)
    sync_index = get_sync_index()

    if sync_index.should_skip(filename, file_hash, force=force):
        record = sync_index.get(filename)
        _report("skip", f"文件未变更，跳过索引")
        return IngestResult(
            filename=filename,
            path=str(path),
            status=IngestStatus.SKIPPED,
            memory_fact_count=record.memory_fact_count if record else 0,
            knowledge_chunk_count=record.knowledge_chunk_count if record else 0,
            content_hash=file_hash,
        )

    previous = sync_index.get(filename)
    status = IngestStatus.NEW if previous is None else IngestStatus.UPDATED

    try:
        memory_count, knowledge_count = _index_document(doc, reporter=reporter)
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        return IngestResult(
            filename=filename,
            path=str(path),
            status=IngestStatus.FAILED,
            content_hash=file_hash,
            error=str(exc),
        )

    _report("save", "写入 sync_index 与记忆存储")
    sync_index.upsert(
        filename,
        path=str(path),
        current_hash=file_hash,
        memory_fact_count=memory_count,
        knowledge_chunk_count=knowledge_count,
    )
    sync_index.save()
    from localagent.memory.store import get_memory_store

    get_memory_store().save()

    _report("done", f"完成: facts={memory_count}, chunks={knowledge_count}")
    return IngestResult(
        filename=filename,
        path=str(path),
        status=status,
        memory_fact_count=memory_count,
        knowledge_chunk_count=knowledge_count,
        content_hash=file_hash,
    )


def _index_document(doc: LoadedDoc, *, reporter: ProgressReporter | None = None) -> tuple[int, int]:
    def _report(phase: str, message: str, current: int = 0, total: int = 0) -> None:
        if reporter is not None:
            reporter.update(ProgressEvent(phase=phase, message=message, current=current, total=total))

    indexer = get_knowledge_indexer()
    backend = get_memory_backend()

    backend.remove_by_source_file(doc.filename)

    sections = split_into_sections(doc.text, filename=doc.filename)
    memory_sections = [
        s for s in sections if should_retain_as_memory(s.text, heading=s.heading)
    ]
    max_facts = config.INGEST_MEMORY_MAX_FACTS
    if len(memory_sections) > max_facts:
        memory_sections = memory_sections[:max_facts]
    _report(
        "split",
        f"切分 {len(sections)} 个章节，{len(memory_sections)} 个写入记忆（启发式）",
    )

    memory_count = 0
    total = len(memory_sections)

    for idx, section in enumerate(memory_sections, start=1):
        heading = section.heading[:40]
        _report("memory", f"写入记忆: {heading}", current=idx, total=total)
        facts: list[str] = []
        if config.INGEST_USE_LLM:
            from localagent.models.router import get_model_router

            try:
                facts = get_model_router().extract_facts(
                    section.text,
                    context=f"{doc.filename} / {section.heading}",
                )
            except Exception:
                facts = []

        doc_recorded_at = doc.metadata.get("modified_at")
        if facts:
            for fact_text in facts:
                fact_id = backend.retain(
                    fact_text,
                    metadata={
                        "source": "ingest",
                        "source_file": doc.filename,
                        "section_heading": section.heading,
                        "chunk_id": section.chunk_id,
                        "document_id": doc.filename,
                        "recorded_at": doc_recorded_at,
                    },
                )
                if fact_id:
                    memory_count += 1
        else:
            fact_id = backend.retain(
                section.text,
                metadata={
                    "source": "ingest",
                    "source_file": doc.filename,
                    "section_heading": section.heading,
                    "chunk_id": section.chunk_id,
                    "document_id": doc.filename,
                    "recorded_at": doc_recorded_at,
                },
            )
            if fact_id:
                memory_count += 1

    _report("knowledge", "构建知识库向量与 BM25 索引")
    rag_chunks = chunk_for_rag(doc.text, filename=doc.filename)
    knowledge_count = indexer.index_chunks(filename=doc.filename, chunks=rag_chunks)
    _report("knowledge", f"知识库索引完成: {knowledge_count} chunks")
    return memory_count, knowledge_count
