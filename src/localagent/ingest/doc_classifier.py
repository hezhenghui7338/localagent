"""Document type classification for structured profile compilation."""

from __future__ import annotations

import re
from enum import Enum


class DocType(str, Enum):
    RESUME = "resume"
    NOTES = "notes"
    GENERAL = "general"


_RESUME_NAME_MARKERS = re.compile(r"(简历|resume|cv|curriculum)", re.I)
_RESUME_HEADINGS = re.compile(
    r"(工作经历|工作经验|项目经验|教育背景|个人简介|求职意向|技术栈|skills|experience|education)",
    re.I,
)


def classify_document(*, filename: str, text: str, title: str = "") -> DocType:
    """Heuristic document classification; no LLM required."""
    name = filename or ""
    if _RESUME_NAME_MARKERS.search(name):
        return DocType.RESUME

    probe = f"{title}\n{text[:4000]}"
    heading_hits = len(_RESUME_HEADINGS.findall(probe))
    if heading_hits >= 2:
        return DocType.RESUME
    if re.search(r"<h1[^>]*>[\u4e00-\u9fff]{2,6}</h1>", probe, re.I):
        if heading_hits >= 1:
            return DocType.RESUME

    if re.search(r"(^|\n)#+\s*(笔记|notes|journal|diary)", probe, re.I):
        return DocType.NOTES
    return DocType.GENERAL


def extract_html_title(text: str) -> str:
    match = re.search(r"<title[^>]*>([^<]+)</title>", text, re.I)
    return match.group(1).strip() if match else ""
