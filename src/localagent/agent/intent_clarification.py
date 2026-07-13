"""Assess user intent clarity before full agent execution.

Policy (ask vs act): interrupt as little as possible.
- act: clear enough → proceed
- assume: mild ambiguity, reversible → proceed with stated assumptions
- clarify: missing detail would materially change a high-cost action → ask once
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from localagent import config
from localagent.models.router import ChatMessage, get_model_router

_ASSESSMENT_PROMPT = """你是 LocalAgent 的意图分析器。第一原则：**少打扰用户**——该做时直接做，只有不得不问时才追问。

请在三种 mode 中选一：

1. **act**（默认）：意图已足够执行，直接放行。包括但不限于：
   - 「当前项目 / 本仓库 / 工作区 / LocalAgent」即默认范围
   - 统计行数、列目录、搜索、跑测试等读操作
   - 含具体路径、文件名、命令、数字范围
   - 寒暄、致谢、确认
   - 结合近期对话，指代已可解析
   - 回顾当前/本次对话
   - **询问已记住的个人事实/偏好**（住址、姓名、「我喜欢喝什么」「我喜欢什么」等）——直接查记忆，禁止追问口味、推荐或菜单
   - 「记住 / 记录一下」类写入指令

2. **assume**：轻微模糊，但可安全默认、做错可逆。放行并给出 1–2 条简短假设（执行层会按假设推进并告知用户）。例如：
   - 「看看项目」→ 假设先列目录结构
   - 「整理一下」且上下文能猜到对象 → 说明假设对象

3. **clarify**（严格少用）：**仅当**缺失信息会实质改变结果，且选错代价高（改文件/跑危险命令/多种互斥目标）时才用。例如：
   - 「改一下」「优化它」——无对象且上下文无法推断
   - 要写文件但缺路径与改动内容
   - 多种合理解读且选错会做错副作用

只输出 JSON，不要其他文字：
{"mode":"act"|"assume"|"clarify","assumptions":["..."],"questions":["..."],"risk":"low"|"high","reasoning":"简短理由"}

规则：
- 默认 mode=act；拿不准时优先 assume，而不是 clarify
- mode=act 时 assumptions 与 questions 都必须为 []
- mode=assume 时 assumptions 1–2 条，questions 必须为 []
- mode=clarify 时 questions 最多 1 条（具体、可直接回答），assumptions 为 []
- 个人偏好/记忆类问题一律 act，禁止当成推荐或点餐场景追问
- 读操作、可逆操作：即使略模糊也 act 或 assume，不要 clarify
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

# Personal facts / preferences → recall memory, never clarify as "recommendation".
_PERSONAL_MEMORY_QUERY = re.compile(
    r"(?:"
    r"你知道我|我是谁|我住|住在哪|居住|住址|我的名字|关于我|"
    r"记住|记录一下|记下|"
    r"我喜欢(?:喝|吃|听|看|玩)?.{0,6}(?:什么|啥)|"
    r"我(?:爱|偏好).{0,8}(?:什么|啥)|"
    r"我的(?:偏好|喜好|口味|经历|职业|身份|家庭)|"
    r"我(?:平时)?喜欢什么"
    r")"
)

_JSON_BLOCK = re.compile(r"\{[^{}]*\}", re.DOTALL)

_VALID_MODES = frozenset({"act", "assume", "clarify"})


@dataclass
class IntentAssessment:
    mode: str = "act"  # act | assume | clarify
    questions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    reasoning: str = ""
    risk: str = "low"  # low | high

    def __post_init__(self) -> None:
        if self.mode not in _VALID_MODES:
            self.mode = "act"
        if self.risk not in {"low", "high"}:
            self.risk = "low"

    @property
    def needs_clarification(self) -> bool:
        return self.mode == "clarify"


@dataclass
class PendingClarification:
    original_message: str


def is_session_recall_query(user_message: str) -> bool:
    """True when the user wants to review current or past chat history."""
    return bool(_SESSION_RECALL_QUERY.search(user_message.strip()))


def is_personal_memory_query(user_message: str) -> bool:
    """True when the user is asking about remembered personal facts/preferences."""
    return bool(_PERSONAL_MEMORY_QUERY.search(user_message.strip()))


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
    if is_personal_memory_query(text):
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


def _normalize_mode(data: dict) -> str:
    raw_mode = str(data.get("mode") or "").strip().lower()
    if raw_mode in _VALID_MODES:
        return raw_mode
    # Legacy binary schema from older prompts / cached models.
    if "needs_clarification" in data:
        return "clarify" if data.get("needs_clarification") else "act"
    return "act"


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
        mode = _normalize_mode(data)
        questions = data.get("questions") or []
        if not isinstance(questions, list):
            questions = []
        assumptions = data.get("assumptions") or []
        if not isinstance(assumptions, list):
            assumptions = []
        cleaned_q = [str(q).strip() for q in questions if str(q).strip()]
        cleaned_a = [str(a).strip() for a in assumptions if str(a).strip()]
        return IntentAssessment(
            mode=mode,
            questions=cleaned_q[:1] if mode == "clarify" else cleaned_q[:2],
            assumptions=cleaned_a[:2],
            reasoning=str(data.get("reasoning") or "").strip(),
            risk=str(data.get("risk") or "low").strip().lower(),
        )
    return None


def _coerce_assessment(parsed: IntentAssessment) -> IntentAssessment:
    """Enforce mode invariants; prefer less interruption on inconsistent output."""
    if parsed.mode == "clarify" and not parsed.questions:
        # Clarify without a question → fail soft: assume if we have hints, else act.
        if parsed.assumptions:
            return IntentAssessment(
                mode="assume",
                assumptions=parsed.assumptions,
                reasoning=parsed.reasoning or "clarify 无问题，降级为 assume",
                risk=parsed.risk,
            )
        return IntentAssessment(
            mode="act",
            reasoning=parsed.reasoning or "clarify 无问题，降级为 act",
            risk=parsed.risk,
        )
    if parsed.mode == "assume" and not parsed.assumptions:
        return IntentAssessment(
            mode="act",
            reasoning=parsed.reasoning or "assume 无假设，降级为 act",
            risk=parsed.risk,
        )
    if parsed.mode == "act":
        return IntentAssessment(
            mode="act",
            reasoning=parsed.reasoning,
            risk=parsed.risk,
        )
    if parsed.mode == "clarify":
        return IntentAssessment(
            mode="clarify",
            questions=parsed.questions[:1],
            reasoning=parsed.reasoning,
            risk=parsed.risk,
        )
    return IntentAssessment(
        mode="assume",
        assumptions=parsed.assumptions[:2],
        reasoning=parsed.reasoning,
        risk=parsed.risk,
    )


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
        return IntentAssessment(mode="act")

    if on_status is not None:
        on_status("分析意图…")

    router = get_model_router()
    prefer = None if provider == "auto" else provider
    context = _format_history(history)
    user_block = (
        f"近期对话:\n{context}\n\n"
        f"当前用户输入:\n{user_message.strip()}\n\n"
        "请选择 mode（优先 act，其次 assume，严格少用 clarify）。"
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
        return IntentAssessment(mode="act")

    parsed = _parse_assessment(raw)
    if parsed is None:
        return IntentAssessment(mode="act")
    return _coerce_assessment(parsed)


def format_clarification_response(assessment: IntentAssessment) -> str:
    """Render clarification questions for the user."""
    lines = ["在继续之前，我想先确认你的意图：", ""]
    for index, question in enumerate(assessment.questions, start=1):
        lines.append(f"{index}. {question}")
    lines.extend(["", "请补充说明，我会据此继续处理。"])
    return "\n".join(lines)


def format_assumed_intent(user_message: str, assumptions: list[str]) -> str:
    """Inject stated assumptions so the agent can proceed without interrupting."""
    text = user_message.strip()
    cleaned = [a.strip() for a in assumptions if a.strip()]
    if not cleaned:
        return text
    lines = [
        "[用户问题]",
        text,
        "",
        "[执行假设（请按此理解推进，并在回复开头用一句话说明假设）]",
    ]
    lines.extend(f"- {item}" for item in cleaned)
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
