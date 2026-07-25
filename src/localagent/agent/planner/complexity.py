"""Deterministic complexity gate for milestone planning."""

from __future__ import annotations

import re

from localagent import config

_CONNECTOR_RE = re.compile(
    r"(?:然后|接着|再|之后|并且|并|以及|and\s+then|finally|after\s+that)",
    re.IGNORECASE,
)
_ACTION_VERB_RE = re.compile(
    r"(?:找|搜|搜索|读|查看|改|修改|写|创建|添加|跑|运行|执行|测|测试|提交|部署|"
    r"find|search|read|modify|edit|write|create|add|run|test|deploy|fix|update)",
    re.IGNORECASE,
)
_FILE_PATH_RE = re.compile(
    r"(?:[\w./\\-]+\.(?:py|ts|js|json|yaml|yml|md|txt|toml|sh|go|rs|java|cpp|c|h)|"
    r"[\w./\\-]+/[\w./\\-]+)",
    re.IGNORECASE,
)
_FILE_ACTION_RE = re.compile(
    r"(?:修改|改|写|创建|添加|运行|测试|edit|write|create|run|test|fix|update)",
    re.IGNORECASE,
)
_COMPOUND_DELIVERABLE_RE = re.compile(
    r"(?:并(?:告诉|汇报|说明|返回|输出)|然后(?:告诉|汇报|说明|返回|输出)|"
    r"and\s+(?:tell|report|show|return))",
    re.IGNORECASE,
)
_MEMORY_RECALL_RE = re.compile(
    r"(?:记住|记下|记忆|回忆|问过|聊过|remember|recall|memory|who am i|我是谁)",
    re.IGNORECASE,
)
_WEB_ONLY_RE = re.compile(
    r"(?:天气|新闻|资讯|几点|weather|news|briefing|what time)",
    re.IGNORECASE,
)


def action_complexity_score(user_message: str) -> int:
    """Return a non-negative complexity score (higher → more likely multi-step action)."""
    text = (user_message or "").strip()
    if not text:
        return 0

    score = 0
    if _CONNECTOR_RE.search(text):
        score += 2
    verbs = _ACTION_VERB_RE.findall(text)
    if len(verbs) >= 2 and len(text) > 15:
        score += 2
    elif len(verbs) == 1 and _CONNECTOR_RE.search(text):
        score += 1
    if _FILE_PATH_RE.search(text) and _FILE_ACTION_RE.search(text):
        score += 2
    if _COMPOUND_DELIVERABLE_RE.search(text):
        score += 1
    return score


def should_use_milestone_mode(user_message: str) -> bool:
    """True when the message looks like a multi-step action task."""
    if not config.PLANNER_ENABLED or config.PLANNER_MODE == "off":
        return False
    if config.PLANNER_MODE == "always":
        return action_complexity_score(user_message) >= 1

    text = (user_message or "").strip()
    if not text:
        return False

    # Pure recall / web Q&A should stay on the simple path.
    if _MEMORY_RECALL_RE.search(text) and not _ACTION_VERB_RE.search(text):
        return False
    if _WEB_ONLY_RE.search(text) and not _FILE_PATH_RE.search(text):
        if action_complexity_score(text) < config.PLANNER_COMPLEXITY_THRESHOLD + 1:
            return False

    return action_complexity_score(text) >= config.PLANNER_COMPLEXITY_THRESHOLD


def has_action_intent(user_message: str) -> bool:
    """True when the message mentions an action verb but is below milestone threshold."""
    text = (user_message or "").strip()
    if not text:
        return False
    return bool(_ACTION_VERB_RE.search(text)) and not should_use_milestone_mode(text)
