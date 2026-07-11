"""Value filter: reject low-value text before memory retain."""

from __future__ import annotations

import re

from localagent import config

_LOW_VALUE_PATTERNS = [
    re.compile(r"^(好的|嗯|哦|ok|yes|no|谢谢|收到)[\s。!！?？]*$", re.I),
    re.compile(r"^[\s\d\W]+$"),
    re.compile(r"^(哈哈|呵呵|lol)+$", re.I),
]

_MIN_CHARS = 6

_MEMORY_HEADING_KEYWORDS = (
    "日记",
    "计划",
    "决定",
    "笔记",
    "反思",
    "总结",
    "目标",
    "备忘",
    "记录",
    "心得",
    "想法",
    "经验",
    "学习",
    "工作",
    "todo",
    "journal",
    "diary",
    "log",
    "note",
    "notes",
    "plan",
    "goals",
)

_PERSONAL_MARKERS = (
    "我",
    "我们",
    "决定",
    "计划",
    "今天",
    "昨天",
    "感到",
    "想要",
    "打算",
    "认为",
    "觉得",
    "偏好",
    "习惯",
    "经历",
    "喜欢",
    "不喜欢",
    "擅长",
    "正在",
    "已经",
    "完成",
)

_SHORT_SECTION_CHARS = 500


def is_valuable(text: str) -> bool:
    text = text.strip()
    if len(text) < _MIN_CHARS:
        return False
    for pat in _LOW_VALUE_PATTERNS:
        if pat.match(text):
            return False
    # Must contain some substantive content
    if len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text)) < 4:
        return False
    return True


def _is_code_heavy(text: str) -> bool:
    return text.count("```") >= 2 or bool(re.search(r"^\s{4}\S", text, re.M))


def _is_list_heavy(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 4:
        return False
    list_lines = sum(
        1 for line in lines if re.match(r"^([-*•]|\d+[.)])\s+", line)
    )
    return list_lines / len(lines) >= 0.6


def should_retain_as_memory(text: str, *, heading: str = "") -> bool:
    """Crude heuristic: keep personal/short sections as memory; long docs go to RAG."""
    if not is_valuable(text):
        return False

    heading_lower = heading.lower()
    has_memory_heading = any(kw in heading_lower for kw in _MEMORY_HEADING_KEYWORDS)
    has_personal = any(marker in text for marker in _PERSONAL_MARKERS)

    if has_memory_heading or has_personal:
        return len(text) <= config.INGEST_MEMORY_MAX_SECTION_CHARS

    if _is_code_heavy(text) or _is_list_heavy(text):
        return (has_memory_heading or has_personal) and len(text) <= config.INGEST_MEMORY_MAX_SECTION_CHARS

    if len(text) > config.INGEST_MEMORY_MAX_SECTION_CHARS:
        return False

    return len(text) <= _SHORT_SECTION_CHARS


def filter_facts(facts: list[str]) -> list[str]:
    return [f for f in facts if is_valuable(f)]
