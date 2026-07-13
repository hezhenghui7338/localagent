"""LangGraph agent runtime."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from localagent.agent.intent_clarification import is_session_recall_query
from localagent.memory.core_profile import load_core_profile
from localagent.models.router import ChatMessage, get_model_router
from localagent.tools import TOOL_DEFINITIONS, execute_tool


class AgentState(TypedDict):
    messages: list[dict[str, str]]
    tool_calls: list[dict[str, Any]]
    final_response: str


SYSTEM_PROMPT = """你是 LocalAgent，用户的本地 AI 个人助手。你可访问本地记忆库（长期记忆）和知识库。

原则：
0. 仅在真正无法安全执行时才澄清（例如缺文件路径或改动内容）；「当前项目/本仓库/工作区」已足够定位，不要再问是哪个项目。统计行数、列目录、搜索、跑测试等读操作直接执行
1. 优先回答用户当前问题，记忆和知识仅作补充
2. 用户明确要求「记住 / 记录一下 / 记下」某事实时，必须立即调用 retain_memory 写入长期记忆，不要只口头答应
3. 涉及个人历史或记忆库内容时，调用 search_memory（若下方已预加载个人上下文则直接回答，禁止再调用工具）
   - 浏览记忆库、按标签/时间/主题查看记忆时，调用 query_memories
   - 已预加载的记忆检索结果即最终依据，不要声称「未找到」后再输出工具 JSON
   - 最近写入的个人事实优先级最高；若预加载结果含住址/偏好等短事实，直接采信
4. 需要文档原文时，调用 search_knowledge（同样会在索引未命中时回退到文档原文）
5. 涉及时效性/外部信息时，调用 web_search（若下方已预加载联网结果则直接回答）
6. 涉及工作区、Git、最近改了什么、待办任务时，调用 workspace_context（若下方已预加载则直接回答）
7. 需要创建、修改、写入或删除工作区文件时，必须调用 write_file（推荐）或 run_shell；禁止在未实际调用工具的情况下声称已完成文件操作
8. 需要执行其他终端命令（统计代码行数、列目录、运行测试/构建、查看文件内容等）时，调用 run_shell，不要只告诉用户去手动运行
9. 回答简洁、准确，引用来源

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
    r"我的家庭|家庭成员|家人|父母|孩子|儿子|女儿|妻子|老公|老婆|亲属|"
    r"住在哪|住哪|居住|住址|家在哪|位于哪|在哪里住|我住哪"
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

_LOCATION_QUERY = re.compile(
    r"住在哪|住哪|居住|住址|家在哪|位于哪|在哪里住|我住哪|住在哪里"
)

_EXPLICIT_REMEMBER = re.compile(
    r"^(?:请)?(?:帮我)?(?:记录一下|记住一下|记住|记下|记一下)[:：\s]*(.+)$",
    re.DOTALL,
)

_WEB_QUERY = re.compile(
    r"新闻|时事|头条|热点|快讯|发生什么|"
    r"最近|最新|今日|今天|昨天|本周|近期|当下|现在|"
    r"几点(?:了|钟)?|当前时间|现在时间|今天几号|今天日期|今天是几号|"
    r"股价|汇率|天气|"
    r"联网搜索|网上搜|搜索一下|web\s*search|"
    r"news|latest|recent|today|breaking|"
    r"what\s*time|current\s*time",
    re.IGNORECASE,
)

_WORKSPACE_QUERY = re.compile(
    r"我最近|最近干|改了什么|文件变|工作区|工作目录|"
    r"git|提交|commit|分支|未提交|待办|todo|TODO|"
    r"做了什么|进度怎样|项目状态",
    re.IGNORECASE,
)

_FILE_ACTION_QUERY = re.compile(
    r"内容写|写入|写到|写进|修改|更新|创建|新建|追加|改成|改为|保存到|"
    r"文件内容(?:增加|改为)|"
    r"帮.*(?:写|改|创建|新建)|新增.*文件|创建.*文件|"
    r"write\s+(?:to|into)|create\s+\S+\s*file|update\s+\S+\s*file",
    re.IGNORECASE,
)

_FILE_DIRECT_WRITE = re.compile(
    r"(?:内容写|追加内容|写入|写到|文件内容(?:增加|改为))[:：]",
    re.IGNORECASE,
)

_FILE_CLARIFICATION = re.compile(
    r"请(告诉|提供|说明|补充|确认)|需要确认|尚未提供|无法直接|哪个文件|"
    r"什么内容|如何改动|请补充",
    re.IGNORECASE,
)

_CLAIMS_FILE_DONE = re.compile(
    r"已(为|经)?(你)?(成功)?(将)?(创建|新建|更新|修改|写入|删除|保存|追加)|"
    r"已成功|"
    r"追加到.*文件|"
    r"文件.*(已|已经).*(创建|更新|修改|写入|追加)|"
    r"当前(?:文件)?(?:完整)?内容为",
    re.IGNORECASE,
)

_FILE_MUTATION_TOOLS = frozenset({"run_shell", "write_file"})


@dataclass
class AgentResult:
    response: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


_TOOL_LABELS = {
    "retain_memory": "写入记忆",
    "search_memory": "搜索记忆",
    "search_knowledge": "搜索知识库",
    "reflect_memory": "推理记忆",
    "web_search": "联网搜索",
    "workspace_context": "工作区上下文",
    "query_memories": "查询记忆库",
    "run_shell": "执行命令",
    "write_file": "写入文件",
}

_TOOL_FENCE = re.compile(r"```(?:tool|json)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
# Small models often hit num_predict mid-fence and never close ```.
_UNCLOSED_TOOL_FENCE = re.compile(r"```(?:tool|json)\b[\s\S]*$", re.IGNORECASE)
_TOOL_CALL_XML = re.compile(
    r"<tool_call>\s*(\w+)(.*?)(?:</tool_call>|$)",
    re.DOTALL | re.IGNORECASE,
)
_TOOL_ARG_XML = re.compile(
    r"<arg_key>(.*?)</arg_key>\s*<arg_value>(.*?)</arg_value>",
    re.DOTALL,
)
_KNOWN_TOOLS = frozenset(_TOOL_LABELS)


def _parse_xml_tool_call(text: str) -> dict[str, Any] | None:
    """Parse <tool_call>name<arg_key>k</arg_key><arg_value>v</arg_value></tool_call>."""
    match = _TOOL_CALL_XML.search(text)
    if not match:
        return None
    name = match.group(1)
    if name not in _KNOWN_TOOLS:
        return None
    arguments: dict[str, Any] = {}
    for key, value in _TOOL_ARG_XML.findall(match.group(2)):
        arguments[key.strip()] = value.strip()
    return {"name": name, "arguments": arguments}


def _parse_tool_call(text: str) -> dict[str, Any] | None:
    """Parse a tool-call payload from model output.

    Small local models often emit ```json instead of the documented ```tool fence.
    Cloud free models may emit XML-style <tool_call> blocks.
    """
    xml_call = _parse_xml_tool_call(text)
    if xml_call:
        return xml_call

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
    """Remove tool-call fences, XML blocks, and bare tool JSON from model output."""
    cleaned = _TOOL_CALL_XML.sub("", text)
    cleaned = _TOOL_FENCE.sub("", cleaned)
    cleaned = _UNCLOSED_TOOL_FENCE.sub("", cleaned)
    stripped = cleaned.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and data.get("name") in _KNOWN_TOOLS:
                return ""
        except json.JSONDecodeError:
            # Truncated bare JSON tool payload — treat as empty so caller can retry.
            if '"name"' in stripped and any(name in stripped for name in _KNOWN_TOOLS):
                return ""
    return cleaned.strip()


def _looks_like_tool_attempt(text: str) -> bool:
    """True when output appears to be a (possibly malformed/truncated) tool call."""
    if not text or not text.strip():
        return False
    if _TOOL_FENCE.search(text) or _UNCLOSED_TOOL_FENCE.search(text):
        return True
    if _TOOL_CALL_XML.search(text):
        return True
    stripped = text.strip()
    if stripped.startswith("{") and '"name"' in stripped:
        return True
    return False


_EMPTY_RESPONSE_FALLBACK = (
    "模型未返回有效内容（可能是工具调用被截断）。请重试一次，或使用 /provider openrouter。"
)

_TOOL_FORMAT_RETRY = (
    "你的上一条工具调用无效或被截断，导致无法执行。"
    "请用简短命令重新输出合法的 tool JSON，格式如下：\n"
    "```tool\n"
    '{"name": "run_shell", "arguments": {"command": "wc -l src/**/*.py"}}\n'
    "```\n"
    "或直接用文字回答用户，不要只输出空内容。"
)

_EMPTY_REPLY_RETRY = (
    "你的上一条回复为空。请直接回答用户，或输出合法的 ```tool JSON 工具调用。"
)

_INCOMPLETE_REPLY_RETRY = (
    "你的上一条回答不完整或被截断了。"
    "请基于已有工具结果，用简洁完整的中文直接给出最终答案，不要再调用工具。"
)

_INCOMPLETE_REPLY_TAIL = re.compile(
    r"(?:根据|如下|如下所示|结果如下|合计|总计|一共|大约|约为|"
    r"具体(?:如下|情况)?|详细|分别是|其中包括)"
    r"\s*[：:，,、]?\s*$"
)

_MAX_TOOL_RESULT_CHARS = 3000


def _truncate_for_llm(text: str, *, limit: int = _MAX_TOOL_RESULT_CHARS) -> str:
    """Keep tool output small enough for low-context local models."""
    if len(text) <= limit:
        return text
    head = (limit * 2) // 3
    tail = max(200, limit - head - 48)
    return (
        text[:head]
        + f"\n…（工具输出过长，已截断至约 {limit} 字符）…\n"
        + text[-tail:]
    )


def _looks_incomplete_reply(text: str, *, had_tools: bool) -> bool:
    """Detect truncated synthesis answers like a lone「根据」 after tool use."""
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    if not had_tools:
        return False
    if _INCOMPLETE_REPLY_TAIL.search(cleaned):
        return True
    # Very short and no sentence terminator → likely cut mid-thought.
    if len(cleaned) < 12 and not re.search(r"[。！？.!?…]\s*$", cleaned):
        return True
    return False


def _needs_file_tool_retry(
    user_message: str,
    response: str,
    tool_calls: list[dict[str, Any]],
) -> bool:
    """Detect assistant claiming a file mutation without calling a write tool."""
    if not _FILE_ACTION_QUERY.search(user_message):
        return False
    if any(call.get("name") in _FILE_MUTATION_TOOLS for call in tool_calls):
        return False
    if _FILE_CLARIFICATION.search(response):
        return False
    if _CLAIMS_FILE_DONE.search(response):
        return True
    return bool(_FILE_DIRECT_WRITE.search(user_message))


def _rewrite_personal_memory_query(user_message: str) -> str:
    """Rewrite vague personal questions into content-focused recall queries."""
    if _LOCATION_QUERY.search(user_message):
        return "用户居住 住在 住址 位于"
    return user_message


def _try_explicit_remember(user_message: str) -> AgentResult | None:
    """Handle '记住/记录一下' immediately without waiting for exit extraction."""
    match = _EXPLICIT_REMEMBER.match(user_message.strip())
    if not match:
        return None
    content = match.group(1).strip()
    if not content:
        return None
    from localagent.tools import retain_memory

    result = retain_memory(content, source="chat_explicit")
    return AgentResult(
        response=result,
        tool_calls=[{"name": "retain_memory", "arguments": {"content": content}}],
    )


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
        recall_query = _rewrite_personal_memory_query(user_message)
        memory_parts.append(search_memory(recall_query, top_k=10))
        if recall_query != user_message:
            memory_parts.append(search_memory(user_message, top_k=5, fallback=False))

    memory = "\n\n".join(part for part in memory_parts if part)
    lines = [
        "[个人上下文（已预加载，请直接据此回答，勿再调用 search_memory / query_memories）]",
        profile,
        f"记忆检索:\n{memory}",
    ]
    return "\n".join(lines)


def _prefetch_web_context(user_message: str) -> str:
    """Run web search upfront for time-sensitive questions (avoids relying on small models)."""
    if is_session_recall_query(user_message):
        return ""
    if not _WEB_QUERY.search(user_message):
        return ""
    if _WORKSPACE_QUERY.search(user_message) and not re.search(
        r"新闻|时事|头条|热点|天气|股价", user_message
    ):
        return ""
    from localagent.tools import web_search

    result = web_search(user_message)
    if result.startswith(("联网搜索未配置", "联网搜索失败")):
        return ""
    lines = ["[联网搜索结果（已预加载，直接回答，勿再调用 web_search）]", result]
    return "\n".join(lines)


def _prefetch_session_context(
    user_message: str,
    history: list[dict[str, str]] | None,
    session_id: str | None,
) -> str:
    """Load today's chat transcripts for session-recall questions."""
    if not is_session_recall_query(user_message):
        return ""

    from datetime import date

    from localagent.persist.conversations import list_sessions, load_conversation

    today = date.today().isoformat()
    blocks: list[str] = []

    if history:
        blocks.append("## 当前会话（进行中）")
        for msg in history:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = (msg.get("content") or "").strip()
            if content:
                blocks.append(f"{role}: {content}")

    for sid in list_sessions():
        messages = load_conversation(sid)
        today_messages = [m for m in messages if str(m.get("ts", "")).startswith(today)]
        if not today_messages:
            continue
        label = f"{sid}（当前）" if sid == session_id else sid
        blocks.append(f"## 会话 {label}")
        for msg in today_messages:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = (msg.get("content") or "").strip()
            ts = msg.get("ts", "")
            prefix = f"[{ts}] " if ts else ""
            if content:
                blocks.append(f"{prefix}{role}: {content}")

    header = "[对话记录（已预加载，请直接据此回答，勿再调用工具）]"
    if not blocks:
        return f"{header}\n今日暂无已保存的聊天记录。"
    return f"{header}\n" + "\n".join(blocks)


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
    session_context: str = "",
) -> str:
    tools_desc = json.dumps(TOOL_DEFINITIONS, ensure_ascii=False, indent=2)
    profile = load_core_profile().format_for_prompt()
    prompt = f"{SYSTEM_PROMPT.format(tools=tools_desc)}\n\n{profile}"
    if personal_context:
        prompt = f"{prompt}\n\n{personal_context}"
    if session_context:
        prompt = f"{prompt}\n\n{session_context}"
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
    def _status(message: str) -> None:
        if on_status is not None:
            on_status(message)

    remembered = _try_explicit_remember(user_message)
    if remembered is not None:
        _status("写入长期记忆…")
        return remembered

    router = get_model_router()
    prefer = None if provider == "auto" else provider

    _status(f"连接模型 ({router.format_provider_hint(provider)})…")
    personal_context = _prefetch_personal_context(user_message)
    if personal_context:
        _status("预加载个人记忆…")
    session_context = _prefetch_session_context(user_message, history, session_id)
    if session_context:
        _status("加载对话记录…")
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
                session_context=session_context,
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
        if not isinstance(reply, str):
            reply = "" if reply is None else str(reply)

        if not reply.strip() and iteration < 2:
            messages.append(ChatMessage(role="assistant", content=reply or "(空)"))
            messages.append(ChatMessage(role="user", content=_EMPTY_REPLY_RETRY))
            continue

        call = _parse_tool_call(reply)
        if not call:
            clean = _strip_tool_blocks(reply)
            # Truncated/malformed ```tool JSON strips to ""; retry instead of blank.
            if not clean and _looks_like_tool_attempt(reply) and iteration < 2:
                messages.append(ChatMessage(role="assistant", content=reply))
                messages.append(ChatMessage(role="user", content=_TOOL_FORMAT_RETRY))
                continue
            if (
                _looks_incomplete_reply(clean, had_tools=bool(tool_calls))
                and iteration < 2
            ):
                messages.append(ChatMessage(role="assistant", content=reply))
                messages.append(ChatMessage(role="user", content=_INCOMPLETE_REPLY_RETRY))
                continue
            needs_retry = _needs_file_tool_retry(user_message, clean, tool_calls)
            if needs_retry and iteration < 2:
                messages.append(ChatMessage(role="assistant", content=reply))
                append_mode = bool(re.search(r"追加", user_message, re.IGNORECASE))
                mode_hint = (
                    'mode 设为 "append"。'
                    if append_mode
                    else '覆盖写入用 mode "overwrite"，追加用 mode "append"。'
                )
                messages.append(
                    ChatMessage(
                        role="user",
                        content=(
                            "你尚未调用 write_file 或 run_shell 就声称已完成文件操作。"
                            "请先调用 write_file（推荐）或 run_shell 真正执行写入，"
                            f"{mode_hint}"
                            "再根据工具返回的内容预览回答用户，不要编造文件内容。"
                        ),
                    )
                )
                continue
            if needs_retry:
                clean = (
                    "未能实际写入文件：模型未调用 write_file 或 run_shell。"
                    "请重试，或使用 /provider openrouter 等更强模型。"
                )
            if not clean.strip():
                clean = _EMPTY_RESPONSE_FALLBACK
            elif _looks_incomplete_reply(clean, had_tools=bool(tool_calls)):
                clean = (
                    f"{clean.rstrip()}…\n\n"
                    "（回答被截断。请再试一次，或提高 Ollama 的 num_predict / 换用更强模型。）"
                )
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
        result = _truncate_for_llm(execute_tool(tool_name, arguments))
        messages.append(ChatMessage(role="assistant", content=reply))
        messages.append(
            ChatMessage(
                role="user",
                content=(
                    f"工具结果:\n{result}\n"
                    "请基于结果给出完整简洁的最终回答，不要再次调用工具。"
                ),
            )
        )

    final = _strip_tool_blocks(reply)
    if not final.strip():
        final = _EMPTY_RESPONSE_FALLBACK
    elif _looks_incomplete_reply(final, had_tools=bool(tool_calls)):
        final = (
            f"{final.rstrip()}…\n\n"
            "（回答被截断。请再试一次，或提高 Ollama 的 num_predict / 换用更强模型。）"
        )
    return AgentResult(response=final, tool_calls=tool_calls)


def build_agent_graph():
    """Build LangGraph for session persistence (requires [full] extras)."""
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        raise ImportError("缺少 LangGraph 依赖，请重新安装: pip install la-localagent") from exc

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
