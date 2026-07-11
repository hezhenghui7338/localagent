"""Markdown-aware chunking for memory and knowledge indexing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")

SECTION_TARGET_CHARS = 1500
SECTION_MAX_CHARS = 4000


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


def _split_chunk_by_chars(text: str, target: int, hard_max: int) -> list[str]:
    if len(text) <= hard_max:
        return [text]

    blocks = [b for b in text.split("\n\n")]
    chunks: list[str] = []
    current = ""

    for block in blocks:
        candidate = (current + "\n\n" + block) if current else block
        if len(candidate) <= target:
            current = candidate
        elif not current:
            chunks.append(block)
            current = ""
        else:
            chunks.append(current)
            current = block
    if current:
        chunks.append(current)

    final: list[str] = []
    for chunk in chunks:
        if len(chunk) <= hard_max:
            final.append(chunk)
            continue
        for i in range(0, len(chunk), hard_max):
            final.append(chunk[i : i + hard_max])
    return final


def split_into_sections(content: str, *, filename: str = "<unknown>") -> list[TextChunk]:
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
        text = section["content"]
        sub_texts = (
            _split_chunk_by_chars(text, SECTION_TARGET_CHARS, SECTION_MAX_CHARS)
            if len(text) > SECTION_MAX_CHARS
            else [text]
        )
        parent_heading = section["heading"]
        for i, sub_text in enumerate(sub_texts):
            heading = parent_heading if i == 0 else f"{parent_heading}（续{i + 1}）"
            start_line = section["start_line"] + sum(s.count("\n") for s in sub_texts[:i])
            chunk_id = hashlib.sha256(
                f"{filename}\x00{heading}\x00{start_line}\x00{len(sub_text)}".encode()
            ).hexdigest()[:12]
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


def chunk_for_rag(content: str, *, filename: str, chunk_size: int = 512, overlap: int = 64) -> list[TextChunk]:
    """Smaller overlapping chunks for knowledge retrieval."""
    sections = split_into_sections(content, filename=filename)
    if not sections:
        return []

    rag_chunks: list[TextChunk] = []
    rag_index = 0
    for section in sections:
        text = section.text
        if len(text) <= chunk_size:
            pieces = [text]
        else:
            pieces = []
            start = 0
            while start < len(text):
                end = min(start + chunk_size, len(text))
                pieces.append(text[start:end])
                if end >= len(text):
                    break
                start = max(end - overlap, start + 1)

        for i, piece in enumerate(pieces):
            chunk_id = f"{section.chunk_id}-rag-{i:03d}"
            rag_chunks.append(
                TextChunk(
                    chunk_id=chunk_id,
                    heading=section.heading,
                    text=piece.strip(),
                    start_line=section.start_line,
                    index=rag_index,
                    metadata={"section_chunk_id": section.chunk_id, "rag_part": i},
                )
            )
            rag_index += 1
    return [c for c in rag_chunks if c.text]
