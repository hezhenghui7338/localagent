"""LangGraph agent runtime."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from localagent.context.router import (
    AWARE_QUERY as _AWARE_QUERY,
    PrefetchRoute,
    archive_search_query,
    archive_time_window,
    is_archive_recall_query,
    is_last_session_recall_query,
    is_session_recall_query,
    is_weak_archive_topic,
)
from localagent.i18n import resolve_lang, t
from localagent.models.router import ChatMessage, get_model_router
from localagent.tools import TOOL_DEFINITIONS, execute_tool
from localagent.audit.events import log_event
from localagent.agent.observe import truncate_head_tail
from localagent.tools.action_receipt import append_action_receipt, format_milestone_progress, record_side_effect
from localagent.tools.approval import (
    SessionApprovalGate,
    ToolRisk,
    classify_tool,
    denied_message,
    get_approval_policy,
    needs_approval,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_ZH = """你是 LocalAgent，用户的本机个人 AI 助手。你可访问本地记忆库（长期记忆）和知识库。
今天是 {today}。
请用简洁完整的中文回答用户。

原则：
0. 少打扰优先：该做时直接做。仅在缺关键信息且选错代价高时才澄清（例如缺文件路径或改动内容）；轻微模糊可先按合理假设推进并一句话说明。「当前项目/本仓库/工作区」已足够定位，不要再问是哪个项目。统计行数、列目录、搜索、跑测试、个人偏好回忆等读操作直接执行
1. 优先回答用户当前问题，记忆和知识仅作补充
2. 用户明确要求「记住 / 记录一下 / 记下」某事实时，必须立即调用 retain_memory 写入长期记忆，不要只口头答应
3. 涉及个人历史或记忆库内容时，调用 search_memory（若下方已预加载个人上下文则直接回答，禁止再调用工具）
   - 【精确问】「多少次/几个/一共/列出所有/同时提到 X 和 Y」等计数、聚合、可形式化多跳：必须调用 query_memory_graph，禁止仅用 search_memory 从片段估算数字
   - 浏览记忆库、按标签/时间/主题查看记忆时，调用 query_memories；浏览类问题会同时预加载 Cold（知识库文档 + 对话原文/摘要）
   - 已预加载的记忆/知识检索结果即最终依据，不要声称「未找到」后再输出工具 JSON；综合回答时应同时参考 Warm 事实与 Cold 归档，勿只复述短事实句
   - 最近写入的个人事实优先级最高；若预加载结果含住址/偏好等短事实，直接采信
   - 跨会话对话原文/摘要（含 ChatGPT 导入与 LA 历史会话）在知识库 Cold 层，用 search_knowledge；事实句仍优先 search_memory
   - 用户问「我问过/聊过…吗」「以前提过…」时：必须以 Cold 对话归档为准；若下方已预加载「对话归档检索」则直接据此回答，勿只根据 Warm 事实说「没有」
   - 「某年某月问过哪些问题」必须以预加载中标注日期的 Cold 证据为准；证据标注的日期须落在用户所问时段；无命中时如实说该时段无归档，禁止编造主题或问题清单
4. 需要文档原文时，调用 search_knowledge（同样会在索引未命中时回退到文档原文）；若下方已预加载 Cold 知识库片段则直接使用
5. 涉及时效性/外部信息时，调用 web_search（若下方已预加载联网结果且无时效警告则直接回答）
6. 涉及工作区、Git、最近改了什么、待办任务时，调用 workspace_context（若下方已预加载则直接回答）。正式待办是托管队列（非代码 TODO 扫描）；用户要记下/完成/搁置待办时用 workspace_task（add 须 rationale；propose 仅重大问题）
7. 需要创建、修改、写入工作区文件时：局部修改优先 edit_file；新建或整文件覆盖用 write_file；禁止在未实际调用工具的情况下声称已完成文件操作
8. 读文件用 read_file，按文件名找文件用 glob，搜代码内容用 grep；run_shell 仅用于测试/构建/包管理/git 等终端操作，不要用 cat/find/grep/sed/echo 重定向替代专用工具
9. 用户要「总结/速读/3 分钟读懂」某份本地文档（txt/md/pdf/xlsx）时，调用 summarize_document（原子速读，默认不入库）。深入追问请让用户运行 `la summarize <path>` 进入文档对话。禁止在总结后追问是否入库；仅当用户明确说入库/收藏/进知识库时才传 keep=true。若用户问「刚才总结的为啥没入库/搜不到」，说明默认不入库，并告知可用会话内 /keep 或 `la summarize <path> --keep`
10. 用户问「今天新闻/早报/资讯/BestBlogs」时，优先调用 news_brief；精读某篇用 news_read；收藏/不感兴趣用 news_mark。简报每条已含原文链接。库为空时提示先 `la news sync`
11. run_shell / write_file / edit_file 会先经用户确认；若工具结果为「用户拒绝」，如实告知并给出不执行的替代建议，不要擅自重试同一危险操作
12. 回答简洁、准确；使用联网搜索（含预加载结果）作答时【必须标注来源】：在答复末尾列出所依据条目的标题与完整链接，便于用户核实。禁止只写「根据联网信息/预加载结果」而不给链接
13. 【证据核对·必须遵守】使用工具结果（尤其是联网搜索）作答前，必须核对与用户请求一致的基础信息：
   - 时间：问「今天/今日/现在」时，结果日期必须接近今天（{today}）；问「明天/明日」时须匹配次日；若结果是其他月份/年份（例如问 7 月却是 3 月天气），绝对禁止当作当前事实播报
   - 地点：结果中的城市/地区必须与用户所说一致；用户未说城市时，优先使用 Core Profile / 记忆中的居住地；不一致则不可套用（禁止默认成北京等无关城市）
   - 相关性：问某地新闻/天气时，只采信标题或摘要中明确出现该地的条目；禁止把无关全球热点（如问深圳却写佛罗里达 SpaceX 发射）当作「相关动态」补充
   - 出现【核对失败】【时效警告】【相关性】或结果自带「过期」标注时：不可把过期/无关内容当事实；**必须先再调用一次 web_search 换查询重试**（天气用「城市 今天 天气预报」，新闻用「城市 新闻」；勿写完整年份；禁止把歌词/教案/PDF 当天气证据）；仅当重试后仍无可用证据才可说明证据不足
可用工具（以 JSON 格式请求）：
{tools}

如需调用工具，回复格式：
```tool
{{"name": "tool_name", "arguments": {{"query": "..."}}}}
```
否则直接回答。
"""

SYSTEM_PROMPT_EN = """You are LocalAgent, the user's personal on-device AI assistant. You can access the local long-term memory bank and knowledge base.
Today is {today}.
Reply in clear, complete English.

Principles:
0. Prefer action over interruption: do the work when you can. Only clarify when a missing detail would be costly (e.g. missing file path or edit content). For mild ambiguity, proceed with a reasonable assumption and say so in one short line. "This project / this repo / the workspace" is enough to locate context — do not ask which project. Read-only ops (line counts, listing dirs, search, tests, recalling preferences) run immediately.
1. Answer the user's current question first; memory and knowledge are supplements only.
2. When the user explicitly asks to remember / note / record a fact, call retain_memory immediately — do not only agree verbally.
3. For personal history or memory-bank content, call search_memory (if personal context is already preloaded below, answer directly and do not call tools again).
   - Precise asks (counts, aggregations, formal multi-hop like "how many / list all / X and Y together"): must call query_memory_graph; do not estimate numbers from search_memory snippets alone.
   - Browsing the memory bank by tag/time/topic: call query_memories; browse intents also preload Cold (knowledge docs + conversation archives).
   - Preloaded memory/knowledge results are the final evidence — do not claim "not found" and then emit tool JSON; synthesize using Warm facts and Cold archives together.
   - Recently written personal facts have highest priority; trust short facts like address/preferences in preload.
   - Cross-session conversation text/summaries (including ChatGPT imports and LA history) live in Cold — use search_knowledge; fact sentences still prefer search_memory.
   - Questions like "have I asked/talked about… before?" must follow Cold conversation archives; if "archive retrieval" is preloaded below, answer from that — do not say "no" from Warm facts alone.
   - "What did I ask in month/year X" must use dated Cold evidence in the asked window; if none, say so honestly — never invent topics.
4. For document source text, call search_knowledge (falls back to raw docs on index miss); use preloaded Cold knowledge snippets when present.
5. For time-sensitive / external info, call web_search (if web results are preloaded without freshness warnings, answer directly).
6. For workspace, Git, recent changes, or todos, call workspace_context (or use preload). Formal todos are a managed queue (not code TODO scans); add/complete/defer via workspace_task (add needs rationale; propose only for major issues).
7. To create/modify workspace files: prefer edit_file for local edits; write_file for new/full overwrite; never claim a file op succeeded without actually calling the tool.
8. Read with read_file; find by name with glob; search code with grep; run_shell only for test/build/package/git — do not use cat/find/grep/sed/echo redirects instead of dedicated tools.
9. For "summarize / skim / 3-minute read" of a local doc (txt/md/pdf/xlsx), call summarize_document (atomic skim; default not ingested). For follow-ups, tell the user to run `la summarize <path>`. Do not ask whether to ingest after summarizing; only pass keep=true when the user clearly asks to save/ingest. If they ask why it is not in the KB, explain default no-ingest and mention /keep or `la summarize <path> --keep`.
10. For "today's news / briefing / BestBlogs", prefer news_brief; deep-read with news_read; like/dislike with news_mark. Each brief item already has a source link. If the store is empty, suggest `la news sync` first.
11. run_shell / write_file / edit_file require user confirmation first; if the tool result is "user denied", say so and suggest alternatives — do not silently retry the same dangerous op.
12. Be concise and accurate; when using web search (including preload), you MUST cite sources: list titles and full URLs at the end. Do not say "based on web/preload" without links.
13. Evidence checks (mandatory) before using tool results (especially web search):
   - Time: for "today/now", dates must be near today ({today}); for "tomorrow", next day; never report a wrong month/year as current.
   - Place: city/region in results must match the user; if unspecified, prefer Core Profile / memory home location; never default to an unrelated city.
   - Relevance: for local news/weather, only use items that clearly mention that place; do not pad with unrelated global headlines.
   - On check-failure / freshness / relevance warnings or "stale" markers: do not treat as fact; **retry web_search once with a revised query** (weather: "city today forecast"; news: "city news"; no full years; never treat lyrics/lesson plans/PDFs as weather). Only after a failed retry may you say evidence is insufficient.
Available tools (request in JSON):
{tools}

To call a tool, reply with:
```tool
{{"name": "tool_name", "arguments": {{"query": "..."}}}}
```
Otherwise answer directly.
"""

# Back-compat alias (tests / importers may reference SYSTEM_PROMPT).
SYSTEM_PROMPT = SYSTEM_PROMPT_ZH


def _system_prompt_template() -> str:
    return SYSTEM_PROMPT_EN if resolve_lang() == "en" else SYSTEM_PROMPT_ZH


_EXPLICIT_REMEMBER = re.compile(
    r"^(?:请)?(?:帮我)?(?:记录一下|记住一下|记住|记下|记一下)[:：\s]*(.+)$"
    r"|^(?:please\s+)?(?:remember|note|record)(?:\s+that)?[:：\s]+(.+)$",
    re.DOTALL | re.IGNORECASE,
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

_FILE_MUTATION_TOOLS = frozenset({"run_shell", "write_file", "edit_file"})


@dataclass
class AgentResult:
    response: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    action_plan: Any | None = None
    partial: bool = False


_TOOL_LABELS = {
    "retain_memory": "写入记忆",
    "search_memory": "搜索记忆",
    "search_knowledge": "搜索知识库",
    "reflect_memory": "综合推理",
    "query_memory_graph": "精确图查询",
    "web_search": "联网搜索",
    "workspace_context": "工作区上下文",
    "workspace_task": "工作区待办",
    "query_memories": "查询记忆库",
    "read_file": "读取文件",
    "glob": "查找文件",
    "grep": "搜索代码",
    "edit_file": "编辑文件",
    "run_shell": "执行命令",
    "write_file": "写入文件",
    "summarize_document": "一键总结",
    "news_brief": "新闻简报",
    "news_read": "新闻精读",
    "news_mark": "新闻标记",
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


_TOOL_STREAM_MARKERS = ("```tool", "```json", "<tool_call", "<tool")


def _make_answer_stream_gate(
    on_token: Callable[[str], None] | None,
) -> Callable[[str], None] | None:
    """Stream answer tokens; mute turns that look like tool-call payloads.

    Agent turns may emit either prose or a tool call. Streaming tool JSON to the
    terminal is confusing, so we probe the prefix before forwarding tokens.
    """
    if on_token is None:
        return None

    parts: list[str] = []
    mode = "probe"  # probe | emit | mute

    def _gate(chunk: str) -> None:
        nonlocal mode
        if mode == "mute":
            return
        if mode == "emit":
            on_token(chunk)
            return

        parts.append(chunk)
        text = "".join(parts)
        stripped = text.lstrip()
        if not stripped:
            return

        head = stripped[:24]
        for marker in _TOOL_STREAM_MARKERS:
            if head.startswith(marker):
                mode = "mute"
                return
            if marker.startswith(head):
                return  # still matching a tool marker prefix
        if stripped.startswith("{"):
            # Bare JSON tool calls start with `{`; keep buffering until decidable.
            if len(stripped) < 48 and '"name"' not in stripped:
                return
            if _looks_like_tool_attempt(stripped):
                mode = "mute"
                return

        mode = "emit"
        on_token(text)
        parts.clear()

    return _gate


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

_EMPTY_REPLY_RETRY_ZH = (
    "你的上一条回复为空。请直接回答用户，或输出合法的 ```tool JSON 工具调用。"
)
_EMPTY_REPLY_RETRY_EN = (
    "Your previous reply was empty. Answer the user directly, "
    "or emit a valid ```tool JSON tool call."
)

_INCOMPLETE_REPLY_TAIL = re.compile(
    r"(?:根据|如下|如下所示|结果如下|合计|总计|一共|大约|约为|"
    r"具体(?:如下|情况)?|详细|分别是|其中包括|"
    r"as follows|namely|specifically|in total|approximately|including)"
    r"\s*[：:，,、]?\s*$",
    re.IGNORECASE,
)


def _empty_reply_retry() -> str:
    return _EMPTY_REPLY_RETRY_EN if resolve_lang() == "en" else _EMPTY_REPLY_RETRY_ZH


def _incomplete_reply_retry() -> str:
    return t("prompt.retry_incomplete")

_MAX_TOOL_RESULT_CHARS = 1200


def _truncate_for_llm(text: str, *, limit: int = _MAX_TOOL_RESULT_CHARS) -> str:
    """Keep tool output small enough for low-context local models."""
    return truncate_head_tail(text, limit=limit)


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
    """Optionally expand personal questions; keep original text for embedding recall."""
    from localagent.context.fetchers.personal import rewrite_personal_memory_query

    return rewrite_personal_memory_query(user_message)


def _try_explicit_remember(user_message: str) -> AgentResult | None:
    """Handle '记住/记录一下' / 'remember that' immediately without waiting for exit extraction."""
    from localagent.agent.intent_route import explicit_remember_content

    content = explicit_remember_content(user_message)
    if not content:
        return None
    from localagent.tools import retain_memory

    result = retain_memory(content, source="chat_explicit")
    return AgentResult(
        response=result,
        tool_calls=[{"name": "retain_memory", "arguments": {"content": content}}],
    )


def _browse_cold_query(user_message: str) -> str:
    """Strip memory-browse boilerplate so Cold RAG gets a topical query."""
    from localagent.context.fetchers.personal import browse_cold_query

    return browse_cold_query(user_message)


def _prefetch_personal_context(
    user_message: str,
    *,
    path: str | None = None,
    route: PrefetchRoute | None = None,
) -> str:
    """Load profile + Warm + Cold upfront for identity/browse/topic questions."""
    from localagent.context.fetchers.personal import prefetch_personal_context

    return prefetch_personal_context(user_message, path=path, route=route)


def _prefetch_archive_context(
    user_message: str,
    *,
    route: PrefetchRoute | None = None,
) -> str:
    """Prefetch Cold conversation archives (+ Warm topic hits) for past-question recalls."""
    if not is_archive_recall_query(user_message):
        return ""
    from localagent.context.fetchers.archive import prefetch_archive_context

    return prefetch_archive_context(user_message, route=route)


def _prefetch_web_context(
    user_message: str,
    *,
    route: PrefetchRoute | None = None,
) -> str:
    from localagent.context.fetchers.web import prefetch_web_context
    from localagent.context.router import route_prefetch_modules

    resolved = route or route_prefetch_modules(user_message)
    if not resolved.should_prefetch("web"):
        return ""
    return prefetch_web_context(user_message, route=resolved)


def _prefetch_session_context(
    user_message: str,
    history: list[dict[str, str]] | None,
    session_id: str | None,
    *,
    route: PrefetchRoute | None = None,
) -> str:
    from localagent.context.fetchers.session import prefetch_session_context
    from localagent.context.router import route_prefetch_modules

    resolved = route or route_prefetch_modules(user_message)
    if not resolved.should_prefetch("session"):
        return ""
    return prefetch_session_context(
        user_message, history, session_id, route=resolved
    )


def _prefetch_workspace_context(
    user_message: str,
    *,
    route: PrefetchRoute | None = None,
) -> str:
    from localagent.context.fetchers.workspace import prefetch_workspace_context
    from localagent.context.router import route_prefetch_modules

    resolved = route or route_prefetch_modules(user_message)
    if not resolved.should_prefetch("workspace"):
        return ""
    return prefetch_workspace_context(user_message, route=resolved)


def _prefetch_aware_context(
    user_message: str,
    *,
    route: PrefetchRoute | None = None,
) -> str:
    from localagent.context.fetchers.aware import prefetch_aware_context
    from localagent.context.router import route_prefetch_modules

    resolved = route or route_prefetch_modules(user_message)
    if not resolved.should_prefetch("aware"):
        return ""
    return prefetch_aware_context(user_message, route=resolved)


def _build_system_prompt(
    *,
    personal_context: str = "",
    web_context: str = "",
    workspace_context: str = "",
    session_context: str = "",
    archive_context: str = "",
    document_context: str = "",
    aware_context: str = "",
    work_context: str = "",
    milestone_context: str = "",
    turn_evidence: str = "",
) -> str:
    from localagent.context.assemble import build_system_prompt

    return build_system_prompt(
        personal_context=personal_context,
        web_context=web_context,
        workspace_context=workspace_context,
        session_context=session_context,
        archive_context=archive_context,
        document_context=document_context,
        aware_context=aware_context,
        work_context=work_context,
        milestone_context=milestone_context,
        turn_evidence=turn_evidence,
    )


def _tool_followup_instruction(
    tool_name: str,
    result: str,
    validation=None,
) -> str:
    """Build the post-tool user message; delegates to validation follow-up builder."""
    from localagent.agent.validation.followup import build_tool_followup

    return build_tool_followup(tool_name, result, validation)



def run_agent_turn(
    user_message: str,
    history: list[dict[str, str]] | None = None,
    *,
    provider: str = "auto",
    session_id: str | None = None,
    on_status: Callable[[str], None] | None = None,
    on_token: Callable[[str], None] | None = None,
    on_tool_approve: Callable[[str, dict[str, Any], ToolRisk], bool] | None = None,
    session_approval: SessionApprovalGate | None = None,
    document_context: str | None = None,
) -> AgentResult:
    """Run one agent turn with up to 3 tool iterations."""
    def _status(message: str) -> None:
        if on_status is not None:
            on_status(message)

    executed_actions: list[dict[str, Any]] = []
    milestone_progress: str | None = None
    action_plan: Any | None = None
    partial = False

    def _with_receipt(response: str) -> str:
        return append_action_receipt(
            response,
            executed_actions,
            milestone_progress=milestone_progress,
        )

    def _log_tool_decision(
        tool_name: str,
        risk: ToolRisk,
        outcome: str,
        *,
        arguments: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "tool": tool_name,
            "outcome": outcome,
            "risk_level": risk.level,
            "reason": risk.reason,
            "summary": risk.summary,
        }
        if tool_name == "run_shell" and arguments:
            payload["command"] = str(arguments.get("command") or "")
        elif tool_name in {"write_file", "edit_file"} and arguments:
            payload["path"] = str(arguments.get("path") or "")
        log_event("tool.decision", session_id=session_id, **payload)

    def _gated_execute(tool_name: str, arguments: dict[str, Any]) -> str:
        risk = classify_tool(tool_name, arguments)
        if risk.level == "blocked":
            _log_tool_decision(tool_name, risk, "blocked", arguments=arguments)
            log_event(
                "guardrail.triggered",
                session_id=session_id,
                policy_id="tool.blocked",
                action="block",
                tool=tool_name,
                reason=risk.reason,
            )
            return denied_message(blocked=True, reason=risk.reason)
        preapproved = (
            session_approval is not None
            and session_approval.is_preapproved(tool_name, risk)
        )
        if (
            not preapproved
            and needs_approval(tool_name, risk, policy=get_approval_policy())
        ):
            if on_tool_approve is None:
                _log_tool_decision(tool_name, risk, "denied", arguments=arguments)
                return (
                    "错误: 需要用户确认后才能执行该操作（当前为非交互环境）。"
                    "请在交互式 LA chat 中运行，或设置 LA_TOOL_APPROVAL=off。"
                )
            _status(t("chat.status_await_approval"))
            _log_tool_decision(tool_name, risk, "asked", arguments=arguments)
            if not on_tool_approve(tool_name, arguments, risk):
                _log_tool_decision(tool_name, risk, "denied", arguments=arguments)
                return denied_message()
            _log_tool_decision(tool_name, risk, "approved", arguments=arguments)
        elif preapproved:
            _log_tool_decision(
                tool_name, risk, "session_preapproved", arguments=arguments
            )
        try:
            result = execute_tool(tool_name, arguments)
        except Exception as exc:
            _log_tool_decision(tool_name, risk, "failed", arguments=arguments)
            return f"错误: 工具执行失败: {exc}"
        _log_tool_decision(tool_name, risk, "executed", arguments=arguments)
        item = record_side_effect(tool_name, arguments, outcome="executed")
        if item is not None:
            executed_actions.append(item)
        return result

    remembered = _try_explicit_remember(user_message)
    if remembered is not None:
        _status(t("chat.status_write_memory"))
        return remembered

    router = get_model_router()
    prefer = None if provider == "auto" else provider
    logger.info(
        "agent turn start session=%s provider=%s session_recall=%s archive_recall=%s",
        session_id or "-",
        provider,
        is_session_recall_query(user_message),
        is_archive_recall_query(user_message),
    )

    _status(t("chat.status_connecting", hint=router.format_provider_hint(provider)))

    from localagent import config as _cfg
    from localagent.agent.intent_route import classify_turn_intent
    from localagent.agent.planner.executor import execute_milestone_plan
    from localagent.agent.planner.milestone import plan_milestones, verify_plan
    from localagent.agent.react_loop import run_react_loop
    from localagent.context.engine import ContextEngine
    from localagent.persist.session_work import sync_session_work

    turn_ctx = ContextEngine().build_turn_context(
        user_message,
        history,
        session_id=session_id,
        document_context=document_context,
        on_status=_status,
    )
    messages = list(turn_ctx.messages)

    def _rebuild_system(**kwargs) -> str:
        return turn_ctx.rebuild_system(**kwargs)

    def _finish(result: AgentResult) -> AgentResult:
        sync_session_work(
            session_id,
            user_message=user_message,
            action_plan=result.action_plan,
            partial=result.partial,
            tool_calls=result.tool_calls,
        )
        return result

    turn_intent = classify_turn_intent(user_message, session_id)
    logger.info("agent turn intent kind=%s", turn_intent.kind)

    if turn_intent.use_milestone_planner and _cfg.PLANNER_ENABLED:
        plan = turn_intent.resume_plan
        if plan is None:
            _status(t("chat.status_generate"))
            plan = plan_milestones(user_message)
        if plan is not None:
            ok, reason = verify_plan(plan, user_message)
            if ok:
                if turn_intent.kind == "continue":
                    log_event(
                        "planner.resume",
                        session_id=session_id,
                        goal=plan.goal,
                        pending=len(plan.pending),
                    )
                else:
                    log_event(
                        "planner.milestone",
                        session_id=session_id,
                        goal=plan.goal,
                        milestones=len(plan.milestones),
                    )
                outcome = execute_milestone_plan(
                    plan,
                    user_message=user_message,
                    base_messages=messages,
                    router=router,
                    prefer=prefer,
                    session_id=session_id,
                    on_status=on_status,
                    on_token=on_token,
                    gated_execute=_gated_execute,
                    rebuild_system=_rebuild_system,
                )
                action_plan = outcome.plan
                partial = outcome.partial
                if outcome.plan is not None:
                    milestone_progress = format_milestone_progress(
                        completed=[m.objective for m in outcome.plan.completed],
                        pending=[m.objective for m in outcome.plan.pending],
                        partial=outcome.partial,
                    )
                logger.info(
                    "agent turn end provider=%s model=%s tools=%s milestone=%s partial=%s",
                    router.last_provider or "-",
                    router.last_model or "-",
                    len(outcome.tool_calls),
                    True,
                    outcome.partial,
                )
                return _finish(
                    AgentResult(
                        response=_with_receipt(outcome.response),
                        tool_calls=outcome.tool_calls,
                        action_plan=action_plan,
                        partial=partial,
                    )
                )
            log_event("planner.degraded", session_id=session_id, reason=reason)

    loop_result = run_react_loop(
        messages=messages,
        user_message=user_message,
        router=router,
        prefer=prefer,
        session_id=session_id,
        max_iterations=_cfg.AGENT_MAX_TOOL_ITERATIONS,
        on_status=on_status,
        on_token=on_token,
        gated_execute=_gated_execute,
        rebuild_system=_rebuild_system,
        goal=user_message,
    )
    logger.info(
        "agent turn end provider=%s model=%s tools=%s",
        router.last_provider or "-",
        router.last_model or "-",
        len(loop_result.tool_calls),
    )
    return _finish(
        AgentResult(
            response=_with_receipt(loop_result.response),
            tool_calls=loop_result.tool_calls,
            action_plan=action_plan,
            partial=partial,
        )
    )