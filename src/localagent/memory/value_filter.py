"""Value filter: reject low-value text before memory retain."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, TypeVar

from localagent import config

if TYPE_CHECKING:
    from localagent.memory.conversation_extract import ExtractedMemory

_LOW_VALUE_PATTERNS = [
    re.compile(r"^(好的|嗯|哦|ok|yes|no|谢谢|收到)[\s。!！?？]*$", re.I),
    re.compile(r"^[\s\d\W]+$"),
    re.compile(r"^(哈哈|呵呵|lol)+$", re.I),
]

# Keyword soup: short tokens joined by Chinese/ASCII semicolons or pipes
_KEYWORD_SOUP = re.compile(
    r"^[\w\u4e00-\u9fff]{1,12}([；;|｜/／][\w\u4e00-\u9fff]{1,12}){1,}$"
)

_MIN_CHARS = 6
_MIN_NARRATIVE_CHARS = 8

_T = TypeVar("_T")

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

# Ephemeral chat: keep in conversation persist only — never Warm session_summary.
_EPHEMERAL_TURN = [
    re.compile(r"天气"),
    re.compile(r"(新闻|资讯|热点|头条)"),
    re.compile(r"^(你好|您好|hi|hello|hey|在吗|早|晚安)[\s。.!！?？]*$", re.I),
    re.compile(r"^我是谁[\s。.!！?？]*$"),
    re.compile(r"^(你是谁|你叫什么)[\s。.!！?？]*$", re.I),
    re.compile(r"^(几点了|现在几点|今天几号|今天星期几)[\s。.!！?？]*$"),
    re.compile(r"^(测试|test|ping)[\s。.!！?？\d]*$", re.I),
    re.compile(r"^(谢谢|感谢|thanks|thx|谢谢你|多谢)[\s。.!！?？]*$", re.I),
    re.compile(r"^(好的|嗯嗯|行|可以|收到|明白了|知道了|ok)[\s。.!！?？]*$", re.I),
    re.compile(r"^(继续|接着说|然后呢|还有吗)[\s。.!！?？]*$", re.I),
]

# Meta / tool chatter that should never become Warm facts.
_META_CHATTER = [
    re.compile(r"^(请|麻烦)?(帮我)?(再)?(搜|查|搜索|google)", re.I),
    re.compile(r"^(忽略|忘掉|不要记住|别记)(上面|刚才|这个)?", re.I),
    re.compile(r"do not remember|don'?t remember|forget (that|this)", re.I),
]

# Durable signals: personal facts/preferences worth a Warm bridge summary.
_DURABLE_MARKERS = (
    "决定",
    "计划",
    "打算",
    "偏好",
    "习惯",
    "喜欢",
    "不喜欢",
    "住在",
    "住址",
    "工作",
    "职业",
    "公司",
    "项目",
    "目标",
    "正在做",
    "已经",
    "完成",
    "学会",
    "擅长",
    "生日",
    "家人",
    "孩子",
    "老婆",
    "老公",
    "男朋友",
    "女朋友",
    "记得",
    "记住",
    "以后都",
    "从今",
    "改用",
    "采用",
    "放弃",
    "选择",
)

_MIN_SESSION_SUMMARY_CHARS = 16


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
    return [f for f in facts if is_narrative_memory(f)]


def is_narrative_memory(text: str) -> bool:
    """Reject keyword fragments / outline soup; require a usable narrative clause."""
    text = text.strip()
    if not is_valuable(text):
        return False
    if len(text) < _MIN_NARRATIVE_CHARS:
        return False
    if any(pat.search(text) for pat in _META_CHATTER):
        return False
    if _is_ephemeral_turn(text) and len(text) < 40:
        return False
    # Pure keyword soup with separators and no sentence punctuation
    compact = re.sub(r"\s+", "", text)
    if _KEYWORD_SOUP.match(compact) and not re.search(r"[。！？.!?]", text):
        return False
    # High separator density with very short segments
    seps = len(re.findall(r"[；;|｜]", text))
    if seps >= 2 and not re.search(r"[。！？.!?]", text):
        parts = [p for p in re.split(r"[；;|｜]", text) if p.strip()]
        if parts and all(len(p.strip()) <= 12 for p in parts):
            return False
    return True


def filter_memory_candidates(memories: list[ExtractedMemory]) -> list[ExtractedMemory]:
    """Keep ExtractedMemory items whose text passes the narrative quality gate."""
    return [m for m in memories if is_narrative_memory(m.text)]


def _is_ephemeral_turn(text: str) -> bool:
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return True
    if not is_valuable(cleaned):
        return True
    return any(pat.search(cleaned) for pat in _EPHEMERAL_TURN)


def is_warm_worthy_session(user_texts: list[str]) -> bool:
    """Whether a chat session deserves a Warm-layer session_summary.

    Conversation transcripts always stay in persist/; Warm only gets durable
    personal/project substance — not weather, news, or identity probes.
    """
    turns = [" ".join((t or "").split()).strip() for t in user_texts]
    turns = [t for t in turns if t]
    if not turns:
        return False

    if all(_is_ephemeral_turn(t) for t in turns):
        return False

    combined = "\n".join(turns)
    if len(combined) < _MIN_SESSION_SUMMARY_CHARS:
        return False
    if not is_narrative_memory(combined):
        return False
    if any(marker in combined for marker in _DURABLE_MARKERS):
        return True
    # Multi-turn substance without durable markers still stays out of Warm;
    # fact extraction may retain specific facts separately.
    return False
