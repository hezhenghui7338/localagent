"""Heuristic Observe-phase compression for small local models.

No extra LLM calls — structured tool / prefetch text is trimmed by rules so
the agent loop stays within a tight context budget.
"""

from __future__ import annotations

import re
from typing import Any

from localagent import config

# Prefetch blocks: higher priority kept when total budget is exceeded.
PREFETCH_PRIORITY = (
    "personal",
    "archive",
    "session",
    "web",
    "workspace",
)

# When the user asks about STM (today / last session), keep session first.
PREFETCH_PRIORITY_SESSION_FIRST = (
    "session",
    "personal",
    "archive",
    "web",
    "workspace",
)

_HIT_CARD_SPLIT = re.compile(r"\n[─-]{3,}\n")
_HIT_HEADER = re.compile(r"^###\s+\d+\.")
_LIST_ITEM = re.compile(r"^[-*]\s+")
_KNOWLEDGE_HIT = re.compile(r"^\[\d+\]")
_TOOL_RESULT_PREFIX = "工具结果:"
_STALE_SECTION = re.compile(
    r"\n(?:已过滤的过期结果|过期结果（仅供排查[^\n]*）):.*",
    re.DOTALL,
)
_CONTENT_AFTER_TITLE = re.compile(
    r"^(\s*-\s*\[[^\]]*\]\s*[^:]+:\s*)(.{0,120})(.*)$",
    re.MULTILINE,
)
_TOOL_NAME_IN_FENCE = re.compile(
    r'"name"\s*:\s*"([a-zA-Z0-9_]+)"',
)
_XML_TOOL_NAME = re.compile(r"<tool_call>\s*([a-zA-Z0-9_]+)", re.IGNORECASE)


def _default_budget() -> int:
    return max(200, int(getattr(config, "OBSERVE_BUDGET_CHARS", 1200)))


def _default_prefetch_budget() -> int:
    return max(200, int(getattr(config, "PREFETCH_BUDGET_CHARS", 1500)))


def _keep_hits() -> int:
    return max(1, int(getattr(config, "OBSERVE_KEEP_HITS", 6)))


def truncate_head_tail(text: str, *, limit: int) -> str:
    """Keep head + tail when text exceeds limit (errors often live at the end)."""
    if len(text) <= limit:
        return text
    note = f"\n…（已截断至约 {limit} 字符）…\n"
    usable = max(40, limit - len(note))
    head = (usable * 2) // 3
    tail = usable - head
    return text[:head] + note + text[-tail:]


def apply_context_budget(text: str, *, budget: int | None = None, label: str = "") -> str:
    """Hard-cap a single context block."""
    if not text:
        return text
    limit = budget if budget is not None else _default_budget()
    if len(text) <= limit:
        return text
    note_mid = f"（{label}）" if label else ""
    note = f"\n…{note_mid}上下文过长，已截断至约 {limit} 字符…\n"
    usable = max(40, limit - len(note))
    head = (usable * 2) // 3
    tail = usable - head
    return text[:head] + note + text[-tail:]


def _clip_line(text: str, max_chars: int) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1] + "…"


def _split_memory_cards(text: str) -> tuple[str, list[str]]:
    """Split format_memory_hits output into header + card bodies."""
    parts = _HIT_CARD_SPLIT.split(text)
    if len(parts) <= 1 and not _HIT_HEADER.search(text):
        return text, []
    header = ""
    cards: list[str] = []
    for i, part in enumerate(parts):
        chunk = part.strip()
        if not chunk:
            continue
        if i == 0 and not _HIT_HEADER.search(chunk.split("\n", 1)[0]):
            # Leading "找到 N 条…" header may share the first segment.
            lines = chunk.split("\n")
            hdr_lines: list[str] = []
            body_start = 0
            for j, line in enumerate(lines):
                if _HIT_HEADER.match(line.strip()):
                    body_start = j
                    break
                hdr_lines.append(line)
            else:
                header = chunk
                continue
            header = "\n".join(hdr_lines).strip()
            rest = "\n".join(lines[body_start:]).strip()
            if rest:
                cards.append(rest)
            continue
        cards.append(chunk)
    return header, cards


def _compress_memory_card(card: str, *, body_limit: int = 140) -> str:
    lines = card.splitlines()
    if not lines:
        return card
    title = lines[0].strip()
    body_lines: list[str] = []
    meta = ""
    for line in lines[1:]:
        s = line.strip()
        if not s:
            continue
        if s.startswith("来源:") or s.startswith("时间锚点:") or s.startswith("语义 "):
            continue
        if " · " in s and any(x in s for x in ("相关度", "事实", "偏好", "计划", "经历")):
            meta = s
            continue
        body_lines.append(s)
    body = _clip_line(" ".join(body_lines), body_limit)
    out = [title]
    if meta:
        # Keep date + type only (drop long tag lists).
        bits = [b for b in meta.split(" · ") if not b.startswith("#")][:3]
        if bits:
            out.append(" · ".join(bits))
    if body:
        out.append(body)
    return "\n".join(out)


def _compress_hit_list(
    text: str,
    *,
    keep: int,
    body_limit: int,
    item_pattern: re.Pattern[str] | None = None,
) -> str:
    """Keep top-N list-like hits; truncate each body."""
    header, cards = _split_memory_cards(text)
    if cards:
        kept = [_compress_memory_card(c, body_limit=body_limit) for c in cards[:keep]]
        omitted = len(cards) - len(kept)
        parts = []
        if header:
            parts.append(header)
        parts.append("\n\n".join(kept))
        if omitted > 0:
            parts.append(f"（另有 {omitted} 条已省略）")
        return "\n\n".join(p for p in parts if p)

    # Fallback: line-oriented list (`- …` / `[1] …`)
    lines = text.splitlines()
    items: list[str] = []
    preface: list[str] = []
    current: list[str] = []
    pat = item_pattern or _LIST_ITEM

    def _flush() -> None:
        nonlocal current
        if current:
            items.append("\n".join(current))
            current = []

    for line in lines:
        if pat.match(line.strip()) or _KNOWLEDGE_HIT.match(line.strip()):
            if not items and not current and preface:
                pass
            _flush()
            current = [line]
        elif current:
            current.append(line)
        else:
            preface.append(line)
    _flush()

    if not items:
        return text

    kept_items = []
    for item in items[:keep]:
        item_lines = item.splitlines()
        head = item_lines[0]
        rest = _clip_line(" ".join(l.strip() for l in item_lines[1:] if l.strip()), body_limit)
        kept_items.append(head if not rest else f"{head}\n  {rest}")
    omitted = len(items) - len(kept_items)
    out_parts = []
    if preface:
        out_parts.append("\n".join(preface).rstrip())
    out_parts.append("\n".join(kept_items))
    if omitted > 0:
        out_parts.append(f"（另有 {omitted} 条已省略）")
    return "\n".join(p for p in out_parts if p)


def _compress_web_search(text: str, *, budget: int) -> str:
    # Drop stale dump section — not useful for answering.
    cleaned = _STALE_SECTION.sub("", text).rstrip()

    # Shorten per-result content after the title colon.
    def _shorten_content(match: re.Match[str]) -> str:
        prefix, content, _rest = match.group(1), match.group(2), match.group(3)
        # Keep URL/source lines that follow on later lines; only trim this line's content.
        return prefix + _clip_line(content, 120)

    cleaned = _CONTENT_AFTER_TITLE.sub(_shorten_content, cleaned)

    # Prefer usable items; drop excess list items after keep_hits.
    lines = cleaned.splitlines()
    header_lines: list[str] = []
    items: list[list[str]] = []
    current: list[str] | None = None
    footer: list[str] = []
    in_items = False

    for line in lines:
        if line.startswith("- ["):
            in_items = True
            if current:
                items.append(current)
            current = [line]
            continue
        if current is not None and (
            line.startswith("  来源:") or line.startswith("  链接:") or line.startswith("  ")
        ):
            current.append(line)
            continue
        if current is not None and not line.strip():
            items.append(current)
            current = None
            continue
        if in_items and line.startswith("【"):
            if current:
                items.append(current)
                current = None
            footer.append(line)
            continue
        if not in_items:
            header_lines.append(line)
        elif current is None:
            footer.append(line)
        else:
            current.append(line)
    if current:
        items.append(current)

    keep = min(_keep_hits(), 5)
    kept = items[:keep]
    omitted = len(items) - len(kept)
    parts = ["\n".join(header_lines).rstrip()]
    for item in kept:
        parts.append("\n".join(item))
    if omitted > 0:
        parts.append(f"（另有 {omitted} 条检索结果已省略）")
    if footer:
        parts.append("\n".join(footer))
    out = "\n".join(p for p in parts if p)
    return apply_context_budget(out, budget=budget, label="web_search")


def _compress_shell(text: str, *, budget: int) -> str:
    # Prefer exit code + tail (errors / last lines matter).
    limit = min(budget, 1000)
    if len(text) <= limit:
        return text
    lines = text.splitlines()
    head_keep = []
    for line in lines[:4]:
        head_keep.append(line)
        if line.startswith("exit:"):
            break
    head = "\n".join(head_keep)
    remaining = limit - len(head) - 40
    if remaining < 100:
        return truncate_head_tail(text, limit=limit)
    tail = text[-(remaining):]
    return head + f"\n…（stdout/stderr 已压缩至约 {limit} 字符）…\n" + tail


def _compress_workspace(text: str, *, budget: int) -> str:
    lines = text.splitlines()
    keep_recent = 8
    out: list[str] = []
    recent_count = 0
    in_recent = False
    for line in lines:
        low = line.lower()
        if "recent" in low or "最近" in line or "files" in low or "文件" in line:
            in_recent = True
            out.append(line)
            continue
        if in_recent and (line.startswith("-") or line.startswith("•") or line.startswith(" ")):
            if recent_count < keep_recent:
                out.append(line)
                recent_count += 1
            continue
        if in_recent and line.strip() and not line.startswith((" ", "-", "•", "\t")):
            in_recent = False
        if not in_recent:
            out.append(line)
    omitted = max(0, sum(1 for l in lines if l.startswith("-") or l.startswith("•")) - recent_count)
    result = "\n".join(out)
    if omitted > 0 and recent_count >= keep_recent:
        result += f"\n（另有若干最近文件已省略）"
    return apply_context_budget(result, budget=budget, label="workspace")


def compress_observation(
    tool_name: str,
    result: str,
    *,
    user_query: str = "",
    budget: int | None = None,
) -> str:
    """Compress a tool observation for the next Think step."""
    del user_query  # reserved for future query-aware clipping
    text = result or ""
    if not text:
        return text
    limit = budget if budget is not None else _default_budget()
    name = (tool_name or "").strip()
    keep = _keep_hits()

    if name in ("search_memory", "query_memories", "query_memory_graph", "reflect_memory"):
        out = _compress_hit_list(text, keep=keep, body_limit=140)
        return apply_context_budget(out, budget=limit, label=name)

    if name == "search_knowledge":
        out = _compress_hit_list(
            text,
            keep=min(keep, 5),
            body_limit=200,
            item_pattern=_LIST_ITEM,
        )
        return apply_context_budget(out, budget=limit, label=name)

    if name == "web_search":
        return _compress_web_search(text, budget=limit)

    if name == "run_shell":
        return _compress_shell(text, budget=limit)

    if name == "workspace_context":
        return _compress_workspace(text, budget=limit)

    if name in ("write_file", "edit_file", "retain_memory"):
        return apply_context_budget(text, budget=limit, label=name)

    if name in ("read_file", "glob", "grep"):
        return apply_context_budget(text, budget=limit, label=name)

    return truncate_head_tail(text, limit=limit)


def budget_prefetch_blocks(
    blocks: dict[str, str],
    *,
    budget: int | None = None,
    session_first: bool = False,
) -> dict[str, str]:
    """Shrink prefetch blocks so their combined size fits ``budget``.

    Priority (kept first): personal → archive → session → web → workspace.
    When ``session_first`` is True (STM recall), session is kept ahead of others.
    Lower-priority blocks are truncated or dropped when over budget.
    """
    limit = budget if budget is not None else _default_prefetch_budget()
    priority = PREFETCH_PRIORITY_SESSION_FIRST if session_first else PREFETCH_PRIORITY
    ordered = [k for k in priority if blocks.get(k)]
    for key in blocks:
        if key not in ordered and blocks.get(key):
            ordered.append(key)

    result: dict[str, str] = {}
    remaining = limit
    for key in ordered:
        text = blocks.get(key) or ""
        if not text:
            continue
        if remaining <= 0:
            break
        if len(text) <= remaining:
            result[key] = text
            remaining -= len(text)
            continue
        # Partial fit: keep a truncated stub if there is room for signal.
        if remaining >= 40:
            result[key] = apply_context_budget(text, budget=remaining, label=key)
        break

    return result


def _extract_tool_name_from_assistant(content: str) -> str:
    m = _TOOL_NAME_IN_FENCE.search(content or "")
    if m:
        return m.group(1)
    m = _XML_TOOL_NAME.search(content or "")
    if m:
        return m.group(1)
    return "tool"


def _is_tool_result_message(content: str) -> bool:
    return (content or "").lstrip().startswith(_TOOL_RESULT_PREFIX)


def compact_prior_observations(messages: list[Any]) -> None:
    """In-place: shrink older tool observations; keep only the latest full.

    Expected pattern: assistant(tool call) + user(\"工具结果:…\").
    """
    if not messages:
        return

    tool_result_idxs: list[int] = []
    for i, msg in enumerate(messages):
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content", "")
        role = getattr(msg, "role", None)
        if role is None and isinstance(msg, dict):
            role = msg.get("role")
        if role == "user" and _is_tool_result_message(str(content or "")):
            tool_result_idxs.append(i)

    if len(tool_result_idxs) < 2:
        return

    # Keep the last observation full; compress earlier ones.
    for idx in tool_result_idxs[:-1]:
        msg = messages[idx]
        content = getattr(msg, "content", "") if not isinstance(msg, dict) else msg.get("content", "")
        tool_name = "tool"
        # Pair with preceding assistant tool call when present.
        if idx > 0:
            prev = messages[idx - 1]
            prev_role = getattr(prev, "role", None) if not isinstance(prev, dict) else prev.get("role")
            prev_content = (
                getattr(prev, "content", "") if not isinstance(prev, dict) else prev.get("content", "")
            )
            if prev_role == "assistant":
                tool_name = _extract_tool_name_from_assistant(str(prev_content or ""))
                short_assistant = f"[已调用工具 {tool_name}]"
                if isinstance(prev, dict):
                    prev["content"] = short_assistant
                else:
                    prev.content = short_assistant

        digest = f"[先前工具 {tool_name}：结果已压缩，保留最新一轮证据]"
        if isinstance(msg, dict):
            msg["content"] = digest
        else:
            msg.content = digest
