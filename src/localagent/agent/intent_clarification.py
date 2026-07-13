"""Assess user intent clarity before full agent execution."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from localagent import config
from localagent.models.router import ChatMessage, get_model_router

_ASSESSMENT_PROMPT = """你是 LocalAgent 的意图分析器。判断用户当前输入是否足够明确、可以安全执行。

意图**不明确**的典型信号（仅这些才追问）：
- 指代不明（「改一下」「优化它」但未说明对象，且上下文也无法推断）
- 会改动文件/系统，但缺少目标文件、改动内容或标准，默认选择可能做错
- 多种合理解读且选错代价高（例如不知是重构、修 bug 还是只读分析）

意图**已明确**时必须放行，例如：
- 「当前项目 / 本仓库 / 工作区 / LocalAgent」即默认范围，不要再问是哪个项目
- 统计/计算代码行数、列目录、跑测试、搜索关键字等动作+对象清晰的请求
- 包含具体路径、文件名、命令、数字范围
- 简单寒暄、致谢、确认（「好的」「谢谢」）
- 结合近期对话上下文，指代已可解析
- 回顾当前/本次对话或今天自己问过什么
- 询问已记住的个人信息（住址、姓名、偏好等）——应直接查记忆，不要追问授权或获取方式
- 「记住 / 记录一下」类写入指令

只输出 JSON，不要其他文字：
{"needs_clarification": true/false, "questions": ["问题1", "问题2"], "reasoning": "简短理由"}

规则：
- needs_clarification=false 时 questions 必须为 []
- needs_clarification=true 时 questions 最多 2 条，具体、简短、可直接回答
- 默认倾向放行：只有真可能做错时才澄清；宁可少问，不要过度追问
"""

_SKIP_ASSESSMENT = re.compile(
    r"^(谢谢|感谢|好的|嗯|ok|yes|no|你好|嗨|hello|hi)$",
    re.IGNORECASE,
)

_SPECIFIC_PATH = re.compile(
    r"(?:^|[\s/])(?:[\w.-]+/)+[\w.-]+\.(?:py|js|ts|tsx|md|yaml|yml|json|toml|txt|sh)\b",
    re.IGNORECASE,
)

# Clear workspace/read-only actions — no need to ask "which project?"
_CLEAR_ACTION = re.compile(
    r"(?:"
    r"(?:统计|计算|查一下|看看|列出|显示|给我).{0,16}?"
    r"(?:代码行数|行数|代码量|文件数|有多少(?:个)?(?:文件|行)|loc)"
    r"|"
    r"(?:当前|本|这个|该|LocalAgent|localagent).{0,10}?(?:项目|仓库|工作区|目录|代码库)"
    r"|"
    r"(?:运行|执行|跑).{0,24}?(?:测试|pytest|单元测试|命令|脚本|构建|build)"
    r"|"
    r"(?:搜索|查找|找出|grep).{0,24}?(?:TODO|FIXME|文件|函数|类|关键字)"
    r"|"
    r"(?:git\s+(?:status|log|diff)|未提交|最近(?:改了|提交)|工作区状态)"
    r")",
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
    if _CLEAR_ACTION.search(text):
        return True
    if is_session_recall_query(text):
        return True
    # Personal memory / identity questions should recall, not ask for authorization.
    if re.search(
        r"你知道我|我是谁|我住|住在哪|居住|住址|我的名字|关于我|记住|记录一下|记下",
        text,
    ):
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
    on_status: Callable[[str], None] | None = None,
) -> IntentAssessment:
    """Lightweight pre-turn intent check via a short LLM call."""
    if not config.INTENT_CLARIFY_ENABLED or should_skip_intent_assessment(user_message):
        return IntentAssessment(needs_clarification=False)

    if on_status is not None:
        on_status("分析意图…")

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
