"""Memory enrichment at write time (title, tags, summary).

Inspired by Mem0 (categories + structured extraction).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from localagent import config

_TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "偏好": ("喜欢", "偏好", "习惯", "不喜欢", "讨厌", "倾向"),
    "工作": ("工作", "公司", "项目", "职业", "团队", "同事", "老板", "职场"),
    "技术": ("编程", "代码", "AI", "模型", "框架", "算法", "开发", "技术", "软件"),
    "计划": ("计划", "打算", "目标", "下周", "明年", "准备", "安排"),
    "家庭": ("孩子", "儿子", "女儿", "家人", "父母", "老婆", "丈夫", "家庭"),
    "健康": ("锻炼", "睡眠", "身体", "健康", "运动", "饮食", "早睡"),
    "学习": ("学习", "读书", "课程", "考试", "钻研", "研究"),
    "财务": ("投资", "理财", "收入", "花钱", "预算", "财务"),
    "决策": ("决定", "选择", "采用", "使用", "放弃", "转向"),
}

_MEMORY_TYPES = ("preference", "fact", "plan", "experience", "observation")


@dataclass
class MemoryEnrichment:
    title: str
    summary: str
    tags: list[str] = field(default_factory=list)
    memory_type: str = "fact"
    searchable_text: str = ""

    def to_metadata(self, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "title": self.title,
            "summary": self.summary,
            "tags": self.tags,
            "type": self.memory_type,
        }
        if extra:
            meta.update(extra)
        return meta


_GENERIC_HEADINGS = frozenset({
    "direct",
    "manual",
    "manual_add",
    "chat",
    "unknown",
})


def _clean_heading(heading: str) -> str:
    text = heading.strip()
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"\s*（续\d+）\s*$", "", text)
    text = re.sub(r"^\(前言\)\s*", "", text)
    text = text.strip()
    if text.lower() in _GENERIC_HEADINGS:
        return ""
    return text


def _first_sentence(text: str, *, max_len: int = 28) -> str:
    text = text.strip()
    # Do not strip leading digits — they are often part of dates like "2026年3月".
    text = re.sub(r"^[\s。；，、\-•.]+", "", text)
    for sep in ("。", "；", "！", "？", "\n", "，"):
        idx = text.find(sep)
        if 4 <= idx <= max_len:
            text = text[:idx]
            break
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text.strip()


def _infer_tags(text: str, *, heading: str = "") -> list[str]:
    combined = f"{heading} {text}"
    tags: list[str] = []
    for tag, keywords in _TAG_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            tags.append(tag)
    return tags[:4]


def _infer_type(text: str, tags: list[str]) -> str:
    if "偏好" in tags or any(w in text for w in ("喜欢", "偏好", "习惯", "不喜欢")):
        return "preference"
    if "计划" in tags or any(w in text for w in ("计划", "打算", "目标", "下周")):
        return "plan"
    if any(w in text for w in ("决定", "选择", "采用", "使用")):
        return "fact"
    if any(w in text for w in ("感到", "觉得", "经历", "反思", "批评")):
        return "experience"
    return "fact"


def _heuristic_summary(text: str, *, max_len: int = 200) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    summary = _first_sentence(lines[0], max_len=max_len)
    if len(summary) < 40:
        for line in lines[1:3]:
            if len(summary) >= max_len:
                break
            snippet = _first_sentence(line, max_len=80)
            if snippet and snippet not in summary:
                summary = f"{summary}；{snippet}"
    if len(summary) > max_len:
        summary = summary[: max_len - 1] + "…"
    return summary


def enrich_heuristic(
    text: str,
    *,
    heading: str = "",
    context: str = "",
) -> MemoryEnrichment:
    """Fast local enrichment without LLM."""
    clean_heading = _clean_heading(heading)
    title = clean_heading or _first_sentence(text)
    if not title:
        title = (context or "未命名记忆")[:28]

    tags = _infer_tags(text, heading=clean_heading)
    memory_type = _infer_type(text, tags)
    summary = text.strip() if len(text.strip()) <= 200 else _heuristic_summary(text)

    return MemoryEnrichment(
        title=title,
        summary=summary,
        tags=tags,
        memory_type=memory_type,
        searchable_text=summary or text.strip(),
    )


def _parse_llm_enrichment(reply: str, *, fallback_text: str) -> MemoryEnrichment | None:
    raw = reply.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    title = str(data.get("title") or "").strip()
    summary = str(data.get("summary") or "").strip()
    tags_raw = data.get("tags") or []
    tags = [str(t).strip() for t in tags_raw if str(t).strip()][:4]
    memory_type = str(data.get("type") or "fact").strip().lower()
    if memory_type not in _MEMORY_TYPES:
        memory_type = "fact"

    if not title:
        title = _first_sentence(summary or fallback_text)
    if not summary:
        summary = _heuristic_summary(fallback_text)

    return MemoryEnrichment(
        title=title,
        summary=summary,
        tags=tags or _infer_tags(fallback_text),
        memory_type=memory_type,
        searchable_text=summary,
    )


def enrich_with_llm(
    text: str,
    *,
    heading: str = "",
    context: str = "",
) -> MemoryEnrichment | None:
    """LLM enrichment (Mem0-style single-pass structured extraction)."""
    from localagent.models.router import ChatMessage, get_model_router

    prompt = (
        "你是记忆整理助手。分析以下内容，输出 JSON（不要 markdown，不要解释）：\n"
        '{"title":"简短标题≤20字","tags":["标签1","标签2"],'
        '"summary":"一句话摘要≤120字",'
        '"type":"preference|fact|plan|experience|observation"}\n'
        "标签从以下选用：偏好、工作、技术、计划、家庭、健康、学习、财务、决策。\n"
    )
    if context:
        prompt += f"上下文: {context}\n"
    if heading:
        prompt += f"章节: {heading}\n"
    prompt += f"\n内容:\n{text[:3000]}"

    try:
        reply = get_model_router().chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.1,
            usage_command="memory_enrich",
        )
    except Exception:
        return None
    return _parse_llm_enrichment(reply, fallback_text=text)


def enrich_memory(
    text: str,
    *,
    heading: str = "",
    context: str = "",
    use_llm: bool | None = None,
) -> MemoryEnrichment:
    """Enrich memory content; LLM optional, heuristic always available as fallback."""
    text = text.strip()
    if not text:
        return MemoryEnrichment(title="空记忆", summary="", tags=[], searchable_text="")

    if use_llm is None:
        use_llm = config.MEMORY_ENRICH_USE_LLM

    if use_llm:
        llm_result = enrich_with_llm(text, heading=heading, context=context)
        if llm_result is not None:
            return llm_result

    return enrich_heuristic(text, heading=heading, context=context)
