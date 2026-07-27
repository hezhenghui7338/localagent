"""Segmented reading for long document summarize sessions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from localagent import config
from localagent.context.compress.core import apply_context_budget
from localagent.ingest.chunker import split_into_sections

if TYPE_CHECKING:
    from localagent.summarize.document import SummarizeResult

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
    compressed_prior: str = ""
    segment_statuses: list[str] = field(default_factory=list)
    prefetch_enabled: bool = True
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
        elif prev_status == "done" and status != "done":
            self.sync_done_count()

    def init_statuses(self) -> None:
        self.segment_statuses = ["pending"] * self.total
        for idx in range(self.total):
            if idx < len(self.segment_summaries) and self.segment_summaries[idx].strip():
                self.segment_statuses[idx] = "done"
        if self.total and self.summary_ready(0):
            self.segment_statuses[0] = "done"
        self.sync_done_count()

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

    def to_session_dict(self) -> dict:
        return {
            "current_index": self.current_index,
            "segment_summaries": list(self.segment_summaries),
            "compressed_prior": self.compressed_prior,
            "segment_statuses": list(self.segment_statuses),
            "prefetch_enabled": self.prefetch_enabled,
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
        budget = resolve_reading_budget(provider)
        segments = build_segments(
            annotated_text,
            target_chars=budget.segment_target,
            segment_max=budget.segment_max,
            filename=filename,
        )
        summaries = list(data.get("segment_summaries") or [])
        raw_statuses = data.get("segment_statuses")
        statuses: list[str] = []
        if isinstance(raw_statuses, list):
            statuses = [str(item) for item in raw_statuses]
        progress = cls(
            segments=segments,
            current_index=max(0, min(int(data.get("current_index") or 0), max(len(segments) - 1, 0))),
            segment_summaries=summaries,
            compressed_prior=str(data.get("compressed_prior") or ""),
            segment_statuses=statuses,
            prefetch_enabled=bool(data.get("prefetch_enabled", True)),
        )
        if not progress.segment_statuses:
            progress.init_statuses()
        else:
            while len(progress.segment_statuses) < progress.total:
                progress.segment_statuses.append("pending")
            for idx in range(progress.total):
                if progress.summary_ready(idx):
                    progress.segment_statuses[idx] = "done"
        progress.sync_done_count()
        return progress


def resolve_reading_budget(provider: str = "auto") -> ReadingBudget:
    """Derive segment sizes from model context window (chars heuristic)."""
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
    segment_target = config.SUMMARIZE_SEGMENT_TARGET_CHARS or max(1500, int(ctx_chars * 0.25))
    prior_budget = config.SUMMARIZE_PRIOR_BUDGET_CHARS or max(800, int(ctx_chars * 0.15))
    threshold = config.SUMMARIZE_SEGMENT_THRESHOLD_CHARS
    segment_max = max(segment_target, int(segment_target * 1.6))
    return ReadingBudget(
        ctx_chars=ctx_chars,
        segment_target=segment_target,
        segment_max=segment_max,
        prior_budget=prior_budget,
        threshold_chars=threshold,
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


def _split_by_pdf_pages(text: str, *, target_chars: int, segment_max: int) -> list[tuple[str, str]]:
    """Split PDF annotated text by page headings when no md sections exist."""
    matches = list(_PAGE_HEADING_RE.finditer(text))
    if len(matches) < 2:
        return []

    parts: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunk = text[start:end].strip()
        if not chunk:
            continue
        page_num = match.group(1)
        heading = f"## [p.{page_num}]"
        parts.append((heading, chunk))
    return _merge_and_split_parts(parts, target_chars=target_chars, segment_max=segment_max)


def _merge_and_split_parts(
    parts: list[tuple[str, str]],
    *,
    target_chars: int,
    segment_max: int,
) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
    min_merge = max(400, target_chars // 3)
    i = 0
    while i < len(parts):
        heading, body = parts[i]
        combined = body
        headings = [heading]
        j = i + 1
        while j < len(parts) and len(combined) < min_merge:
            combined = combined + "\n\n" + parts[j][1]
            headings.append(parts[j][0])
            j += 1
        if len(headings) == 1:
            title = headings[0]
        else:
            title = f"{headings[0]} … {headings[-1]}"
        if len(combined) <= segment_max:
            merged.append((title, combined))
        else:
            from localagent.ingest.chunker import _split_chunk_by_chars

            for k, sub in enumerate(_split_chunk_by_chars(combined, target_chars, segment_max)):
                sub_title = title if k == 0 else f"{title}（续{k + 1}）"
                merged.append((sub_title, sub))
        i = j
    return merged


def build_segments(
    annotated_text: str,
    *,
    target_chars: int,
    segment_max: int,
    filename: str = "",
) -> list[DocumentSegment]:
    """Split annotated document text into semantically coherent reading segments."""
    text = (annotated_text or "").strip()
    if not text:
        return []

    raw_parts: list[tuple[str, str]] = []
    pdf_parts = _split_by_pdf_pages(text, target_chars=target_chars, segment_max=segment_max)
    if pdf_parts:
        raw_parts = pdf_parts
    else:
        sections = split_into_sections(text, filename=filename or "<doc>")
        if not sections:
            raw_parts = [("## [§全文]", text)]
        else:
            for section in sections:
                heading = section.heading
                if not heading.startswith("#"):
                    marker = heading if heading.startswith("[") else f"[§{heading.lstrip('# ').strip()}]"
                    heading = f"## {marker}" if not marker.startswith("##") else marker
                body = section.text.strip()
                if body.startswith(section.heading):
                    lines = body.splitlines()
                    body = "\n".join(lines[1:]).strip()
                combined = f"{heading}\n{body}".strip() if body else heading
                raw_parts.append((heading, combined))

    merged = _merge_and_split_parts(raw_parts, target_chars=target_chars, segment_max=segment_max)
    segments: list[DocumentSegment] = []
    for idx, (heading, body) in enumerate(merged):
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


def _llm_compress_prior(text: str, *, filename: str, budget: int) -> str | None:
    try:
        from localagent.models.router import ChatMessage, get_model_router
    except Exception:
        return None
    prompt = (
        "将下列已读文档各段摘要压缩为 3～5 句滚动摘要，保留章节/页码索引标记，"
        "只输出 Markdown 段落，不要前言。\n\n"
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


def summarize_segment(
    seg: DocumentSegment,
    *,
    filename: str,
    use_llm: bool = True,
) -> str:
    """Generate a skim card for one document segment."""
    from localagent.summarize.document import (
        _heuristic_summary,
        _llm_summarize,
        ensure_citations,
    )

    annotated = seg.text
    markdown: str | None = None
    if use_llm:
        markdown = _llm_summarize(annotated, filename=filename)
    if not markdown:
        markdown = _heuristic_summary(annotated, filename=filename)
    markdown, _warnings = ensure_citations(markdown)
    return markdown


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
    use_llm: bool = True,
    refresh_cache: bool = False,
) -> tuple[ReadingProgress, "SegmentCacheLoad | None"]:
    from localagent.summarize.segment_cache import (
        SegmentCacheLoad,
        apply_cache_to_progress,
        cache_paths,
        load_segment_cache,
        save_segment_cache,
    )

    budget = resolve_reading_budget(provider)
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
            return progress, cache_info

    first_summary = summarize_segment(segments[0], filename=filename, use_llm=use_llm)
    progress = ReadingProgress(
        segments=segments,
        current_index=0,
        segment_summaries=[first_summary],
        compressed_prior="",
    )
    progress.init_statuses()
    if resolved is not None:
        save_segment_cache(
            resolved,
            progress,
            filename=filename,
            char_count=count,
            budget=budget,
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
    use_llm: bool = True,
    sync_if_missing: bool = False,
) -> DocumentSegment | None:
    """Move to next segment; optionally sync-summarize when prefetch is off."""
    if progress.current_index >= len(progress.segments) - 1:
        return None
    next_idx = progress.current_index + 1
    if not progress.summary_ready(next_idx):
        if sync_if_missing:
            while len(progress.segment_summaries) <= next_idx:
                progress.segment_summaries.append("")
            progress.segment_summaries[next_idx] = summarize_segment(
                progress.segments[next_idx],
                filename=filename,
                use_llm=use_llm,
            )
            while len(progress.segment_statuses) <= next_idx:
                progress.segment_statuses.append("pending")
            progress.set_segment_status(next_idx, "done")
        else:
            return None
    progress.current_index = next_idx
    refresh_compressed_prior(progress, provider=provider)
    return progress.current


def goto_segment(
    progress: ReadingProgress,
    index: int,
    *,
    filename: str = "",
    provider: str = "auto",
    use_llm: bool = True,
    sync_if_missing: bool = False,
) -> DocumentSegment | None:
    """Jump to segment index (0-based); returns None if not ready and not syncing."""
    target = max(0, min(index, len(progress.segments) - 1))
    if not progress.summary_ready(target):
        if sync_if_missing:
            while len(progress.segment_summaries) <= target:
                progress.segment_summaries.append("")
            progress.segment_summaries[target] = summarize_segment(
                progress.segments[target],
                filename=filename,
                use_llm=use_llm,
            )
            while len(progress.segment_statuses) <= target:
                progress.segment_statuses.append("pending")
            progress.set_segment_status(target, "done")
        else:
            return None
    progress.current_index = target
    refresh_compressed_prior(progress, provider=provider)
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
