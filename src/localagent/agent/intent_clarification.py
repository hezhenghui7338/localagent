"""Assess user intent clarity before full agent execution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from localagent import config
from localagent.models.router import ChatMessage, get_model_router

_ASSESSMENT_PROMPT = """你是 LocalAgent 的意图分析器。判断用户当前输入是否足够明确、可以安全执行。

意图**不明确**的典型信号：
- 指代不明（「改一下」「优化它」但未说明对象）
- 范围缺失（「分析一下」「写报告」但未说明对象、时间或格式）
- 多种合理解读且默认选择可能做错（浏览结构 vs 跑测试 vs 查 Git）
- 缺少执行所需的关键参数（哪个文件、哪个分支、什么标准）

意图**已明确**时直接放行，例如：
- 包含具体路径、文件名、命令、数字范围
- 简单寒暄、致谢、确认（「好的」「谢谢」）
- 结合近期对话上下文，指代已可解析
- 回顾当前/本次对话或今天自己问过什么（「我今天问了啥」「我们聊了什么」「总结一下刚才的对话」）

只输出 JSON，不要其他文字：
{"needs_clarification": true/false, "questions": ["问题1", "问题2"], "reasoning": "简短理由"}

规则：
- needs_clarification=false 时 questions 必须为 []
- needs_clarification=true 时 questions 最多 2 条，具体、简短、可直接回答
- 宁可少问：若上下文已足够或问题足够具体，不要过度追问
"""

_SKIP_ASSESSMENT = re.compile(
    r"^(谢谢|感谢|好的|嗯|ok|yes|no|你好|嗨|hello|hi)$",
    re.IGNORECASE,
)

_SPECIFIC_PATH = re.compile(
    r"(?:^|[\s/])(?:[\w.-]+/)+[\w.-]+\.(?:py|js|ts|tsx|md|yaml|yml|json|toml|txt|sh)\b",
    re.IGNORECASE,
)

_SESSION_RECALL_QUERY = re.compile(
    r"(?:"
    r"(?:今[天日]|刚才|上面|本次|这场|当前|我们|咱俩)"
    r".{0,15}?"
    r"(?:问|说|聊|讨论|提到)"
    r".{0,8}?"
    r"(?:啥|什么|哪些|内容)"
    r"|"
    r"(?:对话|聊天|会话)"
    r".{0,12}?"
    r"(?:回顾|总结|历史|记录)"
    r"|"
    r"(?:回顾|总结)"
    r".{0,12}?"
    r"(?:对话|聊天|今天|本次)"
    r")",
    re.IGNORECASE,
)

_JSON_BLOCK = re.compile(r"\{[^{}]*\}", re.DOTALL)


@dataclass
class IntentAssessment:
    needs_clarification: bool
    questions: list[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class PendingClarification:
    original_message: str


def is_session_recall_query(user_message: str) -> bool:
    """True when the user wants to review current or past chat history."""
    return bool(_SESSION_RECALL_QUERY.search(user_message.strip()))


def should_skip_intent_assessment(user_message: str) -> bool:
    """Fast-path: skip LLM pre-check for obviously clear or trivial input."""
    text = user_message.strip()
    if not text:
        return True
    if text.startswith(":"):
        return True
    if len(text) <= 3:
        return True
    if _SKIP_ASSESSMENT.match(text):
        return True
    if _SPECIFIC_PATH.search(text):
        return True
    if is_session_recall_query(text):
        return True
    return False


def _format_history(history: list[dict[str, str]] | None, *, limit: int = 6) -> str:
    if not history:
        return "（无近期对话）"
    lines: list[str] = []
    for msg in history[-limit:]:
        role = "用户" if msg.get("role") == "user" else "助手"
        content = (msg.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "（无近期对话）"


def _parse_assessment(raw: str) -> IntentAssessment | None:
    text = raw.strip()
    if text.startswith("{"):
        candidates = [text]
    else:
        candidates = [match.group(0) for match in _JSON_BLOCK.finditer(text)]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        needs = bool(data.get("needs_clarification"))
        questions = data.get("questions") or []
        if not isinstance(questions, list):
            questions = []
        cleaned = [str(q).strip() for q in questions if str(q).strip()]
        return IntentAssessment(
            needs_clarification=needs,
            questions=cleaned[:2],
            reasoning=str(data.get("reasoning") or "").strip(),
        )
    return None


def assess_intent(
    user_message: str,
    history: list[dict[str, str]] | None = None,
    *,
    provider: str = "auto",
    session_id: str | None = None,
) -> IntentAssessment:
    """Lightweight pre-turn intent check via a short LLM call."""
    if not config.INTENT_CLARIFY_ENABLED or should_skip_intent_assessment(user_message):
        return IntentAssessment(needs_clarification=False)

    router = get_model_router()
    prefer = None if provider == "auto" else provider
    context = _format_history(history)
    user_block = (
        f"近期对话:\n{context}\n\n"
        f"当前用户输入:\n{user_message.strip()}\n\n"
        "请判断是否需要澄清。"
    )
    messages = [
        ChatMessage(role="system", content=_ASSESSMENT_PROMPT),
        ChatMessage(role="user", content=user_block),
    ]
    try:
        raw = router.chat(
            messages,
            temperature=0.1,
            prefer=prefer,
            usage_command="intent_assess",
            session_id=session_id,
        )
    except Exception:
        return IntentAssessment(needs_clarification=False)

    parsed = _parse_assessment(raw)
    if parsed is None:
        return IntentAssessment(needs_clarification=False)
    if parsed.needs_clarification and not parsed.questions:
        return IntentAssessment(needs_clarification=False, reasoning=parsed.reasoning)
    return parsed


def format_clarification_response(assessment: IntentAssessment) -> str:
    """Render clarification questions for the user."""
    lines = ["在继续之前，我想先确认你的意图：", ""]
    for index, question in enumerate(assessment.questions, start=1):
        lines.append(f"{index}. {question}")
    lines.extend(["", "请补充说明，我会据此继续处理。"])
    return "\n".join(lines)


def merge_clarified_intent(original: str, clarification: str) -> str:
    """Combine the original ask with the user's follow-up clarification."""
    original_text = original.strip()
    clarification_text = clarification.strip()
    if not original_text:
        return clarification_text
    if not clarification_text:
        return original_text
    return (
        "[用户原始问题]\n"
        f"{original_text}\n\n"
        "[用户澄清补充]\n"
        f"{clarification_text}"
    )
