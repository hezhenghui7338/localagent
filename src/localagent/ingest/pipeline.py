"""Shared ingest pipeline: load → chunk → Cold RAG → optional Warm summaries."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from localagent import config
from localagent.audit.events import log_event
from localagent.audit.security import is_sensitive_path, sensitive_path_reason
from localagent.ingest.chunker import chunk_for_rag, split_into_sections
from localagent.ingest.loader import LoadedDoc, load_file
from localagent.ingest.progress import ProgressEvent, ProgressReporter
from localagent.ingest.sync_index import content_hash, get_sync_index
from localagent.knowledge.indexer import get_knowledge_indexer


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
    knowledge_chunk_count: int = 0
    content_hash: str = ""
    error: str = ""
    memory_fact_count: int = 0

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
    """Index a file into Cold RAG and optionally write Warm summary memories."""
    path = Path(path).resolve()
    filename = path.name

    def _report(phase: str, message: str, current: int = 0, total: int = 0) -> None:
        if reporter is not None:
            reporter.update(ProgressEvent(phase=phase, message=message, current=current, total=total))

    if is_sensitive_path(path):
        reason = sensitive_path_reason(path)
        log_event(
            "kb.blocked",
            policy_id="kb.sensitive_path",
            action="block",
            path=str(path),
            reason=reason,
        )
        log_event(
            "guardrail.triggered",
            policy_id="kb.sensitive_path",
            action="block",
            path=str(path),
            reason=reason,
        )
        _report("fail", reason)
        return IngestResult(
            filename=filename,
            path=str(path),
            status=IngestStatus.FAILED,
            error=reason,
        )

    _report("load", f"加载文件 {filename}")
    try:
        doc = load_file(path)
    except Exception as exc:
        _report("fail", str(exc))
        return IngestResult(
            filename=filename,
            path=str(path),
            status=IngestStatus.FAILED,
            error=str(exc),
        )
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
        _report("skip", "文件未变更，跳过索引")
        return IngestResult(
            filename=filename,
            path=str(path),
            status=IngestStatus.SKIPPED,
            knowledge_chunk_count=record.knowledge_chunk_count if record else 0,
            memory_fact_count=record.memory_fact_count if record else 0,
            content_hash=file_hash,
        )

    previous = sync_index.get(filename)
    status = IngestStatus.NEW if previous is None else IngestStatus.UPDATED

    try:
        knowledge_count = _index_document(doc, reporter=reporter)
        memory_count = _retain_warm_summaries(doc, reporter=reporter)
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

    _report("save", "写入 sync_index")
    sync_index.upsert(
        filename,
        path=str(path),
        current_hash=file_hash,
        memory_fact_count=memory_count,
        knowledge_chunk_count=knowledge_count,
    )
    sync_index.save()

    _report("done", f"完成: facts={memory_count} chunks={knowledge_count}")
    return IngestResult(
        filename=filename,
        path=str(path),
        status=status,
        knowledge_chunk_count=knowledge_count,
        memory_fact_count=memory_count,
        content_hash=file_hash,
    )


def _index_document(doc: LoadedDoc, *, reporter: ProgressReporter | None = None) -> int:
    def _report(phase: str, message: str, current: int = 0, total: int = 0) -> None:
        if reporter is not None:
            reporter.update(ProgressEvent(phase=phase, message=message, current=current, total=total))

    indexer = get_knowledge_indexer()
    _report("knowledge", "构建知识库向量与 BM25 索引")
    rag_chunks = chunk_for_rag(doc.text, filename=doc.filename)
    knowledge_count = indexer.index_chunks(filename=doc.filename, chunks=rag_chunks)
    _report("knowledge", f"知识库索引完成: {knowledge_count} chunks")
    return knowledge_count


def _retain_warm_summaries(doc: LoadedDoc, *, reporter: ProgressReporter | None = None) -> int:
    """Write document/section summary facts into Warm memory."""
    if not config.INGEST_WARM_SUMMARY:
        return 0

    def _report(phase: str, message: str, current: int = 0, total: int = 0) -> None:
        if reporter is not None:
            reporter.update(ProgressEvent(phase=phase, message=message, current=current, total=total))

    from localagent.memory.backend import get_memory_backend
    from localagent.memory.summarize import build_document_summary_facts

    _report("summarize", "生成 Warm 摘要记忆")
    sections = split_into_sections(doc.text, filename=doc.filename)
    facts = build_document_summary_facts(doc.text, filename=doc.filename, sections=sections)
    if not facts:
        _report("summarize", "无需摘要（文本较短或已关闭）")
        return 0

    backend = get_memory_backend()
    saved = 0
    total = len(facts)
    for index, item in enumerate(facts, start=1):
        fact_id = backend.retain(str(item["text"]), metadata=dict(item.get("metadata") or {}))
        if fact_id:
            saved += 1
        _report("summarize", f"摘要入库 {index}/{total}", current=index, total=total)
    _report("summarize", f"Warm 摘要完成: {saved} facts")
    return saved
