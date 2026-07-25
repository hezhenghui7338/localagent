"""BM25-based action tool routing."""

from __future__ import annotations

import re
from typing import Any

from localagent import config
from localagent.knowledge.bm25_store import tokenize
from localagent.mcp.tool_registry import get_tool_definitions

_ACTION_TOOL_NAMES = frozenset(
    {
        "read_file",
        "edit_file",
        "write_file",
        "glob",
        "grep",
        "run_shell",
        "workspace_context",
        "workspace_task",
        "summarize_document",
    }
)
_SIDE_EFFECT_TOOLS = frozenset({"run_shell", "write_file", "edit_file"})
_SIDE_EFFECT_HINT_RE = re.compile(
    r"(?:改|修改|写|创建|添加|跑|运行|执行|测|测试|提交|部署|"
    r"edit|write|create|run|test|deploy|fix|append|overwrite)",
    re.IGNORECASE,
)
def _all_tool_definitions() -> list[dict[str, Any]]:
    return get_tool_definitions()


_BY_NAME: dict[str, dict[str, Any]] = {}


def _tool_corpus(tool: dict[str, Any]) -> str:
    name = str(tool.get("name") or "")
    desc = str(tool.get("description") or "")
    params = tool.get("parameters") or {}
    if isinstance(params, dict):
        param_text = " ".join(str(k) for k in params)
    else:
        param_text = str(params)
    return f"{name} {desc} {param_text}"


def _bm25_scores(query: str, docs: list[str]) -> list[float]:
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        # Fallback: simple token overlap count.
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


def route_action_tools(
    query: str,
    *,
    milestone_objective: str = "",
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Return top-K action tool definitions for the query (+ milestone hint)."""
    all_tools = _all_tool_definitions()
    global _BY_NAME
    _BY_NAME = {t["name"]: t for t in all_tools}
    k = top_k if top_k is not None else getattr(config, "PLANNER_TOOL_TOP_K", 7)
    k = max(3, min(k, len(all_tools)))

    combined = f"{query} {milestone_objective}".strip()
    action_tools = [t for t in all_tools if t["name"] in _ACTION_TOOL_NAMES]
    if not action_tools:
        return all_tools[:k]

    corpora = [_tool_corpus(t) for t in action_tools]
    scores = _bm25_scores(combined, corpora)
    ranked = sorted(
        zip(scores, action_tools, strict=False),
        key=lambda x: x[0],
        reverse=True,
    )

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(tool: dict[str, Any]) -> None:
        name = str(tool.get("name") or "")
        if name and name not in seen:
            seen.add(name)
            selected.append(tool)

    for _score, tool in ranked:
        if len(selected) >= k:
            break
        _add(tool)

    # Ensure side-effect tools when the milestone implies mutation/execution.
    hint = f"{query} {milestone_objective}"
    if _SIDE_EFFECT_HINT_RE.search(hint):
        for name in _SIDE_EFFECT_TOOLS:
            if len(selected) >= k:
                break
            tool = _BY_NAME.get(name)
            if tool:
                _add(tool)

    # Always include read_file for action chains (common first step).
    read_tool = _BY_NAME.get("read_file")
    if read_tool:
        _add(read_tool)

    return selected[:k] if selected else action_tools[:k]


def select_tools_for_turn(
    user_message: str,
    *,
    milestone_mode: bool = False,
    milestone_objective: str = "",
) -> list[dict[str, Any]]:
    """Pick tool definitions for a turn (subset in milestone mode or when configured)."""
    if milestone_mode or getattr(config, "PLANNER_TOOL_SUBSET", False):
        return route_action_tools(
            user_message,
            milestone_objective=milestone_objective,
        )
    return _all_tool_definitions()
