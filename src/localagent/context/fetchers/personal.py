"""Personal / family / browse memory prefetch."""

from __future__ import annotations

import re

from localagent.context.compress import compress_observation
from localagent.context.router import (
    LOCATION_QUERY,
    PrefetchRoute,
    personal_prefetch_path,
    prefetch_header,
)
from localagent.logging_setup import truncate_for_log
from localagent.memory.core_profile import load_core_profile


def rewrite_personal_memory_query(user_message: str) -> str:
    """Optionally expand personal questions; keep original text for embedding recall."""
    if LOCATION_QUERY.search(user_message):
        return f"{user_message} 居住 住在 住址 位于"
    return user_message


def browse_cold_query(user_message: str) -> str:
    """Strip memory-browse boilerplate so Cold RAG gets a topical query."""
    q = user_message.strip()
    q = re.sub(
        r"(?:请)?(?:帮我)?(?:深入|深度|仔细|全面)?(?:搜索|检索|查看|浏览)"
        r"(?:一下)?(?:我的)?(?:记忆库|记忆)[，,、。！!\s]*",
        "",
        q,
        count=1,
    )
    q = re.sub(
        r"(?:我的)?记忆库(?:里|中)?[，,、。！!\s]*",
        "",
        q,
        count=1,
    )
    cleaned = q.strip(" ，,、。！!?？")
    return cleaned or user_message.strip()


def prefetch_personal_context(
    user_message: str,
    *,
    path: str | None = None,
    route: PrefetchRoute | None = None,
) -> str:
    """Load profile + Warm + Cold upfront for identity/browse/topic questions."""
    resolved = path or personal_prefetch_path(user_message)
    if resolved is None:
        return ""
    from localagent import config as _cfg
    from localagent.context.retrieval import get_retrieval_gateway

    import logging

    logger = logging.getLogger(__name__)
    gw = get_retrieval_gateway()
    logger.info("prefetch personal context path=%s", resolved)
    logger.debug("prefetch personal query=%s", truncate_for_log(user_message))

    profile = load_core_profile().format_for_prompt()
    memory_parts: list[str] = []
    cold = ""
    cold_conversation_only = False
    keep = max(1, int(_cfg.OBSERVE_KEEP_HITS))

    if resolved == "family":
        memory_parts.append(
            gw.query_warm(
                query="家庭 家人 父母 孩子 妻子",
                tags=["家庭"],
                sort="relevance",
                limit=min(8, keep + 2),
            )
        )
        memory_parts.append(
            gw.recall_warm(
                "家庭 家人 父母 孩子 妻子 老公 老婆",
                top_k=keep,
                fallback=False,
            )
        )
        cold_conversation_only = True
        cold = gw.search_cold(
            "家庭 家人 父母 孩子 妻子 老公 老婆",
            top_k=min(5, keep),
            fallback=False,
            conversation_only=True,
        )
    elif resolved == "browse":
        memory_parts.append(
            gw.query_warm(
                query=user_message,
                sort="relevance" if len(user_message.strip()) > 4 else "newest",
                limit=min(8, keep + 2),
            )
        )
        cold_query = browse_cold_query(user_message)
        logger.info(
            "prefetch browse cold query=%s",
            truncate_for_log(cold_query),
        )
        cold = gw.search_cold(cold_query, top_k=min(5, keep), fallback=False)
        if (
            cold.startswith("未找到")
            and cold_query != user_message.strip()
            and len(cold_query) < 8
        ):
            cold = gw.search_cold(user_message, top_k=min(5, keep), fallback=False)
    else:
        recall_query = rewrite_personal_memory_query(user_message)
        rewritten = recall_query != user_message
        logger.info("prefetch personal rewrite=%s", rewritten)
        if rewritten:
            logger.debug("prefetch rewrite→ %s", truncate_for_log(recall_query))
        memory_parts.append(gw.recall_warm(recall_query, top_k=min(8, keep + 2)))
        if rewritten:
            memory_parts.append(
                gw.recall_warm(user_message, top_k=min(5, keep), fallback=False)
            )
        cold_conversation_only = True
        cold_query = recall_query if rewritten else user_message
        cold = gw.search_cold(
            cold_query,
            top_k=min(5, keep),
            fallback=False,
            conversation_only=True,
        )
        if cold.startswith("未找到") and rewritten:
            cold = gw.search_cold(
                user_message,
                top_k=min(5, keep),
                fallback=False,
                conversation_only=True,
            )

    memory = compress_observation(
        "query_memories",
        "\n\n".join(part for part in memory_parts if part),
        user_query=user_message,
    )
    if cold:
        cold = compress_observation(
            "search_knowledge",
            cold,
            user_query=user_message,
        )
    forbid = "search_memory / query_memories / search_knowledge"
    lines = [
        prefetch_header(
            route,
            "personal",
            strong=f"[个人上下文（已预加载，请直接据此回答，勿再调用 {forbid}）]",
            soft=f"[个人上下文（已预加载，可优先据此回答；不足时再调用 {forbid}）]",
        ),
        profile,
        f"记忆检索 (Warm):\n{memory}",
    ]
    if cold_conversation_only:
        lines.append(
            "说明：Cold 为跨会话对话原文/摘要（ChatGPT 导入与 LA 历史）；"
            "请综合 Warm 事实与 Cold 内容回答，勿只复述短事实句。"
        )
        lines.append(f"对话归档 (Cold):\n{cold or '（Cold 未命中）'}")
    else:
        lines.append(
            "说明：Cold 含知识库文档与跨会话对话原文/摘要（ChatGPT 导入与 LA 历史）；"
            "请综合 Warm 事实与 Cold 内容回答，勿只复述短事实句。"
        )
        lines.append(f"知识库/对话归档 (Cold):\n{cold or '（Cold 未命中）'}")
    return "\n".join(lines)
