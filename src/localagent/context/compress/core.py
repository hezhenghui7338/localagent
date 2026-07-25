"""Heuristic context compression for small local models.

Implementation module for ``context.compress``; prefer importing from
``localagent.context.compress`` or ``localagent.agent.observe`` (shim).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from localagent import config

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


_LOCAL_PROVIDERS = frozenset({"ollama"})

_QUERY_STOPWORDS = frozenset(
    {
        "什么",
        "怎么",
        "如何",
        "为什么",
        "哪里",
        "哪个",
        "是否",
        "可以",
        "一下",
        "the",
        "and",
        "for",
        "what",
        "how",
        "why",
        "where",
        "when",
        "with",
        "this",
        "that",
        "from",
        "about",
    }
)


@dataclass(frozen=True)
class ContextTier:
    name: str
    observe_budget: int
    evidence_budget: int
    keep_full_rounds: int


@dataclass
class EvidenceEntry:
    step: int
    tool: str
    summary: str
    signature: str


def _default_budget() -> int:
    return max(200, int(getattr(config, "OBSERVE_BUDGET_CHARS", 1200)))


def _normalize_provider(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def resolve_context_tier(
    prefer: str | None = None,
    last_provider: str | None = None,
) -> ContextTier:
    """Return observe/evidence budgets for local (ollama) vs cloud providers."""
    local_observe = max(200, int(getattr(config, "OBSERVE_BUDGET_CHARS", 1200)))
    cloud_observe = max(
        local_observe,
        int(getattr(config, "OBSERVE_BUDGET_CHARS_CLOUD", 2400)),
    )
    local_evidence = max(120, int(getattr(config, "EVIDENCE_BUDGET_CHARS", 600)))
    cloud_evidence = max(
        local_evidence,
        int(getattr(config, "EVIDENCE_BUDGET_CHARS_CLOUD", 1200)),
    )
    local_keep = max(1, int(getattr(config, "OBSERVE_KEEP_FULL_ROUNDS", 1)))
    cloud_keep = max(
        local_keep,
        int(getattr(config, "OBSERVE_KEEP_FULL_ROUNDS_CLOUD", 2)),
    )

    provider = _normalize_provider(last_provider)
    if not provider and prefer:
        pref = _normalize_provider(prefer)
        if pref and pref not in ("auto", getattr(config, "DEFAULT_MODEL_PROVIDER", "auto")):
            provider = pref

    is_local = provider in _LOCAL_PROVIDERS or not provider
    if is_local:
        return ContextTier("local", local_observe, local_evidence, local_keep)
    return ContextTier("cloud", cloud_observe, cloud_evidence, cloud_keep)


def _query_tokens(user_query: str) -> list[str]:
    q = (user_query or "").strip().lower()
    if not q:
        return []
    tokens = re.findall(r"[\w\u4e00-\u9fff]{2,}", q)
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in _QUERY_STOPWORDS or token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= 8:
            break
    return out


def _line_query_score(line: str, tokens: list[str]) -> int:
    if not tokens:
        return 0
    low = line.lower()
    return sum(1 for token in tokens if token in low)


def _prioritize_text_by_query(text: str, user_query: str, *, limit: int) -> str:
    tokens = _query_tokens(user_query)
    if not text or len(text) <= limit or not tokens:
        return apply_context_budget(text, budget=limit, label="")
    lines = text.splitlines()
    if not lines:
        return apply_context_budget(text, budget=limit, label="")

    scored: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        scored.append((_line_query_score(line, tokens), idx, line))
    matched = [item for item in scored if item[0] > 0]
    if not matched:
        return apply_context_budget(text, budget=limit, label="")

    matched.sort(key=lambda item: (-item[0], item[1]))
    picked: list[str] = []
    used: set[int] = set()
    for _, idx, line in matched:
        if idx in used:
            continue
        picked.append(line)
        used.add(idx)
        if len("\n".join(picked)) >= limit:
            break

    if len("\n".join(picked)) < limit:
        for _, idx, line in sorted(scored, key=lambda item: item[1]):
            if idx in used:
                continue
            picked.append(line)
            used.add(idx)
            if len("\n".join(picked)) >= limit:
                break

    out = "\n".join(picked)
    if len(out) > limit:
        out = apply_context_budget(out, budget=limit, label="")
    return out


def tool_path_signature(tool_name: str, arguments: dict[str, Any] | None) -> str:
    """Stable dedupe key for a tool call (tool + path/query)."""
    args = arguments or {}
    path = str(args.get("path") or args.get("file") or "").strip()
    query = str(
        args.get("query")
        or args.get("pattern")
        or args.get("command")
        or args.get("glob_pattern")
        or ""
    ).strip()
    name = (tool_name or "tool").strip()
    if path:
        return f"{name}:{path}"
    if query:
        return f"{name}:{query[:80]}"
    return name


def extract_evidence_bullet(
    tool_name: str,
    raw: str,
    *,
    user_query: str = "",
    arguments: dict[str, Any] | None = None,
    step: int = 1,
    budget: int = 180,
) -> EvidenceEntry:
    """Build a one-line evidence digest for the turn working-memory block."""
    name = (tool_name or "tool").strip()
    args = arguments or {}
    text = (raw or "").strip()
    signature = tool_path_signature(name, args)

    if name in ("read_file", "grep"):
        path = str(args.get("path") or args.get("pattern") or "").strip()
        tokens = _query_tokens(user_query)
        best_line = ""
        best_score = -1
        for line in text.splitlines():
            score = _line_query_score(line, tokens)
            if score > best_score:
                best_score = score
                best_line = line.strip()
        if not best_line:
            for line in text.splitlines():
                stripped = line.strip()
                if stripped:
                    best_line = stripped
                    break
        if path and best_line:
            summary = f"{path} → {_clip_line(best_line, max(80, budget - len(path) - 4))}"
        elif path:
            summary = f"{path} → {_clip_line(text, budget - len(path) - 4)}"
        elif best_line:
            summary = _clip_line(best_line, budget)
        else:
            summary = _clip_line(text, budget)

    elif name == "glob":
        paths = [line.strip() for line in text.splitlines() if line.strip()][:5]
        pattern = str(args.get("pattern") or args.get("glob_pattern") or "").strip()
        joined = ", ".join(paths) if paths else _clip_line(text, budget)
        summary = f"{pattern or 'glob'} → {_clip_line(joined, budget)}"

    elif name == "run_shell":
        exit_line = ""
        err_line = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("exit:"):
                exit_line = stripped
            if any(token in stripped.lower() for token in ("error", "failed", "错误", "失败")):
                err_line = stripped
        tail = err_line or (text.splitlines()[-1].strip() if text.splitlines() else "")
        cmd = str(args.get("command") or "").strip()
        prefix = f"{_clip_line(cmd, 40)} " if cmd else ""
        if exit_line:
            summary = f"{prefix}{exit_line}"
            if tail and tail != exit_line:
                summary = f"{summary}; {_clip_line(tail, 80)}"
        else:
            summary = _clip_line(tail or text, budget)

    elif name in ("write_file", "edit_file", "retain_memory"):
        path = str(args.get("path") or "").strip()
        marker = _clip_line(text.splitlines()[0] if text.splitlines() else text, budget)
        summary = f"{path} → {marker}" if path else marker

    elif name in ("search_memory", "query_memories", "query_memory_graph", "reflect_memory", "search_knowledge"):
        compressed = compress_observation(name, text, user_query=user_query, budget=min(budget * 2, 400))
        first_line = next((ln.strip() for ln in compressed.splitlines() if ln.strip()), compressed)
        summary = _clip_line(first_line.replace("\n", " "), budget)

    elif name == "web_search":
        summary = _clip_line(text.splitlines()[0] if text.splitlines() else text, budget)

    else:
        summary = _clip_line(text.replace("\n", " "), budget)

    return EvidenceEntry(
        step=step,
        tool=name,
        summary=_clip_line(summary, budget),
        signature=signature,
    )


def format_turn_evidence(
    entries: list[EvidenceEntry],
    *,
    goal: str = "",
    budget: int | None = None,
) -> str:
    """Format goal anchor + numbered evidence bullets within ``budget`` chars."""
    limit = budget if budget is not None else max(
        120, int(getattr(config, "EVIDENCE_BUDGET_CHARS", 600))
    )
    goal_text = (goal or "").strip()
    if not entries and not goal_text:
        return ""

    lines: list[str] = []
    if goal_text:
        lines.append(f"【当前目标】{_clip_line(goal_text, min(200, limit))}")

    if entries:
        lines.append("【已收集证据】")
        for entry in entries:
            lines.append(f"{entry.step}. {entry.tool} → {entry.summary}")

    text = "\n".join(lines)
    if len(text) <= limit:
        return text

    if goal_text:
        header = f"【当前目标】{_clip_line(goal_text, min(200, limit))}\n【已收集证据】"
    else:
        header = "【已收集证据】"

    remaining = max(80, limit - len(header) - 1)
    kept: list[str] = [header]
    for entry in reversed(entries):
        line = f"{entry.step}. {entry.tool} → {entry.summary}"
        if len(line) + 1 > remaining:
            line = _clip_line(line, remaining)
        if len(line) + sum(len(x) + 1 for x in kept) > limit:
            break
        kept.insert(1 if len(kept) > 1 else len(kept), line)
        remaining -= len(line) + 1

    if len(entries) > max(0, len(kept) - (2 if goal_text else 1)):
        kept.append("（较早证据已省略，见最新工具结果）")

    out = "\n".join(kept)
    return out if len(out) <= limit else out[: max(40, limit - 1)] + "…"


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
        if user_query.strip():
            return _prioritize_text_by_query(text, user_query, limit=limit)
        return apply_context_budget(text, budget=limit, label=name)

    return truncate_head_tail(text, limit=limit)


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


def compact_prior_observations(
    messages: list[Any],
    *,
    keep_full_rounds: int = 1,
) -> None:
    """In-place: shrink older tool observations; keep the latest N full rounds.

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

    keep_n = max(1, keep_full_rounds)
    if len(tool_result_idxs) <= keep_n:
        return

    compress_upto = len(tool_result_idxs) - keep_n
    for step, idx in enumerate(tool_result_idxs[:compress_upto], start=1):
        msg = messages[idx]
        tool_name = "tool"
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

        digest = f"[步骤{step}: {tool_name} 摘要见 system evidence]"
        if isinstance(msg, dict):
            msg["content"] = digest
        else:
            msg.content = digest
