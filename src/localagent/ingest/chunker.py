"""Unified document chunking for summarize reading, RAG indexing, and Warm sections."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_PAGE_HEADING_RE = re.compile(r"(?m)^##\s+\[p\.(\d+)\]")

# Legacy module constants (defaults; env overrides via config at runtime).
SECTION_TARGET_CHARS = 1500
SECTION_MAX_CHARS = 4000

_PROVIDER_READING_DEFAULTS: dict[str, tuple[int, int]] = {
    "ollama": (1000, 1200),
    "cursor": (3500, 4200),
}
_DEFAULT_READING = (3000, 3600)
_MIN_CHUNK_RATIO = 0.6
_HARD_MAX_RATIO = 1.2
_CONTINUATION_SUFFIX_RE = re.compile(r"（续\d+）+$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？])\s+|(?<=[.!?])\s+")


class ChunkMode(str, Enum):
    READING = "reading"
    RAG = "rag"
    SECTION = "section"


@dataclass(frozen=True)
class ChunkBudget:
    target_chars: int
    hard_max: int
    overlap: int = 0
    min_merge: int = 0
    prior_budget: int = 0
    threshold_chars: int = 0


@dataclass
class TextChunk:
    chunk_id: str
    heading: str
    text: str
    start_line: int
    index: int
    metadata: dict = field(default_factory=dict)


def _detect_heading(line: str) -> tuple[int, str] | None:
    match = _HEADING_RE.match(line.rstrip())
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def _la_recursive_rules():
    from chonkie import RecursiveLevel, RecursiveRules

    return RecursiveRules(
        [
            RecursiveLevel(delimiters=["\n## [p.", "\n## [§", "\n# ", "\n## "]),
            RecursiveLevel(delimiters=["\n\n"]),
            RecursiveLevel(delimiters=["。", "！", "？", ". ", "! ", "? "]),
            RecursiveLevel(delimiters=None, whitespace=True),
        ]
    )


def _continuation_base_title(title: str) -> str:
    return _CONTINUATION_SUFFIX_RE.sub("", title).strip()


def _min_chunk_chars(target: int) -> int:
    return max(1, int(target * _MIN_CHUNK_RATIO))


def _split_at_whitespace(text: str, hard_max: int) -> list[str]:
    """Last-resort split for a single unit that exceeds hard_max."""
    text = text.strip()
    if len(text) <= hard_max:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + hard_max, len(text))
        if end < len(text):
            space = text.rfind(" ", start, end)
            if space > start:
                end = space
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = end if end > start else start + hard_max
    return chunks or [text[:hard_max]]


def _split_paragraph_by_sentences(para: str, *, target: int, hard_max: int) -> list[str]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(para) if s.strip()]
    if not sentences:
        return [para]

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= target:
            current = candidate
        elif not current:
            if len(sentence) > hard_max:
                chunks.extend(_split_at_whitespace(sentence, hard_max))
                current = ""
            else:
                current = sentence
        else:
            chunks.append(current)
            if len(sentence) > hard_max:
                chunks.extend(_split_at_whitespace(sentence, hard_max))
                current = ""
            else:
                current = sentence
    if current:
        chunks.append(current)
    return chunks


def _pack_semantic(text: str, *, target: int, hard_max: int) -> list[str]:
    """Greedy semantic packing: paragraphs first, then sentences."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= hard_max:
        return [text]

    paragraphs = re.split(r"\n\n+", text)
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(para) > hard_max:
            if current:
                chunks.append(current)
                current = ""
            for sub in _split_paragraph_by_sentences(para, target=target, hard_max=hard_max):
                if len(sub) > hard_max:
                    chunks.extend(_split_at_whitespace(sub, hard_max))
                elif len(sub) > target:
                    chunks.append(sub)
                else:
                    candidate = f"{current}\n\n{sub}".strip() if current else sub
                    if current and len(candidate) <= target:
                        current = candidate
                    elif current:
                        chunks.append(current)
                        current = sub
                    else:
                        current = sub
            continue

        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= target:
            current = candidate
        elif not current:
            current = para
        else:
            chunks.append(current)
            current = para

    if current:
        chunks.append(current)
    return chunks


def _rebalance_tail(chunks: list[str], *, target: int, hard_max: int) -> list[str]:
    """Move content from the previous chunk into a tiny tail when merge would overflow."""
    min_chars = _min_chunk_chars(target)
    if len(chunks) < 2 or len(chunks[-1]) >= min_chars:
        return chunks

    prev = chunks[-2]
    tail = chunks[-1]
    combined = f"{prev}\n\n{tail}"
    if len(combined) <= hard_max:
        return chunks[:-2] + [combined]

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(prev) if s.strip()]
    if len(sentences) <= 1:
        return chunks

    while sentences and len(tail) < min_chars:
        sentence = sentences.pop()
        new_tail = f"{sentence} {tail}".strip() if tail else sentence
        new_prev = " ".join(sentences).strip()
        if new_prev and len(new_prev) < min_chars:
            sentences.append(sentence)
            break
        tail = new_tail
        prev = new_prev

    if len(tail) < min_chars:
        return chunks

    result = chunks[:-2]
    if prev:
        result.append(prev)
    result.append(tail)
    return result


def _merge_small_chunks(chunks: list[str], *, target: int, hard_max: int) -> list[str]:
    if not chunks:
        return []

    min_chars = _min_chunk_chars(target)
    merged: list[str] = [chunks[0]]
    for piece in chunks[1:]:
        piece = piece.strip()
        if not piece:
            continue
        prev = merged[-1]
        combined = f"{prev}\n\n{piece}"
        if len(piece) < min_chars and len(combined) <= hard_max:
            merged[-1] = combined
        elif len(prev) < min_chars and len(combined) <= hard_max:
            merged[-1] = combined
        else:
            merged.append(piece)

    return _rebalance_tail(merged, target=target, hard_max=hard_max)


def _normalize_chunk_sizes(pieces: list[str], *, target: int, hard_max: int) -> list[str]:
    expanded: list[str] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) > hard_max:
            expanded.extend(_pack_semantic(piece, target=target, hard_max=hard_max))
        else:
            expanded.append(piece)

    if not expanded:
        return []

    merged = _merge_small_chunks(expanded, target=target, hard_max=hard_max)
    final: list[str] = []
    for piece in merged:
        if len(piece) > hard_max:
            final.extend(_pack_semantic(piece, target=target, hard_max=hard_max))
        else:
            final.append(piece)
    return _merge_small_chunks(final, target=target, hard_max=hard_max)


def _split_semantic(text: str, *, target: int, hard_max: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= hard_max:
        return _normalize_chunk_sizes([text], target=target, hard_max=hard_max)
    return _normalize_chunk_sizes(
        _pack_semantic(text, target=target, hard_max=hard_max),
        target=target,
        hard_max=hard_max,
    )


def _get_recursive_chunker(*, chunk_size: int):
    from chonkie import RecursiveChunker

    return RecursiveChunker(
        tokenizer="character",
        chunk_size=max(chunk_size, 64),
        rules=_la_recursive_rules(),
        min_characters_per_chunk=24,
    )


def _chonkie_split_text(text: str, *, target: int, hard_max: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= hard_max:
        return _normalize_chunk_sizes([text], target=target, hard_max=hard_max)
    try:
        chunker = _get_recursive_chunker(chunk_size=target)
        raw = [c.text.strip() for c in chunker.chunk(text) if c.text.strip()]
        if not raw:
            return _split_semantic(text, target=target, hard_max=hard_max)
        return _normalize_chunk_sizes(raw, target=target, hard_max=hard_max)
    except Exception:
        return _split_semantic(text, target=target, hard_max=hard_max)


def _apply_rag_overlap(chunks: list[str], *, overlap: int) -> list[str]:
    if overlap <= 0 or len(chunks) <= 1:
        return chunks
    try:
        from chonkie import OverlapRefinery
        from chonkie.types import Chunk

        wrapped = [
            Chunk(text=t, start_index=0, end_index=len(t), token_count=len(t))
            for t in chunks
        ]
        refinery = OverlapRefinery(context_size=overlap, tokenizer="character")
        refined = refinery.refine(wrapped)
        return [c.text.strip() for c in refined if c.text.strip()]
    except Exception:
        return _native_rag_overlap(chunks, overlap=overlap)


def _native_rag_overlap(chunks: list[str], *, overlap: int) -> list[str]:
    if overlap <= 0 or len(chunks) <= 1:
        return chunks
    out: list[str] = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            out.append(chunk)
            continue
        prev_tail = chunks[i - 1][-overlap:]
        out.append((prev_tail + chunk).strip())
    return out


def _resolve_provider_name(provider: str) -> str:
    from localagent import config

    resolved = config.normalize_provider_choice(provider)
    if resolved != "auto":
        return resolved
    for name in config.MODEL_PROVIDER_PRIORITY:
        server = config.get_model_server(name)
        if server is not None:
            return name
    return "ollama"


def resolve_chunk_budget(*, mode: ChunkMode, provider: str = "auto") -> ChunkBudget:
    """Resolve chunk sizes for reading / RAG / section modes."""
    from localagent import config

    if mode == ChunkMode.RAG:
        size = config.RAG_CHUNK_SIZE
        overlap = config.RAG_CHUNK_OVERLAP
        return ChunkBudget(
            target_chars=size,
            hard_max=size,
            overlap=overlap,
            min_merge=0,
        )

    if mode == ChunkMode.SECTION:
        target = config.CHUNK_SECTION_TARGET
        hard_max = config.CHUNK_SECTION_MAX
        return ChunkBudget(
            target_chars=target,
            hard_max=hard_max,
            overlap=0,
            min_merge=max(400, target // 3),
        )

    # READING mode
    num_ctx = config.OLLAMA_NUM_CTX
    provider_name = _resolve_provider_name(provider)
    server = config.get_model_server(provider_name)
    if server is not None:
        num_ctx = server.num_ctx

    ctx_chars = max(num_ctx * 4, 4000)
    prior_budget = config.SUMMARIZE_PRIOR_BUDGET_CHARS or max(800, int(ctx_chars * 0.15))
    threshold = config.SUMMARIZE_SEGMENT_THRESHOLD_CHARS

    if config.SUMMARIZE_SEGMENT_TARGET_CHARS > 0:
        target = config.SUMMARIZE_SEGMENT_TARGET_CHARS
    elif server is not None and server.reading_target_chars > 0:
        target = server.reading_target_chars
    else:
        target = _PROVIDER_READING_DEFAULTS.get(provider_name, _DEFAULT_READING)[0]

    if server is not None and server.reading_max_chars > 0:
        hard_max = server.reading_max_chars
    elif config.SUMMARIZE_SEGMENT_TARGET_CHARS > 0:
        hard_max = max(target, int(target * _HARD_MAX_RATIO))
    else:
        hard_max = _PROVIDER_READING_DEFAULTS.get(provider_name, _DEFAULT_READING)[1]

    hard_max = max(hard_max, target)
    min_merge = max(400, target // 3)
    return ChunkBudget(
        target_chars=target,
        hard_max=hard_max,
        overlap=0,
        min_merge=min_merge,
        prior_budget=prior_budget,
        threshold_chars=threshold,
    )


def _split_by_pdf_pages(text: str) -> list[tuple[str, str]]:
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
    return parts


def _extract_structural_parts(content: str, *, filename: str) -> list[tuple[str, str]]:
    """Split annotated text into (heading, body) structural parts."""
    text = (content or "").strip()
    if not text:
        return []

    pdf_parts = _split_by_pdf_pages(text)
    if pdf_parts:
        return pdf_parts

    sections = split_into_sections(text, filename=filename)
    if not sections:
        return [("## [§全文]", text)]

    parts: list[tuple[str, str]] = []
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
        parts.append((heading, combined))
    return parts


def _merge_short_sections(
    parts: list[tuple[str, str]],
    *,
    min_merge: int,
    target_chars: int,
    hard_max: int,
) -> list[tuple[str, str]]:
    merged: list[tuple[str, str]] = []
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
        if len(combined) <= hard_max:
            merged.append((title, combined))
        else:
            base_title = _continuation_base_title(title)
            for k, sub in enumerate(
                _chonkie_split_text(combined, target=target_chars, hard_max=hard_max)
            ):
                sub_title = base_title if k == 0 else f"{base_title}（续{k + 1}）"
                merged.append((sub_title, sub))
        i = j
    return merged


def _line_number_at(content: str, char_index: int) -> int:
    if char_index <= 0:
        return 1
    return content[:char_index].count("\n") + 1


def _make_chunk_id(*, filename: str, heading: str, start_line: int, text_len: int, suffix: str = "") -> str:
    base = hashlib.sha256(
        f"{filename}\x00{heading}\x00{start_line}\x00{text_len}{suffix}".encode()
    ).hexdigest()[:12]
    return base


def chunk_document(
    content: str,
    *,
    filename: str = "<unknown>",
    mode: ChunkMode = ChunkMode.SECTION,
    provider: str = "auto",
    budget: ChunkBudget | None = None,
) -> list[TextChunk]:
    """Unified chunking entry for reading, RAG, and section modes."""
    text = (content or "").strip()
    if not text:
        return []

    resolved = budget or resolve_chunk_budget(mode=mode, provider=provider)
    parts = _extract_structural_parts(text, filename=filename)

    if mode == ChunkMode.READING:
        merged = _merge_short_sections(
            parts,
            min_merge=resolved.min_merge,
            target_chars=resolved.target_chars,
            hard_max=resolved.hard_max,
        )
        chunks: list[TextChunk] = []
        for idx, (heading, body) in enumerate(merged):
            body = body.strip()
            if not body:
                continue
            start_line = _line_number_at(text, text.find(body[: min(80, len(body))]))
            chunks.append(
                TextChunk(
                    chunk_id=_make_chunk_id(
                        filename=filename,
                        heading=heading,
                        start_line=start_line,
                        text_len=len(body),
                    ),
                    heading=heading.lstrip("# ").strip(),
                    text=body,
                    start_line=start_line,
                    index=idx,
                    metadata={"mode": mode.value},
                )
            )
        return chunks

    if mode == ChunkMode.RAG:
        rag_chunks: list[TextChunk] = []
        rag_index = 0
        for section in split_into_sections(text, filename=filename):
            section_text = section.text.strip()
            if not section_text:
                continue
            if len(section_text) <= resolved.target_chars:
                pieces = [section_text]
            else:
                pieces = _chonkie_split_text(
                    section_text,
                    target=resolved.target_chars,
                    hard_max=resolved.target_chars,
                )
            pieces = _apply_rag_overlap(pieces, overlap=resolved.overlap)
            for i, piece in enumerate(pieces):
                piece = piece.strip()
                if not piece:
                    continue
                chunk_id = f"{section.chunk_id}-rag-{i:03d}"
                rag_chunks.append(
                    TextChunk(
                        chunk_id=chunk_id,
                        heading=section.heading,
                        text=piece,
                        start_line=section.start_line,
                        index=rag_index,
                        metadata={
                            "section_chunk_id": section.chunk_id,
                            "rag_part": i,
                            "mode": mode.value,
                        },
                    )
                )
                rag_index += 1
        return rag_chunks

    # SECTION mode — heading-aware sections for Warm memory
    return split_into_sections(
        text,
        filename=filename,
        target_chars=resolved.target_chars,
        hard_max=resolved.hard_max,
    )


def split_into_sections(
    content: str,
    *,
    filename: str = "<unknown>",
    target_chars: int | None = None,
    hard_max: int | None = None,
) -> list[TextChunk]:
    target = target_chars if target_chars is not None else SECTION_TARGET_CHARS
    max_chars = hard_max if hard_max is not None else SECTION_MAX_CHARS

    lines = content.splitlines()
    if not lines:
        return []

    raw: list[dict] = []
    current: dict | None = None
    for idx, line in enumerate(lines, start=1):
        heading = _detect_heading(line)
        if heading:
            if current is not None:
                current["end_line"] = idx - 1
                current["content"] = "\n".join(lines[current["_start_idx"] : idx - 1])
                raw.append(current)
            level, _title = heading
            current = {
                "heading": line.rstrip(),
                "level": level,
                "start_line": idx,
                "end_line": idx,
                "_start_idx": idx - 1,
            }
    if current is not None:
        current["end_line"] = len(lines)
        current["content"] = "\n".join(lines[current["_start_idx"] :])
        raw.append(current)

    if not raw:
        if not content.strip():
            return []
        raw = [
            {
                "heading": "(全文)",
                "level": 0,
                "start_line": 1,
                "end_line": len(lines),
                "_start_idx": 0,
                "content": content,
            }
        ]

    first = raw[0]
    if first["start_line"] > 1:
        preamble_lines = lines[: first["start_line"] - 1]
        preamble_text = "\n".join(preamble_lines).strip()
        if preamble_text:
            raw.insert(
                0,
                {
                    "heading": "(前言)",
                    "level": 0,
                    "start_line": 1,
                    "end_line": first["start_line"] - 1,
                    "_start_idx": 0,
                    "content": preamble_text,
                },
            )

    chunks: list[TextChunk] = []
    chunk_index = 0
    for section in raw:
        section_text = section["content"]
        sub_texts = (
            _chonkie_split_text(section_text, target=target, hard_max=max_chars)
            if len(section_text) > max_chars
            else [section_text]
        )
        parent_heading = section["heading"]
        base_heading = _continuation_base_title(parent_heading)
        for i, sub_text in enumerate(sub_texts):
            heading = base_heading if i == 0 else f"{base_heading}（续{i + 1}）"
            start_line = section["start_line"] + sum(s.count("\n") for s in sub_texts[:i])
            chunk_id = _make_chunk_id(
                filename=filename,
                heading=heading,
                start_line=start_line,
                text_len=len(sub_text),
            )
            chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    heading=heading,
                    text=sub_text.strip(),
                    start_line=start_line,
                    index=chunk_index,
                    metadata={"level": section["level"]},
                )
            )
            chunk_index += 1
    return [c for c in chunks if c.text]


def chunk_for_rag(
    content: str,
    *,
    filename: str,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[TextChunk]:
    """Smaller overlapping chunks for knowledge retrieval (deprecated alias)."""
    budget = ChunkBudget(
        target_chars=chunk_size,
        hard_max=chunk_size,
        overlap=overlap,
    )
    return chunk_document(content, filename=filename, mode=ChunkMode.RAG, budget=budget)
