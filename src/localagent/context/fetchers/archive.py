"""Cold/Warm archive prefetch for past-question recalls."""

from __future__ import annotations

from localagent.context.compress import compress_observation
from localagent.context.router import (
    PrefetchRoute,
    archive_search_query,
    archive_time_window,
    is_weak_archive_topic,
    prefetch_header,
)
from localagent.logging_setup import truncate_for_log


def prefetch_archive_context(
    user_message: str,
    *,
    route: PrefetchRoute | None = None,
) -> str:
    """Prefetch Cold conversation archives (+ Warm topic hits) for past-question recalls."""
    from localagent import config as _cfg
    from localagent.context.retrieval import get_retrieval_gateway

    import logging

    logger = logging.getLogger(__name__)
    gw = get_retrieval_gateway()
    topic = archive_search_query(user_message)
    since, until = archive_time_window(user_message)
    weak_topic = is_weak_archive_topic(topic)
    keep = max(1, int(_cfg.OBSERVE_KEEP_HITS))
    logger.info(
        "prefetch archive context topic=%s since=%s until=%s weak=%s",
        truncate_for_log(topic),
        since,
        until,
        weak_topic,
    )

    if since or until:
        if weak_topic:
            cold = gw.list_user_questions_in_range(
                since=since,
                until=until,
                limit=min(30, keep * 5),
            )
        else:
            cold = gw.search_cold(
                topic,
                top_k=min(6, keep),
                fallback=False,
                since=since,
                until=until,
                conversation_only=True,
            )
        warm = gw.query_warm(
            query="" if weak_topic else topic,
            since=since,
            until=until,
            sort="newest",
            limit=min(8, keep + 2),
            show_ids=False,
            time_field="recorded",
        )
        if weak_topic:
            cold = cold or ""
        else:
            cold = compress_observation("search_knowledge", cold or "", user_query=user_message)
        warm = compress_observation("query_memories", warm or "", user_query=user_message)
        window = f"{since or '…'} ~ {until or '…'}"
        parts: list[str] = [
            prefetch_header(
                route,
                "archive",
                strong="[对话归档检索（已预加载，请直接据此回答，勿再调用 search_knowledge / search_memory / query_memories）]",
                soft="[对话归档检索（已预加载，可优先据此回答；不足时再调用 search_knowledge / search_memory / query_memories）]",
            ),
            f"时间窗（对话发生时间 recorded_at）: {window}",
            "说明：下列 Cold 命中已按对话发生时间硬过滤；只可根据标注日期在窗内的证据作答。"
            "若 Cold 显示该时段无归档，必须如实说明，禁止编造问题清单。"
            "Warm 事实仅作补充（亦按 recorded_at 过滤）。",
            f"检索主题: {topic or '（按时间浏览，无主题）'}",
            f"Cold 对话归档:\n{cold or '（Cold 未命中）'}",
        ]
        if warm and not warm.startswith("未找到") and not warm.startswith("记忆库为空"):
            parts.append(f"Warm 相关事实:\n{warm}")
        return "\n".join(parts)

    cold = compress_observation(
        "search_knowledge",
        gw.search_cold(topic, top_k=min(5, keep), fallback=False),
        user_query=user_message,
    )
    warm = compress_observation(
        "search_memory",
        gw.recall_warm(topic, top_k=min(5, keep), fallback=False),
        user_query=user_message,
    )
    parts = [
        prefetch_header(
            route,
            "archive",
            strong="[对话归档检索（已预加载，请直接据此回答，勿再调用 search_knowledge / search_memory）]",
            soft="[对话归档检索（已预加载，可优先据此回答；不足时再调用 search_knowledge / search_memory）]",
        ),
        "说明：下列 Cold 命中来自 ChatGPT/LA 历史对话原文或摘要；据此回答用户「问过/聊过什么」。"
        "Warm 事实仅作补充，不得因 Warm 未命中而否认 Cold 中的对话记录。",
        f"检索主题: {topic}",
        f"Cold 对话归档:\n{cold or '（Cold 未命中）'}",
    ]
    if warm and not warm.startswith("未找到"):
        parts.append(f"Warm 相关事实:\n{warm}")
    return "\n".join(parts)
