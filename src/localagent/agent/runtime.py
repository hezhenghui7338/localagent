"""LangGraph agent runtime."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from localagent.memory.core_profile import load_core_profile
from localagent.models.router import ChatMessage, get_model_router
from localagent.tools import TOOL_DEFINITIONS, execute_tool


class AgentState(TypedDict):
    messages: list[dict[str, str]]
    tool_calls: list[dict[str, Any]]
    final_response: str


SYSTEM_PROMPT = """你是 LocalAgent，用户的本地 AI 个人助手。你可访问本地记忆库（长期记忆）和知识库。

原则：
1. 优先回答用户当前问题，记忆和知识仅作补充
2. 涉及个人历史或记忆库内容时，调用 search_memory（若下方已预加载个人上下文则直接回答，禁止再调用工具）
   - 浏览记忆库、按标签/时间/主题查看记忆时，调用 query_memories
   - 已预加载的记忆检索结果即最终依据，不要声称「未找到」后再输出工具 JSON
3. 需要文档原文时，调用 search_knowledge（同样会在索引未命中时回退到文档原文）
4. 涉及时效性/外部信息时，调用 web_search（若下方已预加载联网结果则直接回答）
5. 涉及工作区、Git、最近改了什么、待办任务时，调用 workspace_context（若下方已预加载则直接回答）
6. 需要执行终端命令（统计代码行数、列目录、运行测试/构建、查看文件内容等）时，调用 run_shell，不要只告诉用户去手动运行
7. 回答简洁、准确，引用来源

可用工具（以 JSON 格式请求）：
{tools}

如需调用工具，回复格式：
```tool
{{"name": "tool_name", "arguments": {{"query": "..."}}}}
```
否则直接回答。
"""

_PERSONAL_QUERY = re.compile(
    r"我是谁|我叫什么|我的名字|你知道我|关于我|我的身份|我的职业|我是做什么|我喜欢什么|我的经历|"
    r"我的家庭|家庭成员|家人|父母|孩子|儿子|女儿|妻子|老公|老婆|亲属"
)

_MEMORY_BROWSE_QUERY = re.compile(
    r"记忆库|记忆里|我的记忆|记住了什么|记得什么|存了什么|"
    r"有什么有趣|有什么东西|你还记得|你记得我|"
    r"你对我(的)?了解|知道我什么|有什么记忆|"
    r"深入搜索|深度搜索|深度检索|仔细搜索|全面搜索|搜索记忆"
)

_FAMILY_QUERY = re.compile(
    r"家庭|家人|父母|父亲|母亲|爸爸|妈妈|孩子|儿子|女儿|妻子|老公|老婆|配偶|亲属|结婚|已婚"
)

_WEB_QUERY = re.compile(
    r"新闻|时事|头条|热点|快讯|发生什么|"
    r"最近|最新|今日|今天|昨天|本周|近期|当下|"
    r"股价|汇率|天气|"
    r"联网搜索|网上搜|搜索一下|web\s*search|"
    r"news|latest|recent|today|breaking",
    re.IGNORECASE,
)

_WORKSPACE_QUERY = re.compile(
    r"我最近|最近干|改了什么|文件变|工作区|工作目录|"
    r"git|提交|commit|分支|未提交|待办|todo|TODO|"
    r"做了什么|进度怎样|项目状态",
    re.IGNORECASE,
)


@dataclass
class AgentResult:
    response: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


_TOOL_LABELS = {
    "search_memory": "搜索记忆",
    "search_knowledge": "搜索知识库",
    "reflect_memory": "推理记忆",
    "web_search": "联网搜索",
    "workspace_context": "工作区上下文",
    "query_memories": "查询记忆库",
    "run_shell": "执行命令",
}

_TOOL_FENCE = re.compile(r"```(?:tool|json)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
_KNOWN_TOOLS = frozenset(_TOOL_LABELS)


def _parse_tool_call(text: str) -> dict[str, Any] | None:
    """Parse a tool-call payload from model output.

    Small local models often emit ```json instead of the documented ```tool fence.
    """
    candidates: list[str] = []
    for match in _TOOL_FENCE.finditer(text):
        block = match.group(1).strip()
        if block:
            candidates.append(block)

    stripped = text.strip()
    if stripped.startswith("{"):
        candidates.append(stripped)

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("name") in _KNOWN_TOOLS:
            return data
    return None


def _strip_tool_blocks(text: str) -> str:
    """Remove tool-call fences and bare tool JSON from model output."""
    cleaned = _TOOL_FENCE.sub("", text)
    stripped = cleaned.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and data.get("name") in _KNOWN_TOOLS:
                return ""
        except json.JSONDecodeError:
            pass
    return cleaned.strip()


def _prefetch_personal_context(user_message: str) -> str:
    """Load profile + memory upfront for identity/browse/topic questions."""
    browse = bool(_MEMORY_BROWSE_QUERY.search(user_message))
    personal = bool(_PERSONAL_QUERY.search(user_message))
    family = bool(_FAMILY_QUERY.search(user_message))
    if not browse and not personal and not family:
        return ""
    from localagent.tools import query_memories_tool, search_memory

    profile = load_core_profile().format_for_prompt()
    memory_parts: list[str] = []

    if family:
        memory_parts.append(
            query_memories_tool(
                query="家庭 家人 父母 孩子 妻子",
                tags=["家庭"],
                sort="relevance",
                limit=25,
            )
        )
        memory_parts.append(
            search_memory(
                "家庭 家人 父母 孩子 妻子 老公 老婆",
                top_k=10,
                fallback=False,
            )
        )
    elif browse:
        memory_parts.append(
            query_memories_tool(
                query=user_message,
                sort="relevance" if len(user_message.strip()) > 4 else "newest",
                limit=25,
            )
        )
    else:
        memory_parts.append(search_memory(user_message, top_k=10))

    memory = "\n\n".join(part for part in memory_parts if part)
    lines = [
        "[个人上下文（已预加载，请直接据此回答，勿再调用 search_memory / query_memories）]",
        profile,
        f"记忆检索:\n{memory}",
    ]
    return "\n".join(lines)


def _prefetch_web_context(user_message: str) -> str:
    """Run web search upfront for time-sensitive questions (avoids relying on small models)."""
    if not _WEB_QUERY.search(user_message):
        return ""
    if _WORKSPACE_QUERY.search(user_message) and not re.search(
        r"新闻|时事|头条|热点|天气|股价", user_message
    ):
        return ""
    from localagent.tools import web_search

    result = web_search(user_message)
    if result.startswith("联网搜索未配置"):
        return ""
    lines = ["[联网搜索结果（已预加载，直接回答，勿再调用 web_search）]", result]
    return "\n".join(lines)


def _prefetch_workspace_context(user_message: str) -> str:
    if not _WORKSPACE_QUERY.search(user_message):
        return ""
    from localagent.tools import workspace_context_tool

    result = workspace_context_tool(days=7)
    return "\n".join(
        [
            "[工作区上下文（已预加载，直接回答，勿再调用 workspace_context）]",
            result,
        ]
    )


def _build_system_prompt(
    *,
    personal_context: str = "",
    web_context: str = "",
    workspace_context: str = "",
) -> str:
    tools_desc = json.dumps(TOOL_DEFINITIONS, ensure_ascii=False, indent=2)
    profile = load_core_profile().format_for_prompt()
    prompt = f"{SYSTEM_PROMPT.format(tools=tools_desc)}\n\n{profile}"
    if personal_context:
        prompt = f"{prompt}\n\n{personal_context}"
    if web_context:
        prompt = f"{prompt}\n\n{web_context}"
    if workspace_context:
        prompt = f"{prompt}\n\n{workspace_context}"
    return prompt



def run_agent_turn(
    user_message: str,
    history: list[dict[str, str]] | None = None,
    *,
    provider: str = "auto",
    session_id: str | None = None,
    on_status: Callable[[str], None] | None = None,
    on_token: Callable[[str], None] | None = None,
) -> AgentResult:
    """Run one agent turn with up to 3 tool iterations."""
    router = get_model_router()
    prefer = None if provider == "auto" else provider

    def _status(message: str) -> None:
        if on_status is not None:
            on_status(message)

    _status(f"连接模型 ({router.format_provider_hint(provider)})…")
    personal_context = _prefetch_personal_context(user_message)
    if personal_context:
        _status("预加载个人记忆…")
    web_context = _prefetch_web_context(user_message)
    if web_context:
        _status("联网搜索…")
    workspace_ctx = _prefetch_workspace_context(user_message)
    if workspace_ctx:
        _status("加载工作区上下文…")
    messages = [
        ChatMessage(
            role="system",
            content=_build_system_prompt(
                personal_context=personal_context,
                web_context=web_context,
                workspace_context=workspace_ctx,
            ),
        )
    ]
    if history:
        for msg in history[-10:]:
            messages.append(ChatMessage(role=msg["role"], content=msg["content"]))
    messages.append(ChatMessage(role="user", content=user_message))

    tool_calls: list[dict[str, Any]] = []
    reply = ""
    for iteration in range(3):
        if iteration == 0:
            _status("生成回复…")
        else:
            _status(f"综合工具结果 (第 {iteration + 1} 轮)…")

        # Do not stream intermediate turns: tool calls may follow partial prose.
        reply = router.chat(
            messages,
            temperature=0.3,
            prefer=prefer,
            on_token=None,
            usage_command="chat",
            session_id=session_id,
        )
        call = _parse_tool_call(reply)
        if not call:
            clean = _strip_tool_blocks(reply)
            return AgentResult(response=clean, tool_calls=tool_calls)

        tool_name = call.get("name", "")
        tool_label = _TOOL_LABELS.get(tool_name, tool_name or "工具")
        arguments = call.get("arguments", {}) or {}
        query = arguments.get("query", "") or arguments.get("command", "")
        if query:
            preview = query if len(query) <= 40 else f"{query[:40]}…"
            _status(f"调用 {tool_label}: {preview}")
        else:
            _status(f"调用 {tool_label}…")

        tool_calls.append(call)
        result = execute_tool(tool_name, arguments)
        messages.append(ChatMessage(role="assistant", content=reply))
        messages.append(ChatMessage(role="user", content=f"工具结果:\n{result}\n请基于结果回答用户。"))

    return AgentResult(response=_strip_tool_blocks(reply), tool_calls=tool_calls)


def build_agent_graph():
    """Build LangGraph for session persistence (requires [full] extras)."""
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        raise ImportError("安装完整依赖: pip install -e '.[full]'") from exc

    def call_model(state: AgentState) -> AgentState:
        last_user = ""
        for msg in reversed(state["messages"]):
            if msg["role"] == "user":
                last_user = msg["content"]
                break
        result = run_agent_turn(last_user, state["messages"][:-1])
        state["final_response"] = result.response
        state["tool_calls"] = result.tool_calls
        state["messages"].append({"role": "assistant", "content": result.response})
        return state

    graph = StateGraph(AgentState)
    graph.add_node("call_model", call_model)
    graph.set_entry_point("call_model")
    graph.add_edge("call_model", END)
    return graph
