"""Unified conversation memory extraction for LA chat and ChatGPT exports."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from localagent.memory.value_filter import filter_memory_candidates, is_narrative_memory
from localagent.persist.chatgpt import ChatGPTConversation, format_conversation_text


@dataclass
class ExtractedMemory:
    text: str
    slots: dict[str, str] = field(default_factory=dict)
    memory_type: str = "fact"
    tags: list[str] = field(default_factory=list)

    def to_metadata_extra(self) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if self.slots:
            extra["slots"] = {k: v for k, v in self.slots.items() if v}
        if self.memory_type:
            extra["type"] = self.memory_type
        if self.tags:
            extra["tags"] = self.tags[:2]
        return extra


_ALLOWED_TYPES = frozenset(
    {"preference", "fact", "plan", "experience", "decision", "observation"}
)


def conversation_extract_prompt(*, context: str = "") -> str:
    """Shared system-style instructions for conversation memory extraction."""
    parts = [
        "你是对话记忆提取助手。从对话中提取可长期记住的用户事实。",
        "规则：",
        "1. 以 user 发言为主事实源；assistant 仅作指代消解与语境，未明确被用户采纳的建议不要记为用户事实。",
        "2. 每条必须是可独立理解的完整叙事句（如「用户喜欢喝葡萄酒。」），禁止关键词串、大纲、分号拼接标签。",
        "3. 不编造时间/地点；不确定则省略对应槽位。",
        "4. 元命令、闲聊寒暄、无信息量内容跳过。",
        "5. 若无有价值记忆，输出空数组 []。",
        '输出纯 JSON 数组（不要 markdown）：'
        '[{"text":"完整叙事句","slots":{"subject":"用户","action":"","object":"","time":"","location":"","outcome":""},'
        '"type":"preference|fact|plan|experience|decision","tags":["标签"]}]',
        "tags 最多 2 个，从：偏好、工作、技术、计划、家庭、健康、学习、财务、决策。",
    ]
    if context:
        parts.append(f"上下文: {context}")
    return "\n".join(parts)


def parse_extracted_memories(reply: str) -> list[ExtractedMemory]:
    """Parse LLM reply into ExtractedMemory list; tolerant of fenced JSON / line fallback."""
    raw = (reply or "").strip()
    if not raw:
        return []
    if "NONE" in raw.upper() and len(raw) < 20:
        return []

    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    data: Any = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to locate a JSON array substring
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                data = None

    memories: list[ExtractedMemory] = []
    if isinstance(data, list):
        for item in data:
            mem = _item_to_memory(item)
            if mem is not None:
                memories.append(mem)
    elif isinstance(data, dict) and "text" in data:
        mem = _item_to_memory(data)
        if mem is not None:
            memories.append(mem)
    else:
        # Legacy line-based fallback
        for line in raw.splitlines():
            text = line.strip().lstrip("-• ").strip()
            if text and len(text) > 4 and is_narrative_memory(text):
                memories.append(ExtractedMemory(text=text))

    return filter_memory_candidates(memories)


def _item_to_memory(item: Any) -> ExtractedMemory | None:
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return ExtractedMemory(text=text)
    if not isinstance(item, dict):
        return None
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    slots_raw = item.get("slots") or {}
    slots: dict[str, str] = {}
    if isinstance(slots_raw, dict):
        for key in ("subject", "action", "object", "time", "location", "outcome"):
            val = str(slots_raw.get(key) or "").strip()
            if val:
                slots[key] = val
    memory_type = str(item.get("type") or "fact").strip().lower()
    if memory_type not in _ALLOWED_TYPES:
        memory_type = "fact"
    tags_raw = item.get("tags") or []
    tags = [str(t).strip() for t in tags_raw if str(t).strip()][:2]
    return ExtractedMemory(text=text, slots=slots, memory_type=memory_type, tags=tags)


def extract_from_conversation_text(
    text: str,
    *,
    context: str = "",
) -> list[ExtractedMemory]:
    """Run LLM extraction on already-formatted conversation text."""
    from localagent.models.router import get_model_router

    return get_model_router().extract_memories(text, context=context)


def extract_from_chatgpt_conversation(
    conversation: ChatGPTConversation,
    *,
    context: str = "",
) -> list[ExtractedMemory]:
    text = format_conversation_text(conversation)
    if not text.strip():
        return []
    ctx = context or f"conversation={conversation.conversation_id}"
    return extract_from_conversation_text(text, context=ctx)


def memories_to_fact_texts(memories: list[ExtractedMemory]) -> list[str]:
    return [m.text for m in memories]
