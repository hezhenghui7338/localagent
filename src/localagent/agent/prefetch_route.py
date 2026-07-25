"""Centralized JIT prefetch routing: signals, priority, and block matrix.

Regex patterns detect individual signals; ``route_prefetch_modules`` applies
priority and mutual-exclusion rules so prefetch triggers stay in one place
instead of scattered ``if re.search`` patches inside each ``_prefetch_*``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from localagent.context.router.queries import (
    AWARE_QUERY,
    LOCATION_QUERY,
    PersonalPath,
    WEB_DOMAIN,
    WEB_OVERRIDE,
    archive_search_query,
    archive_time_window,
    is_archive_recall_query,
    is_aware_query,
    is_last_session_recall_query,
    is_session_recall_query,
    is_web_query,
    is_weak_archive_topic,
    is_workspace_query,
    personal_prefetch_path,
    web_blocked_by_personal,
    web_blocked_by_workspace,
)

PrefetchModule = Literal["session", "archive", "personal", "web", "workspace", "aware"]

# Module priority (higher = kept first under budget pressure).
MODULE_PRIORITY: dict[str, int] = {
    "session": 100,
    "archive": 90,
    "personal": 80,
    "web": 60,
    "workspace": 50,
    "aware": 40,
}

# When module X is active, suppress these lower-priority modules.
BLOCKS: dict[str, frozenset[str]] = {
    "session": frozenset({"web", "workspace", "aware"}),
    "archive": frozenset({"web", "workspace", "aware"}),
    "personal": frozenset({"web"}),  # overridden when WEB_OVERRIDE matches
}

CONFIDENCE_ANCHOR = 0.92
CONFIDENCE_DEFAULT = 0.85
CONFIDENCE_BM25 = 0.68
CONFIDENCE_FORBID = 0.85

# Tier-1 module descriptions for BM25 fallback (extend text, not regex).
MODULE_CORPORA: dict[str, str] = {
    "session": (
        "session today chat conversation 今天 刚才 本次对话 上次聊天 上一场会话 "
        "回顾刚才说了什么 聊了啥 问了啥 review chat history last conversation "
        "what did we talk about today 对话记录 会话回顾"
    ),
    "archive": (
        "archive past conversation 以前 有没有问过 历史对话 导入对话 ChatGPT "
        "某年某月问过什么 聊过 提过 讨论过 previously ever before "
        "conversation archive 对话归档"
    ),
    "personal": (
        "personal profile memory 我是谁 关于我 我的偏好 记忆库 家庭 家人 "
        "住在哪里 who am i my name preferences memory bank 你知道我什么"
    ),
    "web": (
        "web search news weather 新闻 时事 天气 股价 汇率 联网 实时 "
        "现在几点 当前时间 latest breaking headlines stock price"
    ),
    "workspace": (
        "workspace git todo 工作区 最近改了什么 未提交 待办 commit 分支 "
        "项目状态 recent changes uncommitted files project status"
    ),
    "aware": (
        "aware local activity 本机感知 听了什么 看了什么 在忙什么 改了哪些 "
        "电脑屏幕 正在听 正在看 what did i do listen watch work coding"
    ),
}


@dataclass
class PrefetchRoute:
    """Result of prefetch routing for one user turn."""

    modules: list[str] = field(default_factory=list)
    session_first: bool = False
    confidence: float = 0.0
    personal_path: PersonalPath | None = None
    module_confidence: dict[str, float] = field(default_factory=dict)
    source: str = "none"  # none | regex | bm25 | mixed

    def should_prefetch(self, module: str) -> bool:
        return module in self.modules

    def forbid_tools(self, module: str) -> bool:
        """True when prefetch confidence is high enough to skip tool re-fetch."""
        return self.module_confidence.get(module, self.confidence) >= CONFIDENCE_FORBID


def prefetch_header(
    route: PrefetchRoute | None,
    module: str,
    *,
    strong: str,
    soft: str,
) -> str:
    """Pick strict vs soft preload header based on per-module confidence."""
    if route is None or route.forbid_tools(module):
        return strong
    return soft


def _collect_candidates(text: str) -> list[tuple[str, float]]:
    """Detect prefetch module candidates with confidence scores."""
    found: list[tuple[str, float]] = []

    if is_session_recall_query(text):
        found.append(("session", CONFIDENCE_ANCHOR))
    elif is_archive_recall_query(text):
        found.append(("archive", CONFIDENCE_ANCHOR))

    path = personal_prefetch_path(text)
    if path is not None:
        found.append(("personal", CONFIDENCE_ANCHOR))

    if is_web_query(text):
        if not web_blocked_by_personal(text) and not web_blocked_by_workspace(text):
            conf = CONFIDENCE_ANCHOR if WEB_DOMAIN.search(text) else CONFIDENCE_DEFAULT
            found.append(("web", conf))

    if is_workspace_query(text):
        found.append(("workspace", CONFIDENCE_DEFAULT))

    if is_aware_query(text):
        found.append(("aware", CONFIDENCE_DEFAULT))

    return found


def _hybrid_enabled() -> bool:
    from localagent import config

    return getattr(config, "PREFETCH_ROUTER", "regex").lower() == "hybrid"


def _bm25_scores(query: str, docs: list[str]) -> list[float]:
    from localagent.knowledge.bm25_store import tokenize

    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        q_tokens = set(tokenize(query))
        scores: list[float] = []
        for doc in docs:
            d_tokens = set(tokenize(doc))
            scores.append(float(len(q_tokens & d_tokens)))
        return scores

    tokenized = [tokenize(d) for d in docs]
    if not tokenized or not any(tokenized):
        return [0.0] * len(docs)
    bm25 = BM25Okapi(tokenized)
    return list(bm25.get_scores(tokenize(query)))


def _bm25_candidates(text: str) -> list[tuple[str, float]]:
    """Tier-1 fallback when Tier-0 regex finds no module."""
    from localagent import config

    modules = list(MODULE_CORPORA.keys())
    scores = _bm25_scores(text, [MODULE_CORPORA[m] for m in modules])
    ranked = sorted(zip(scores, modules, strict=False), key=lambda x: x[0], reverse=True)
    top_score, top_mod = ranked[0]
    min_score = float(getattr(config, "PREFETCH_BM25_MIN_SCORE", 0.1) or 0.1)
    if top_score < min_score:
        return []
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    if second_score > 0 and top_score < second_score * 1.15:
        return []
    return [(top_mod, CONFIDENCE_BM25)]


def _resolve_personal_path(text: str, modules: list[str]) -> PersonalPath | None:
    if "personal" not in modules:
        return None
    return personal_prefetch_path(text) or "personal"


def route_prefetch_modules(user_message: str) -> PrefetchRoute:
    """Return ordered prefetch modules and routing metadata for one user message."""
    text = user_message.strip()
    if not text:
        return PrefetchRoute()

    candidates = _collect_candidates(text)
    source = "regex"
    if not candidates and _hybrid_enabled():
        bm25 = _bm25_candidates(text)
        if bm25:
            candidates = bm25
            source = "bm25"
    if not candidates:
        return PrefetchRoute()

    active_names = {name for name, _ in candidates}
    blocked: set[str] = set()
    for name in sorted(active_names, key=lambda m: MODULE_PRIORITY.get(m, 0), reverse=True):
        for victim in BLOCKS.get(name, frozenset()):
            if victim not in active_names:
                continue
            if name == "personal" and victim == "web":
                if WEB_OVERRIDE.search(text):
                    continue
            blocked.add(victim)

    selected = [(n, c) for n, c in candidates if n not in blocked]
    selected.sort(key=lambda x: MODULE_PRIORITY.get(x[0], 0), reverse=True)
    modules = [n for n, _ in selected]
    module_confidence = {n: c for n, c in selected}
    max_conf = max(module_confidence.values(), default=0.0)

    return PrefetchRoute(
        modules=modules,
        session_first="session" in modules,
        confidence=max_conf,
        personal_path=_resolve_personal_path(text, modules),
        module_confidence=module_confidence,
        source=source,
    )
