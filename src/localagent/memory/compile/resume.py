"""Resume → structured Hot profile compiler."""

from __future__ import annotations

import re
from typing import Any

from localagent.memory.compile.engine import ProfileCompileResult
from localagent.memory.conversation_extract import ExtractedMemory


def _strip_html(text: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    cleaned = re.sub(r"(?i)</?(p|div|br|li|h[1-6]|tr)[^>]*>", "\n", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _rule_extract_name(text: str) -> str:
    html_match = re.search(r"<h1[^>]*>([\u4e00-\u9fffA-Za-z·\s]{2,20})</h1>", text, re.I)
    if html_match:
        return html_match.group(1).strip()
    line_match = re.search(r"^([\u4e00-\u9fff]{2,4})\s*$", text, re.M)
    return line_match.group(1).strip() if line_match else ""


def _rule_extract_location(text: str) -> str:
    match = re.search(r"现居\s*([^\s·•|，,；;]{2,12})", text)
    if match:
        return match.group(1).strip(" ·•|，,；;")
    match = re.search(r"居住(?:于|在)?\s*([^\s·•|，,；;]{2,12})", text)
    return match.group(1).strip(" ·•|，,；;") if match else ""


def _build_resume_prompt(text: str, *, filename: str, source: str, name_hint: str) -> str:
    return (
        "你是简历结构化提取助手。从下列简历文本提取用户核心画像，输出 JSON（不要 markdown）：\n"
        '{"profile_updates":[{"field":"name|preference|current_status|skill|work_entry|'
        'education|project|goal|contact|source","key":"可选","value":"值","category":"技能分类",'
        '"company":"公司","role":"职位","school":"学校","name":"项目名","confidence":0.95}],'
        '"warm_memories":[{"text":"完整叙事句","type":"fact","tags":["工作"]}]}\n'
        "规则：\n"
        "- profile_updates 写入 Hot 层稳定身份信息\n"
        "- skill 用 category + value（逗号分隔技能列表）\n"
        "- work_entry 每条一段经历；project 每条一个项目\n"
        "- goal 写求职意向；contact 写 phone/email/github 等 key+value\n"
        "- source field 固定写入来源文件名\n"
        "- warm_memories 可选，3-8 条关键叙事句\n"
        f"- 来源文件: {source or filename}\n"
        + (f"- 姓名提示: {name_hint}\n" if name_hint else "")
        + f"\n简历文本:\n{text[:12000]}"
    )


def _parse_resume_reply(reply: str, *, source: str) -> ProfileCompileResult:
    import json

    from localagent.memory.conversation_extract import _item_to_memory
    from localagent.models.router import _parse_profile_updates_reply

    raw = (reply or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    updates: list[dict[str, Any]] = []
    memories: list[ExtractedMemory] = []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return ProfileCompileResult(source=source)
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return ProfileCompileResult(source=source)

    if isinstance(data, dict):
        updates = _parse_profile_updates_reply(json.dumps({"updates": data.get("profile_updates") or []}))
        warm_raw = data.get("warm_memories") or []
        if isinstance(warm_raw, list):
            for item in warm_raw:
                mem = _item_to_memory(item)
                if mem is not None:
                    memories.append(mem)
    return ProfileCompileResult(profile_updates=updates, warm_memories=memories, source=source)


def _rule_bootstrap_updates(text: str, *, source: str) -> list[dict[str, Any]]:
    updates: list[dict[str, Any]] = []
    name = _rule_extract_name(text)
    if name:
        updates.append({"field": "name", "value": name, "confidence": 0.95})
    location = _rule_extract_location(text)
    if location:
        updates.append(
            {"field": "preference", "key": "居住地", "value": location, "confidence": 0.9}
        )
    goal_match = re.search(r"求职意向[:：]\s*([^\n]+)", text)
    if goal_match:
        updates.append({"field": "goal", "value": goal_match.group(1).strip(), "confidence": 0.9})
    if source:
        updates.append({"field": "source", "value": source, "confidence": 1.0})
    return updates


def compile_resume(text: str, *, filename: str = "", source: str = "") -> ProfileCompileResult:
    """Compile resume HTML/text into Hot profile updates."""
    plain = _strip_html(text) if "<" in text else text
    src = source or filename
    name_hint = _rule_extract_name(text)

    try:
        from localagent.models.router import ChatMessage, get_model_router

        prompt = _build_resume_prompt(plain, filename=filename, source=src, name_hint=name_hint)
        reply = get_model_router().chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.1,
            usage_command="compile_resume",
        )
        result = _parse_resume_reply(reply, source=src)
    except Exception:
        result = ProfileCompileResult(source=src)

    if not result.profile_updates:
        result.profile_updates = _rule_bootstrap_updates(text, source=src)
    else:
        bootstrap = _rule_bootstrap_updates(text, source=src)
        existing_fields = {str(u.get("field")) for u in result.profile_updates}
        for item in bootstrap:
            if item["field"] not in existing_fields:
                result.profile_updates.append(item)

    return result
