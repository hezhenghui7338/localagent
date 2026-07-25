"""STM session transcript prefetch."""

from __future__ import annotations

from localagent.context.router import (
    PrefetchRoute,
    is_last_session_recall_query,
    prefetch_header,
)


def format_session_messages(
    messages: list[dict],
    *,
    include_ts: bool = True,
) -> list[str]:
    lines: list[str] = []
    for msg in messages:
        role = "用户" if msg.get("role") == "user" else "助手"
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        ts = msg.get("ts", "") if include_ts else ""
        prefix = f"[{ts}] " if ts else ""
        lines.append(f"{prefix}{role}: {content}")
    return lines


def pack_session_blocks(
    blocks: list[str],
    *,
    header: str,
    budget: int,
) -> str:
    """Join blocks newest-first already ordered; stop when over budget."""
    if not blocks:
        return f"{header}\n近期暂无已保存的聊天记录。"
    kept: list[str] = []
    used = len(header) + 1
    for block in blocks:
        add = len(block) + (1 if kept else 0)
        if kept and used + add > budget:
            break
        kept.append(block)
        used += add
    if not kept:
        kept = [blocks[0][: max(40, budget - len(header) - 20)]]
    return f"{header}\n" + "\n".join(kept)


def prefetch_session_context(
    user_message: str,
    history: list[dict[str, str]] | None,
    session_id: str | None,
    *,
    route: PrefetchRoute | None = None,
) -> str:
    """Load STM chat transcripts (rolling window or previous session)."""
    from localagent import config as _cfg
    from localagent.persist.conversations import (
        list_sessions_in_stm_window,
        load_conversation,
        message_create_time,
        previous_session_id,
        stm_window_start_unix,
    )

    budget = max(200, int(getattr(_cfg, "PREFETCH_BUDGET_CHARS", 1500)))

    if is_last_session_recall_query(user_message):
        header = prefetch_header(
            route,
            "session",
            strong="[上一场对话（已预加载，请直接据此回答，勿再调用工具）]",
            soft="[上一场对话（已预加载，可优先据此回答；不足时再调用工具）]",
        )
        prev = previous_session_id(session_id)
        if not prev:
            return f"{header}\n暂无上一场已保存的对话。"
        messages = load_conversation(prev)
        if not messages:
            return f"{header}\n上一场会话 {prev} 无消息。"
        lines = [f"## 会话 {prev}（上一场）"]
        lines.extend(format_session_messages(messages))
        return pack_session_blocks(lines, header=header, budget=budget)

    header = prefetch_header(
        route,
        "session",
        strong="[对话记录（已预加载，请直接据此回答，勿再调用工具）]",
        soft="[对话记录（已预加载，可优先据此回答；不足时再调用工具）]",
    )
    since = stm_window_start_unix()
    hours = float(getattr(_cfg, "STM_WINDOW_HOURS", 24) or 24)
    blocks: list[str] = [
        f"说明：以下为近 {hours:g} 小时内的短期对话（STM），按时间新→旧排列。"
    ]

    session_chunks: list[list[str]] = []

    if history:
        chunk = ["## 当前会话（进行中）"]
        chunk.extend(format_session_messages(history, include_ts=False))
        if len(chunk) > 1:
            session_chunks.append(chunk)

    for sid in list_sessions_in_stm_window(descending=True):
        if sid == session_id and history:
            continue
        messages = load_conversation(sid)
        window_messages = [
            m
            for m in messages
            if (ct := message_create_time(m)) is not None and ct >= since
        ]
        if not window_messages:
            continue
        label = f"{sid}（当前）" if sid == session_id else sid
        chunk = [f"## 会话 {label}"]
        chunk.extend(format_session_messages(window_messages))
        session_chunks.append(chunk)

    flat: list[str] = [blocks[0]]
    used = len(header) + 1 + len(blocks[0])
    for chunk in session_chunks:
        chunk_text_len = sum(len(line) + 1 for line in chunk)
        if flat and used + chunk_text_len > budget:
            if len(flat) <= 1:
                for line in chunk:
                    add = len(line) + 1
                    if used + add > budget:
                        break
                    flat.append(line)
                    used += add
            break
        flat.extend(chunk)
        used += chunk_text_len

    if len(flat) <= 1:
        return f"{header}\n近 {hours:g} 小时内暂无已保存的聊天记录。"
    return f"{header}\n" + "\n".join(flat)
