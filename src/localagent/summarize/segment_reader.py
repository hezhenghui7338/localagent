"""Segmented reading for long document summarize sessions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from localagent import config
from localagent.context.compress.core import apply_context_budget
from localagent.ingest.chunker import ChunkMode, chunk_document, resolve_chunk_budget

if TYPE_CHECKING:
    from localagent.summarize.document import SummarizeResult
    from localagent.summarize.translate import TranslateConfig
    from localagent.summarize.model_choice import SummarizeModelChoice, SegmentSource

_PAGE_HEADING_RE = re.compile(r"(?m)^##\s+\[p\.(\d+)\]")
_SECTION_HEADING_RE = re.compile(r"(?m)^##\s+\[(§[^\]]+)\]")
_HEADING_SUM = re.compile(r"^##\s*总结")
_HEADING_POINTS = re.compile(r"^##\s*结构化要点")
_CROSS_SEGMENT_RE = re.compile(
    r"(全文|整篇|总共|整体|对比|比较|之前|前面|后面|后面|其它段|其他段|"
    r"跨段|所有段|每一节|各节|第\s*\d+\s*[章节条款页段])",
    re.IGNORECASE,
)

SegmentStatus = str  # pending | running | done | failed


@dataclass(frozen=True)
class DocumentSegment:
    index: int
    heading: str
    text: str
    char_count: int
    cite_range: str


@dataclass
class ReadingBudget:
    ctx_chars: int
    segment_target: int
    segment_max: int
    prior_budget: int
    threshold_chars: int


@dataclass
class ReadingProgress:
    segments: list[DocumentSegment]
    current_index: int = 0
    segment_summaries: list[str] = field(default_factory=list)
    segment_sources: list["SegmentSource | None"] = field(default_factory=list)
    compressed_prior: str = ""
    segment_statuses: list[str] = field(default_factory=list)
    prefetch_enabled: bool = True
    book_context: str = ""
    book_context_done_count: int = -1
    _done_count: int = field(default=0, repr=False)

    @property
    def total(self) -> int:
        return len(self.segments)

    @property
    def current(self) -> DocumentSegment:
        return self.segments[self.current_index]

    def segment_status_at(self, index: int) -> str:
        if index < 0 or index >= self.total:
            return "pending"
        if index < len(self.segment_statuses):
            return self.segment_statuses[index] or "pending"
        return "pending"

    def summary_ready(self, index: int) -> bool:
        if index < 0 or index >= self.total:
            return False
        if self.segment_status_at(index) == "done":
            return True
        if index < len(self.segment_summaries) and self.segment_summaries[index].strip():
            return True
        return False

    def done_count(self) -> int:
        return self._done_count

    def sync_done_count(self) -> int:
        self._done_count = sum(1 for i in range(self.total) if self.summary_ready(i))
        return self._done_count

    def set_segment_status(self, index: int, status: str) -> None:
        while len(self.segment_statuses) < self.total:
            self.segment_statuses.append("pending")
        if index < 0 or index >= self.total:
            return
        prev_status = self.segment_status_at(index)
        self.segment_statuses[index] = status
        if status == "done" and prev_status != "done":
            self._done_count += 1
            self.invalidate_book_context()
        elif prev_status == "done" and status != "done":
            self.sync_done_count()
            self.invalidate_book_context()

    def init_statuses(self) -> None:
        self.segment_statuses = ["pending"] * self.total
        for idx in range(self.total):
            if idx < len(self.segment_summaries) and self.segment_summaries[idx].strip():
                self.segment_statuses[idx] = "done"
        if self.total and self.summary_ready(0):
            self.segment_statuses[0] = "done"
        self.sync_done_count()

    def failed_count(self) -> int:
        return sum(
            1 for i in range(self.total) if self.segment_status_at(i) == "failed"
        )

    def select_segment(self, index: int, *, provider: str = "auto") -> DocumentSegment:
        self.current_index = max(0, min(index, self.total - 1))
        refresh_compressed_prior(self, provider=provider)
        return self.current

    def next_ready_index(self, after: int | None = None) -> int | None:
        start = (after if after is not None else self.current_index) + 1
        for idx in range(start, self.total):
            if self.summary_ready(idx):
                return idx
        return None

    def current_summary(self) -> str:
        idx = self.current_index
        if 0 <= idx < len(self.segment_summaries):
            return self.segment_summaries[idx]
        return ""

    def invalidate_book_context(self) -> None:
        self.book_context = ""
        self.book_context_done_count = -1

    def to_session_dict(self) -> dict:
        return {
            "current_index": self.current_index,
            "segment_summaries": list(self.segment_summaries),
            "segment_sources": [
                item.to_dict() if item is not None else None for item in self.segment_sources
            ],
            "compressed_prior": self.compressed_prior,
            "segment_statuses": list(self.segment_statuses),
            "prefetch_enabled": self.prefetch_enabled,
            "book_context": self.book_context,
            "book_context_done_count": self.book_context_done_count,
        }

    @classmethod
    def from_session_dict(
        cls,
        data: dict,
        *,
        annotated_text: str,
        filename: str,
        provider: str = "auto",
    ) -> ReadingProgress:
        from localagent.summarize.model_choice import SegmentSource

        budget = resolve_reading_budget(provider)
        segments = build_segments(
            annotated_text,
            target_chars=budget.segment_target,
            segment_max=budget.segment_max,
            filename=filename,
        )
        summaries = list(data.get("segment_summaries") or [])
        raw_sources = data.get("segment_sources")
        sources: list[SegmentSource | None] = []
        if isinstance(raw_sources, list):
            for item in raw_sources:
                if item is None:
                    sources.append(None)
                else:
                    sources.append(SegmentSource.from_dict(item))
        raw_statuses = data.get("segment_statuses")
        statuses: list[str] = []
        if isinstance(raw_statuses, list):
            statuses = [str(item) for item in raw_statuses]
        progress = cls(
            segments=segments,
            current_index=max(0, min(int(data.get("current_index") or 0), max(len(segments) - 1, 0))),
            segment_summaries=summaries,
            segment_sources=sources,
            compressed_prior=str(data.get("compressed_prior") or ""),
            segment_statuses=statuses,
            prefetch_enabled=bool(data.get("prefetch_enabled", True)),
            book_context=str(data.get("book_context") or ""),
            book_context_done_count=int(data.get("book_context_done_count") or -1),
        )
        if not progress.segment_statuses:
            progress.init_statuses()
        else:
            while len(progress.segment_statuses) < progress.total:
                progress.segment_statuses.append("pending")
            for idx in range(progress.total):
                if progress.summary_ready(idx):
                    progress.segment_statuses[idx] = "done"
        normalize_stale_running_segments(progress)
        progress.sync_done_count()
        return progress


def resolve_reading_budget(provider: str = "auto") -> ReadingBudget:
    """Derive segment sizes from provider-aware chunk budget."""
    budget = resolve_chunk_budget(mode=ChunkMode.READING, provider=provider)
    num_ctx = config.OLLAMA_NUM_CTX
    resolved = config.normalize_provider_choice(provider)
    if resolved != "auto":
        server = config.get_model_server(resolved)
        if server is not None:
            num_ctx = server.num_ctx
    else:
        for name in config.MODEL_PROVIDER_PRIORITY:
            server = config.get_model_server(name)
            if server is not None:
                num_ctx = server.num_ctx
                break
    ctx_chars = max(num_ctx * 4, 4000)
    return ReadingBudget(
        ctx_chars=ctx_chars,
        segment_target=budget.target_chars,
        segment_max=budget.hard_max,
        prior_budget=budget.prior_budget,
        threshold_chars=budget.threshold_chars,
    )


def should_use_segment_mode(char_count: int, *, provider: str = "auto") -> bool:
    budget = resolve_reading_budget(provider)
    return char_count > budget.threshold_chars


def _extract_cite_range(heading: str, text: str) -> str:
    pages = [int(m.group(1)) for m in _PAGE_HEADING_RE.finditer(text)]
    if not pages:
        pages = [int(m.group(1)) for m in re.finditer(r"\[p\.(\d+)\]", text)]
    if pages:
        lo, hi = min(pages), max(pages)
        return f"p.{lo}" if lo == hi else f"p.{lo}-{hi}"
    section = _SECTION_HEADING_RE.search(heading) or _SECTION_HEADING_RE.search(text)
    if section:
        return section.group(1)
    title = heading.lstrip("# ").strip()
    if title.startswith("[") and title.endswith("]"):
        inner = title[1:-1]
        return inner if inner.startswith(("§", "p.")) else f"§{inner}"
    if title.startswith(("§", "p.")):
        return title
    return title or "§段"


def build_segments(
    annotated_text: str,
    *,
    target_chars: int,
    segment_max: int,
    filename: str = "",
    provider: str = "auto",
) -> list[DocumentSegment]:
    """Split annotated document text into semantically coherent reading segments."""
    from localagent.ingest.chunker import ChunkBudget

    text = (annotated_text or "").strip()
    if not text:
        return []

    budget = ChunkBudget(
        target_chars=target_chars,
        hard_max=segment_max,
        min_merge=max(400, target_chars // 3),
    )
    chunks = chunk_document(
        text,
        filename=filename or "<doc>",
        mode=ChunkMode.READING,
        provider=provider,
        budget=budget,
    )
    segments: list[DocumentSegment] = []
    for idx, chunk in enumerate(chunks):
        heading = chunk.heading
        body = chunk.text
        cite = _extract_cite_range(heading, body)
        segments.append(
            DocumentSegment(
                index=idx,
                heading=heading.lstrip("# ").strip(),
                text=body,
                char_count=len(body),
                cite_range=cite,
            )
        )
    return segments


def _extract_summary_sections(markdown: str) -> str:
    """Keep only 总结 + 结构化要点 for prior compression."""
    lines = markdown.splitlines()
    out: list[str] = []
    mode: str | None = None
    for line in lines:
        if _HEADING_SUM.match(line):
            mode = "sum"
            out.append(line)
            continue
        if _HEADING_POINTS.match(line):
            mode = "points"
            out.append(line)
            continue
        if line.startswith("## "):
            mode = None
            continue
        if mode and line.strip():
            out.append(line)
    return "\n".join(out).strip()


def compress_prior_summaries(
    summaries: list[str],
    segments: list[DocumentSegment],
    *,
    budget: int,
    filename: str = "",
) -> str:
    """Compress already-read segment summaries into a rolling prior block."""
    if not summaries:
        return ""
    parts: list[str] = []
    for idx, summary in enumerate(summaries):
        if not summary.strip():
            continue
        seg = segments[idx] if idx < len(segments) else None
        label = seg.heading if seg else f"段 {idx + 1}"
        cite = seg.cite_range if seg else ""
        excerpt = _extract_summary_sections(summary) or summary.strip()
        parts.append(f"### 段 {idx + 1} · {label} 〔{cite}〕\n{excerpt}")

    blob = "\n\n".join(parts)
    compressed = apply_context_budget(blob, budget=budget, label="已读段摘要")

    if config.SUMMARIZE_SEGMENT_LLM_COMPRESS and (
        len(summaries) > 5 or len(compressed) >= budget
    ):
        llm = _llm_compress_prior(compressed, filename=filename, budget=budget)
        if llm:
            return llm
    return compressed


def _llm_compress_prior(
    text: str,
    *,
    filename: str,
    budget: int,
    prompt_prefix: str | None = None,
) -> str | None:
    try:
        from localagent.models.router import ChatMessage, get_model_router
    except Exception:
        return None
    prefix = prompt_prefix or "将下列已读文档各段摘要压缩为 3～5 句滚动摘要，保留章节/页码索引标记"
    prompt = (
        f"{prefix}，只输出 Markdown 段落，不要前言。\n\n"
        f"文件: {filename}\n\n{text[: budget * 2]}"
    )
    try:
        reply = get_model_router().chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.2,
            usage_command="summarize",
        )
    except Exception:
        return None
    out = (reply or "").strip()
    if not out:
        return None
    return apply_context_budget(out, budget=budget, label="已读段滚动摘要")


def is_stale_running(progress: ReadingProgress, index: int) -> bool:
    """Segment marked running in cache but no worker is summarizing it."""
    return (
        progress.segment_status_at(index) == "running"
        and not progress.summary_ready(index)
    )


def normalize_stale_running_segments(progress: ReadingProgress) -> list[int]:
    """Convert orphaned running segments to pending (e.g. after interrupted prefetch)."""
    normalized: list[int] = []
    for idx in range(progress.total):
        if is_stale_running(progress, idx):
            progress.set_segment_status(idx, "pending")
            normalized.append(idx)
    return normalized


def reset_segment_for_retry(progress: ReadingProgress, index: int) -> bool:
    """Clear one segment summary and mark pending; skip active running with summary."""
    if index < 0 or index >= progress.total:
        return False
    status = progress.segment_status_at(index)
    if status == "running" and progress.summary_ready(index):
        return False
    if status not in {"failed", "pending"} and not is_stale_running(progress, index):
        return False
    while len(progress.segment_summaries) <= index:
        progress.segment_summaries.append("")
    while len(progress.segment_sources) <= index:
        progress.segment_sources.append(None)
    progress.segment_summaries[index] = ""
    progress.segment_sources[index] = None
    progress.set_segment_status(index, "pending")
    return True


def reset_failed_segments(progress: ReadingProgress) -> list[int]:
    """Reset failed and stale-running segments for retry; returns reset indices."""
    reset: list[int] = []
    for idx in range(progress.total):
        status = progress.segment_status_at(idx)
        if status == "failed" or is_stale_running(progress, idx):
            if reset_segment_for_retry(progress, idx):
                reset.append(idx)
    return reset


def can_manual_retry_segment(
    progress: ReadingProgress,
    index: int,
    *,
    prefetch_enabled: bool,
) -> bool:
    """Whether TUI manual retry (R) should be offered for this segment."""
    status = progress.segment_status_at(index)
    if status == "failed":
        return True
    if is_stale_running(progress, index):
        return True
    if status == "pending" and not prefetch_enabled:
        return True
    return False


def set_segment_summary(
    progress: ReadingProgress,
    index: int,
    markdown: str,
    source: SegmentSource,
) -> None:
    while len(progress.segment_summaries) <= index:
        progress.segment_summaries.append("")
    while len(progress.segment_sources) <= index:
        progress.segment_sources.append(None)
    progress.segment_summaries[index] = markdown
    progress.segment_sources[index] = source


def summarize_segment(
    seg: DocumentSegment,
    *,
    filename: str,
    use_llm: bool = True,
    translate: TranslateConfig | None = None,
    model_choice: SummarizeModelChoice | None = None,
) -> tuple[str, SegmentSource]:
    """Generate a skim card for one document segment."""
    from localagent.summarize.document import (
        _heuristic_summary,
        _llm_summarize,
        _prepare_for_summarize,
        ensure_citations,
    )
    from localagent.summarize.model_choice import (
        SummarizeModelChoice,
        SegmentSource,
        append_source_footer,
    )

    prep, _, _ = _prepare_for_summarize(seg.text, translate)
    if use_llm:
        llm_text, llm_source = _llm_summarize(
            prep,
            filename=filename,
            translate=None,
            model_choice=model_choice,
        )
        if not llm_text:
            return "", SegmentSource(via="failed")
        markdown = llm_text
        source = llm_source or SegmentSource(via="llm")
    else:
        markdown = _heuristic_summary(prep, filename=filename)
        source = SegmentSource(via="heuristic")
    markdown, _warnings = ensure_citations(markdown)
    markdown = append_source_footer(markdown, source)
    return markdown, source


def needs_cross_segment_rag(user_input: str) -> bool:
    """Detect queries that likely need retrieval outside the current segment."""
    text = (user_input or "").strip()
    if not text:
        return False
    return bool(_CROSS_SEGMENT_RE.search(text))


def init_reading_progress(
    annotated_text: str,
    *,
    filename: str,
    source_path: Path | None = None,
    char_count: int | None = None,
    provider: str = "auto",
    model_choice: SummarizeModelChoice | None = None,
    use_llm: bool = True,
    refresh_cache: bool = False,
    retry_failed: bool = False,
    translate: TranslateConfig | None = None,
) -> tuple[ReadingProgress, "SegmentCacheLoad | None"]:
    from localagent.summarize.model_choice import SummarizeModelChoice
    from localagent.summarize.segment_cache import (
        SegmentCacheLoad,
        apply_cache_to_progress,
        cache_paths,
        load_segment_cache,
        save_segment_cache,
    )

    choice = model_choice or SummarizeModelChoice.from_cli(provider=provider)
    budget = resolve_reading_budget(choice.provider)
    segments = build_segments(
        annotated_text,
        target_chars=budget.segment_target,
        segment_max=budget.segment_max,
        filename=filename,
    )
    if not segments:
        raise ValueError("无法分段：文档为空")
    resolved = source_path.expanduser().resolve() if source_path else None
    count = char_count if char_count is not None else len(annotated_text)
    cache_info: SegmentCacheLoad | None = None

    if resolved is not None and not refresh_cache:
        cached = load_segment_cache(
            resolved,
            total_segments=len(segments),
            char_count=count,
            budget=budget,
            translate=translate,
            model_choice=choice,
        )
        if cached is not None:
            progress = ReadingProgress(
                segments=segments,
                current_index=0,
                segment_summaries=[],
                compressed_prior="",
            )
            done = apply_cache_to_progress(progress, cached)
            _, md_path = cache_paths(resolved)
            cache_info = SegmentCacheLoad(
                loaded=True,
                done_count=done,
                total=progress.total,
                md_path=md_path,
            )
            if retry_failed:
                reset = reset_failed_segments(progress)
                if reset:
                    save_segment_cache(
                        resolved,
                        progress,
                        filename=filename,
                        char_count=count,
                        budget=budget,
                        translate=translate,
                        model_choice=choice,
                    )
                    cache_info = SegmentCacheLoad(
                        loaded=True,
                        done_count=progress.done_count(),
                        total=progress.total,
                        md_path=md_path,
                        retry_reset_count=len(reset),
                    )
                    return progress, cache_info
            return progress, cache_info

    first_summary, first_source = summarize_segment(
        segments[0],
        filename=filename,
        use_llm=use_llm,
        translate=translate,
        model_choice=choice,
    )
    progress = ReadingProgress(
        segments=segments,
        current_index=0,
        segment_summaries=[first_summary],
        segment_sources=[first_source],
        compressed_prior="",
    )
    progress.init_statuses()
    if use_llm and not first_summary.strip():
        progress.set_segment_status(0, "failed")
    if resolved is not None:
        save_segment_cache(
            resolved,
            progress,
            filename=filename,
            char_count=count,
            budget=budget,
            translate=translate,
            model_choice=choice,
        )
    return progress, cache_info


def refresh_compressed_prior(progress: ReadingProgress, *, provider: str = "auto") -> str:
    budget = resolve_reading_budget(provider)
    prior_summaries = progress.segment_summaries[: progress.current_index]
    progress.compressed_prior = compress_prior_summaries(
        prior_summaries,
        progress.segments,
        budget=budget.prior_budget,
    )
    return progress.compressed_prior


def advance_segment(
    progress: ReadingProgress,
    *,
    filename: str = "",
    provider: str = "auto",
    model_choice: SummarizeModelChoice | None = None,
    use_llm: bool = True,
    sync_if_missing: bool = False,
    translate: TranslateConfig | None = None,
) -> DocumentSegment | None:
    """Move to next segment; optionally sync-summarize when prefetch is off."""
    from localagent.summarize.model_choice import SummarizeModelChoice

    choice = model_choice or SummarizeModelChoice.from_cli(provider=provider)
    if progress.current_index >= len(progress.segments) - 1:
        return None
    next_idx = progress.current_index + 1
    if not progress.summary_ready(next_idx):
        if sync_if_missing:
            summary, source = summarize_segment(
                progress.segments[next_idx],
                filename=filename,
                use_llm=use_llm,
                translate=translate,
                model_choice=choice,
            )
            set_segment_summary(progress, next_idx, summary, source)
            while len(progress.segment_statuses) <= next_idx:
                progress.segment_statuses.append("pending")
            progress.set_segment_status(next_idx, "done")
        else:
            return None
    progress.current_index = next_idx
    refresh_compressed_prior(progress, provider=choice.provider)
    return progress.current


def goto_segment(
    progress: ReadingProgress,
    index: int,
    *,
    filename: str = "",
    provider: str = "auto",
    model_choice: SummarizeModelChoice | None = None,
    use_llm: bool = True,
    sync_if_missing: bool = False,
    translate: TranslateConfig | None = None,
) -> DocumentSegment | None:
    """Jump to segment index (0-based); returns None if not ready and not syncing."""
    from localagent.summarize.model_choice import SummarizeModelChoice

    choice = model_choice or SummarizeModelChoice.from_cli(provider=provider)
    target = max(0, min(index, len(progress.segments) - 1))
    if not progress.summary_ready(target):
        if sync_if_missing:
            summary, source = summarize_segment(
                progress.segments[target],
                filename=filename,
                use_llm=use_llm,
                translate=translate,
                model_choice=choice,
            )
            set_segment_summary(progress, target, summary, source)
            while len(progress.segment_statuses) <= target:
                progress.segment_statuses.append("pending")
            progress.set_segment_status(target, "done")
        else:
            return None
    progress.current_index = target
    refresh_compressed_prior(progress, provider=choice.provider)
    return progress.current


def prev_segment(progress: ReadingProgress, *, provider: str = "auto") -> DocumentSegment | None:
    if progress.current_index <= 0:
        return None
    progress.current_index -= 1
    refresh_compressed_prior(progress, provider=provider)
    return progress.current


def format_segment_context(
    result: SummarizeResult,
    progress: ReadingProgress,
    *,
    retrieval_block: str = "",
    max_body_chars: int | None = None,
) -> str:
    """Build system-prompt block for segment-mode document chat."""
    budget = resolve_reading_budget("auto")
    limit = max_body_chars if max_body_chars is not None else budget.segment_max
    seg = progress.current
    body = seg.text.strip()
    if len(body) > limit:
        body = body[: limit - 1] + "…"

    kept_line = (
        f"已入库 → {result.keep_target}"
        if result.kept and result.keep_target
        else "未入库（默认；用户明确要求时可用会话内 /keep）"
    )
    rules = (
        "规则: 你已在文档逐段阅读对话中，优先依据「当前段原文」与「当前段速读卡」回答；"
        "已读段仅见压缩摘要；跨段问题可参考 RAG 补充块；"
        "禁止建议用户再运行 la summarize；用户说入库时用 /keep；"
        "引用时用 〔§…|p.…〕；依据不足时如实说明，禁止编造。"
    )
    parts = [
        "[当前文档 · 逐段阅读（请优先当前段；引用时用 〔§…|p.…〕）]",
        f"文件: {result.path}",
        f"进度: 第 {progress.current_index + 1}/{progress.total} 段 · {seg.heading} · 约 {seg.char_count} 字",
        f"索引: {seg.cite_range}",
        f"入库状态: {kept_line}",
    ]
    if result.session_source_key:
        parts.append(f"会话索引: {result.session_source_key}")
    parts.extend([rules, ""])
    if progress.compressed_prior.strip():
        parts.extend(["## 已读段压缩摘要", progress.compressed_prior.strip(), ""])
    parts.extend(
        [
            "## 当前段速读卡",
            progress.current_summary().strip() or "（暂无）",
            "",
            "## 当前段原文（含索引标记）",
            body or "（无正文）",
        ]
    )
    if retrieval_block.strip():
        parts.extend(["", "## RAG 补充检索", retrieval_block.strip()])
    return "\n".join(parts)


def resolve_book_context_budget(provider: str = "auto") -> int:
    """Character budget for full-book chat context."""
    if config.SUMMARIZE_BOOK_CONTEXT_BUDGET_CHARS > 0:
        return config.SUMMARIZE_BOOK_CONTEXT_BUDGET_CHARS
    budget = resolve_reading_budget(provider)
    return max(budget.prior_budget * 2, int(budget.ctx_chars * 0.25))


def _book_llm_compress_enabled() -> bool:
    if config.SUMMARIZE_BOOK_LLM_COMPRESS is not None:
        return bool(config.SUMMARIZE_BOOK_LLM_COMPRESS)
    return bool(config.SUMMARIZE_SEGMENT_LLM_COMPRESS)


def _group_ready_indices_by_budget(
    progress: ReadingProgress,
    *,
    group_budget: int,
) -> list[list[int]]:
    """Group consecutive ready segment indices by approximate char budget."""
    groups: list[list[int]] = []
    current: list[int] = []
    current_chars = 0
    for idx in range(progress.total):
        if not progress.summary_ready(idx):
            continue
        summary = ""
        if idx < len(progress.segment_summaries):
            summary = progress.segment_summaries[idx]
        chunk_len = len(_extract_summary_sections(summary) or summary.strip())
        if current and current_chars + chunk_len > group_budget:
            groups.append(current)
            current = []
            current_chars = 0
        current.append(idx)
        current_chars += chunk_len
    if current:
        groups.append(current)
    return groups


def _compress_summary_group(
    progress: ReadingProgress,
    indices: list[int],
    *,
    budget: int,
    filename: str,
    label: str,
) -> str:
    summaries = [
        progress.segment_summaries[idx]
        for idx in indices
        if idx < len(progress.segment_summaries)
    ]
    segments = [progress.segments[idx] for idx in indices if idx < len(progress.segments)]
    compressed = compress_prior_summaries(
        summaries,
        segments,
        budget=budget,
        filename=filename,
    )
    if _book_llm_compress_enabled() and len(compressed) >= budget:
        llm = _llm_compress_prior(
            compressed,
            filename=filename,
            budget=budget,
            prompt_prefix=f"将下列文档「{label}」各段摘要压缩为 3～5 句概要",
        )
        if llm:
            return llm
    return compressed


def build_book_context(
    progress: ReadingProgress,
    *,
    budget: int | None = None,
    filename: str = "",
    provider: str = "auto",
) -> str:
    """Build hierarchical compressed context from all ready segment summaries."""
    done = progress.sync_done_count()
    if done <= 0:
        return ""

    if (
        progress.book_context.strip()
        and progress.book_context_done_count == done
    ):
        return progress.book_context

    limit = budget if budget is not None else resolve_book_context_budget(provider)
    ready_indices = [idx for idx in range(progress.total) if progress.summary_ready(idx)]
    if not ready_indices:
        return ""

    summaries = [progress.segment_summaries[idx] for idx in ready_indices]
    segments = [progress.segments[idx] for idx in ready_indices]

    flat = compress_prior_summaries(
        summaries,
        segments,
        budget=limit,
        filename=filename,
    )
    need_hierarchical = (
        len(ready_indices) >= config.SUMMARIZE_BOOK_GROUP_MIN
        or len(flat) >= limit
    )

    if need_hierarchical:
        group_budget = max(400, limit // 4)
        groups = _group_ready_indices_by_budget(progress, group_budget=group_budget)
        meta_parts: list[str] = []
        per_group = max(200, limit // max(1, len(groups)))
        for group_idx, group in enumerate(groups, start=1):
            lo = group[0] + 1
            hi = group[-1] + 1
            label = f"第 {lo}-{hi} 段" if lo != hi else f"第 {lo} 段"
            meta_parts.append(
                _compress_summary_group(
                    progress,
                    group,
                    budget=per_group,
                    filename=filename,
                    label=label,
                )
            )
        outline_blob = "\n\n".join(
            f"### 部分 {idx} · {part[:80].splitlines()[0] if part else ''}\n{part}"
            for idx, part in enumerate(meta_parts, start=1)
            if part.strip()
        )
        outline = apply_context_budget(
            outline_blob,
            budget=max(200, limit // 2),
            label="全书概要",
        )
        if _book_llm_compress_enabled() and len(outline) >= limit // 2:
            llm = _llm_compress_prior(
                outline,
                filename=filename,
                budget=limit // 2,
                prompt_prefix="将下列文档各部分概要进一步压缩为全书 5～8 句总览",
            )
            if llm:
                outline = llm
        index_part = compress_prior_summaries(
            summaries,
            segments,
            budget=max(200, limit // 2),
            filename=filename,
        )
        body = "\n\n".join(
            [
                "## 全书概要（分层压缩）",
                outline.strip() or "（暂无）",
                "",
                "## 各段摘要索引",
                index_part.strip() or "（暂无）",
            ]
        )
    else:
        body = flat

    header = f"## 全书阅读进度\n已完成 {done}/{progress.total} 段摘要"
    if done < progress.total:
        header += f"（尚有 {progress.total - done} 段摘要生成中）"

    result = f"{header}\n\n{body}".strip()
    progress.book_context = result
    progress.book_context_done_count = done
    return result


def format_book_context(
    result: SummarizeResult,
    progress: ReadingProgress,
    *,
    retrieval_block: str = "",
    provider: str = "auto",
) -> str:
    """Build system-prompt block for full-book chat grounded on segment summaries."""
    kept_line = (
        f"已入库 → {result.keep_target}"
        if result.kept and result.keep_target
        else "未入库（默认；用户明确要求时可用会话内 /keep）"
    )
    rules = (
        "规则: 你已在全书对话中，优先依据下方各段摘要回答全书/跨章问题；"
        "细节不足时参考 RAG 补充块；禁止建议用户再运行 la summarize；"
        "用户说入库时用 /keep；引用时用 〔§…|p.…〕；依据不足时如实说明，禁止编造。"
    )
    book_block = build_book_context(
        progress,
        filename=result.filename,
        provider=provider,
    )
    parts = [
        "[当前文档 · 全书对话（请优先各段摘要；引用时用 〔§…|p.…〕）]",
        f"文件: {result.path}",
        f"入库状态: {kept_line}",
    ]
    if result.session_source_key:
        parts.append(f"会话索引: {result.session_source_key}")
    parts.extend([rules, ""])
    if book_block.strip():
        parts.append(book_block.strip())
    else:
        parts.append("（暂无段摘要，请稍候后台摘要完成）")
    if retrieval_block.strip():
        parts.extend(["", "## RAG 补充检索", retrieval_block.strip()])
    return "\n".join(parts)
