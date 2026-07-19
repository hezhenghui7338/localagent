"""LangGraph agent runtime."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from localagent.i18n import resolve_lang, t
from localagent.memory.core_profile import load_core_profile
from localagent.models.router import ChatMessage, get_model_router
from localagent.tools import TOOL_DEFINITIONS, execute_tool
from localagent.audit.events import log_event
from localagent.agent.observe import (
    apply_context_budget,
    budget_prefetch_blocks,
    compact_prior_observations,
    compress_observation,
    truncate_head_tail,
)
from localagent.tools.action_receipt import append_action_receipt, record_side_effect
from localagent.tools.approval import (
    SessionApprovalGate,
    ToolRisk,
    classify_tool,
    denied_message,
    get_approval_policy,
    needs_approval,
)

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    messages: list[dict[str, str]]
    tool_calls: list[dict[str, Any]]
    final_response: str


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


_PERSONAL_QUERY = re.compile(
    r"我是谁|我叫什么|我的名字|你知道我|关于我|我的身份|我的职业|我是做什么|"
    r"我喜欢什么|我喜欢喝|我喜欢吃|我爱喝|我爱吃|我的偏好|我的喜好|我的口味|我的经历|"
    r"我的家庭|家庭成员|家人|父母|孩子|儿子|女儿|妻子|老公|老婆|亲属|"
    r"住在哪|住哪|居住|住址|家在哪|位于哪|在哪里住|我住哪|"
    r"\bwho am i\b|\bwhat(?:'s| is) my name\b|\bmy name\b|\babout me\b|"
    r"\bwhat do i (?:like|prefer)\b|\bwhere do i live\b|\bmy (?:job|occupation|family)\b",
    re.IGNORECASE,
)

_MEMORY_BROWSE_QUERY = re.compile(
    r"记忆库|记忆里|我的记忆|记住了什么|记得什么|存了什么|"
    r"有什么有趣|有什么东西|你还记得|你记得我|"
    r"你对我(的)?了解|知道我什么|有什么记忆|"
    r"深入搜索|深度搜索|深度检索|仔细搜索|全面搜索|搜索记忆|"
    r"\bmemory bank\b|\bmy memories\b|\bwhat do you remember\b|"
    r"\bwhat have you (?:stored|saved|remembered)\b|\bsearch (?:my )?memory\b|"
    r"\bdeep(?:er)? search\b",
    re.IGNORECASE,
)

_FAMILY_QUERY = re.compile(
    r"家庭|家人|父母|父亲|母亲|爸爸|妈妈|孩子|儿子|女儿|妻子|老公|老婆|配偶|亲属|结婚|已婚|"
    r"\bfamily\b|\bparents?\b|\bmother\b|\bfather\b|\bspouse\b|\bwife\b|\bhusband\b|"
    r"\bchildren\b|\bson\b|\bdaughter\b|\bmarried\b",
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
    # Previous LA chat session (STM; not Cold semantic search)
    r"(?:上次|上一场|上一回|上一次)"
    r".{0,16}?"
    r"(?:对话|聊天|会话)"
    r".{0,16}?"
    r"(?:问|说|聊|讨论|提到)?"
    r".{0,8}?"
    r"(?:啥|什么|哪些|内容)?"
    r"|"
    r"(?:上次|上一场|上一回|上一次)"
    r".{0,12}?"
    r"(?:问|说|聊|讨论)(?:了|过)?"
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
    r"|"
    # English same-day / in-progress session review
    r"what did (?:we|i) (?:talk|chat|discuss|say|ask).{0,40}?\btoday\b"
    r"|"
    r"\btoday'?s?\b.{0,20}?(?:chat|conversation|talk|discussion)"
    r"|"
    r"(?:what (?:did|was)|remind me).{0,40}?\b(?:last|previous)\b.{0,20}?"
    r"(?:conversation|chat|session|time)\b"
    r"|"
    r"\b(?:last|previous)\b.{0,12}?(?:conversation|chat|session)\b"
    r")",
    re.IGNORECASE,
)

_LAST_SESSION_RECALL_QUERY = re.compile(
    r"(?:"
    r"(?:上次|上一场|上一回|上一次)"
    r"|"
    r"\b(?:last|previous)\b.{0,12}?(?:conversation|chat|session|time)\b"
    r")",
    re.IGNORECASE,
)

# Cross-session / imported archive questions → Cold (search_knowledge), not only Warm.
_ARCHIVE_RECALL_QUERY = re.compile(
    r"(?:"
    r"我(?:有没有|是否)?(?:问过|聊过|提过|讨论过)|"
    r"我.{0,40}?(?:问过|聊过|提过|讨论过|问了).{0,12}?(?:什么|哪些|问题|啥)?"
    r"|"
    r"(?:以前|之前|曾经|过去).{0,8}?(?:问过|聊过|提过|讨论过)|"
    r"(?:问过|聊过|提过)关于|"
    r"关于.+?(?:问过|聊过|提过).{0,12}?(?:什么|哪些|问题)|"
    r"(?:ChatGPT|chatgpt|历史对话|导入(?:的)?对话|对话归档).{0,24}?(?:什么|哪些|有没有|问过|聊过)|"
    r"(?:有没有|是否).{0,12}?(?:问过|聊过|提过)|"
    r"(?:20\d{2}\s*年(?:\s*\d{1,2}\s*月)?|(?:上|这|本)?个?月).{0,30}?"
    r"(?:问过|聊过|提过|讨论过|问了).{0,12}?(?:什么|哪些|问题|啥)?"
    r"|"
    r"\bhave i (?:asked|talked|mentioned|discussed)\b|"
    r"\bdid i (?:ask|talk|mention|discuss)\b|"
    r"\b(?:before|previously|ever).{0,20}?(?:ask|talk|mention|discuss)\b|"
    r"\b(?:conversation|chat) archive\b"
    r")",
    re.IGNORECASE,
)

_ARCHIVE_TOPIC = re.compile(
    r"(?:关于|about)\s*([^的？?，,。！!\s]{1,40})",
    re.IGNORECASE,
)

_TEMPORAL_PHRASE = re.compile(
    r"20\d{2}\s*年(?:\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?)?"
    r"|\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2}(?:st|nd|rd|th)?\s*,?\s*20\d{2}"
    r"|(?:上周|上个星期|这周|这个星期|本周|上个月|上月|这个月|本月|去年|今年|"
    r"最近|近期|近日|今天|今日|昨天|昨日|前天|这两天|这几天|"
    r"recently|lately|today|yesterday)",
    re.IGNORECASE,
)

_LOCATION_QUERY = re.compile(
    r"住在哪|住哪|居住|住址|家在哪|位于哪|在哪里住|我住哪|住在哪里|"
    r"\bwhere do i live\b|\bmy (?:address|home)\b|\bwhere am i (?:based|located)\b",
    re.IGNORECASE,
)

_EXPLICIT_REMEMBER = re.compile(
    r"^(?:请)?(?:帮我)?(?:记录一下|记住一下|记住|记下|记一下)[:：\s]*(.+)$"
    r"|^(?:please\s+)?(?:remember|note|record)(?:\s+that)?[:：\s]+(.+)$",
    re.DOTALL | re.IGNORECASE,
)

_WEB_QUERY = re.compile(
    r"新闻|时事|头条|热点|快讯|发生什么|"
    r"最近|最新|今日|今天|昨天|明天|明日|本周|近期|当下|现在|"
    r"几点(?:了|钟)?|当前时间|现在时间|今天几号|今天日期|今天是几号|"
    r"股价|汇率|天气|"
    r"联网搜索|网上搜|搜索一下|web\s*search|"
    r"news|latest|recent|today|tomorrow|breaking|"
    r"what\s*time|current\s*time",
    re.IGNORECASE,
)

_WORKSPACE_QUERY = re.compile(
    r"我最近|最近干|改了什么|文件变|工作区|工作目录|"
    r"git|提交|commit|分支|未提交|待办|todo|TODO|"
    r"做了什么|进度怎样|项目状态|"
    r"\bworkspace\b|\brecent (?:changes|files)\b|\bwhat did i (?:change|do)\b|"
    r"\bproject status\b|\buncommitted\b",
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

_FILE_MUTATION_TOOLS = frozenset({"run_shell", "write_file", "edit_file"})


def archive_search_query(user_message: str) -> str:
    """Extract a topical search string from an archive-recall question."""
    text = user_message.strip()
    match = _ARCHIVE_TOPIC.search(text)
    if match:
        topic = match.group(1).strip(" 《》「」\"'")
        if topic:
            return _strip_temporal_phrases(topic)
    cleaned = re.sub(
        r"我(?:有没有|是否)?(?:问过|聊过|提过|讨论过)|"
        r"(?:以前|之前|曾经|过去)|"
        r"(?:有没有|是否)|"
        r"关于|什么问题|哪些问题|什么|哪些|吗|呢|[？?！!。．]",
        " ",
        text,
    )
    cleaned = _strip_temporal_phrases(cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned or text


def _strip_temporal_phrases(text: str) -> str:
    return " ".join(_TEMPORAL_PHRASE.sub(" ", text).split())


def is_weak_archive_topic(topic: str) -> bool:
    """True when topic is empty/filler after stripping dates and archive boilerplate."""
    cleaned = _strip_temporal_phrases(topic or "")
    cleaned = re.sub(
        r"我|在|的|了|吗|呢|啊|吧|过|问|聊|提|讨论|问题|哪些|什么|啥|"
        r"最近|近期|近日|今天|今日|昨天|昨日|前天|"
        r"上次|上一场|上一回|上一次|对话|聊天|会话",
        " ",
        cleaned,
    )
    cleaned = " ".join(cleaned.split())
    return len(cleaned) < 2


def archive_time_window(user_message: str) -> tuple[str | None, str | None]:
    """Return (since, until) YYYY-MM-DD when the query has an explicit range intent."""
    from localagent.memory.temporal_intent import parse_temporal_intent

    intent = parse_temporal_intent(user_message)
    if intent.intent_kind == "range" and intent.has_time_scope:
        return intent.scope_start, intent.scope_end
    return None, None


def is_session_recall_query(user_message: str) -> bool:
    """True when the user wants to review STM chat history (window / last session)."""
    return bool(_SESSION_RECALL_QUERY.search(user_message.strip()))


def is_last_session_recall_query(user_message: str) -> bool:
    """True when the user asks specifically about the previous LA chat session."""
    text = user_message.strip()
    if not is_session_recall_query(text):
        return False
    return bool(_LAST_SESSION_RECALL_QUERY.search(text))


def is_archive_recall_query(user_message: str) -> bool:
    """True when the user asks about past/imported conversation topics (Cold)."""
    text = user_message.strip()
    if is_session_recall_query(text):
        return False
    return bool(_ARCHIVE_RECALL_QUERY.search(text))


@dataclass
class AgentResult:
    response: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


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
    if _LOCATION_QUERY.search(user_message):
        # Append lexical hints without replacing the semantic query.
        return f"{user_message} 居住 住在 住址 位于"
    return user_message


def _try_explicit_remember(user_message: str) -> AgentResult | None:
    """Handle '记住/记录一下' / 'remember that' immediately without waiting for exit extraction."""
    match = _EXPLICIT_REMEMBER.match(user_message.strip())
    if not match:
        return None
    content = (match.group(1) or match.group(2) or "").strip()
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


def _prefetch_personal_context(user_message: str) -> str:
    """Load profile + Warm + Cold upfront for identity/browse/topic questions.

    LTM path always joints Cold with Warm (STM session/archive gates stay separate).
    Personal/family Cold uses conversation_only to avoid kb/ doc noise; browse
    still searches the full Cold index (docs + conversation archives).
    """
    browse = bool(_MEMORY_BROWSE_QUERY.search(user_message))
    personal = bool(_PERSONAL_QUERY.search(user_message))
    family = bool(_FAMILY_QUERY.search(user_message))
    if not browse and not personal and not family:
        return ""
    from localagent import config as _cfg
    from localagent.logging_setup import truncate_for_log
    from localagent.tools import query_memories_tool, search_knowledge, search_memory

    path = "family" if family else ("browse" if browse else "personal")
    logger.info("prefetch personal context path=%s", path)
    logger.debug("prefetch personal query=%s", truncate_for_log(user_message))

    profile = load_core_profile().format_for_prompt()
    memory_parts: list[str] = []
    cold = ""
    cold_conversation_only = False
    keep = max(1, int(_cfg.OBSERVE_KEEP_HITS))

    if family:
        memory_parts.append(
            query_memories_tool(
                query="家庭 家人 父母 孩子 妻子",
                tags=["家庭"],
                sort="relevance",
                limit=min(8, keep + 2),
            )
        )
        memory_parts.append(
            search_memory(
                "家庭 家人 父母 孩子 妻子 老公 老婆",
                top_k=keep,
                fallback=False,
            )
        )
        cold_conversation_only = True
        cold = search_knowledge(
            "家庭 家人 父母 孩子 妻子 老公 老婆",
            top_k=min(5, keep),
            fallback=False,
            conversation_only=True,
        )
    elif browse:
        memory_parts.append(
            query_memories_tool(
                query=user_message,
                sort="relevance" if len(user_message.strip()) > 4 else "newest",
                limit=min(8, keep + 2),
            )
        )
        cold_query = _browse_cold_query(user_message)
        logger.info(
            "prefetch browse cold query=%s",
            truncate_for_log(cold_query),
        )
        cold = search_knowledge(cold_query, top_k=min(5, keep), fallback=False)
        # If the topical strip left a very short query, also try the full message.
        if (
            cold.startswith("未找到")
            and cold_query != user_message.strip()
            and len(cold_query) < 8
        ):
            cold = search_knowledge(user_message, top_k=min(5, keep), fallback=False)
    else:
        recall_query = _rewrite_personal_memory_query(user_message)
        rewritten = recall_query != user_message
        logger.info("prefetch personal rewrite=%s", rewritten)
        if rewritten:
            logger.debug("prefetch rewrite→ %s", truncate_for_log(recall_query))
        memory_parts.append(search_memory(recall_query, top_k=min(8, keep + 2)))
        if rewritten:
            memory_parts.append(
                search_memory(user_message, top_k=min(5, keep), fallback=False)
            )
        cold_conversation_only = True
        cold_query = recall_query if rewritten else user_message
        cold = search_knowledge(
            cold_query,
            top_k=min(5, keep),
            fallback=False,
            conversation_only=True,
        )
        if cold.startswith("未找到") and rewritten:
            cold = search_knowledge(
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
        f"[个人上下文（已预加载，请直接据此回答，勿再调用 {forbid}）]",
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


def _prefetch_archive_context(user_message: str) -> str:
    """Prefetch Cold conversation archives (+ Warm topic hits) for past-question recalls."""
    if not is_archive_recall_query(user_message):
        return ""
    from localagent import config as _cfg
    from localagent.logging_setup import truncate_for_log
    from localagent.tools import (
        list_knowledge_in_range,
        list_user_questions_in_range,
        query_memories_tool,
        search_knowledge,
    )

    topic = archive_search_query(user_message)
    since, until = archive_time_window(user_message)
    weak_topic = is_weak_archive_topic(topic)
    keep = max(1, int(_cfg.OBSERVE_KEEP_HITS))
    logger.info(
        "prefetch archive context topic=%s since=%s until=%s weak=%s",
        truncate_for_log(topic),
        since,
        until,
        weak_topic,
    )

    if since or until:
        if weak_topic:
            # Session summaries often truncate mid-conversation; list user turns instead.
            cold = list_user_questions_in_range(
                since=since,
                until=until,
                limit=min(30, keep * 5),
            )
        else:
            cold = search_knowledge(
                topic,
                top_k=min(6, keep),
                fallback=False,
                since=since,
                until=until,
                conversation_only=True,
            )
        warm = query_memories_tool(
            query="" if weak_topic else topic,
            since=since,
            until=until,
            sort="newest",
            limit=min(8, keep + 2),
            show_ids=False,
            time_field="recorded",
        )
        if weak_topic:
            # Short user-question bullets: keep the full browse list (budgeted later).
            cold = cold or ""
        else:
            cold = compress_observation("search_knowledge", cold or "", user_query=user_message)
        warm = compress_observation("query_memories", warm or "", user_query=user_message)
        window = f"{since or '…'} ~ {until or '…'}"
        parts: list[str] = [
            "[对话归档检索（已预加载，请直接据此回答，勿再调用 search_knowledge / search_memory / query_memories）]",
            f"时间窗（对话发生时间 recorded_at）: {window}",
            "说明：下列 Cold 命中已按对话发生时间硬过滤；只可根据标注日期在窗内的证据作答。"
            "若 Cold 显示该时段无归档，必须如实说明，禁止编造问题清单。"
            "Warm 事实仅作补充（亦按 recorded_at 过滤）。",
            f"检索主题: {topic or '（按时间浏览，无主题）'}",
            f"Cold 对话归档:\n{cold or '（Cold 未命中）'}",
        ]
        if warm and not warm.startswith("未找到") and not warm.startswith("记忆库为空"):
            parts.append(f"Warm 相关事实:\n{warm}")
        return "\n".join(parts)

    from localagent.tools import search_memory

    cold = compress_observation(
        "search_knowledge",
        search_knowledge(topic, top_k=min(5, keep), fallback=False),
        user_query=user_message,
    )
    warm = compress_observation(
        "search_memory",
        search_memory(topic, top_k=min(5, keep), fallback=False),
        user_query=user_message,
    )
    parts = [
        "[对话归档检索（已预加载，请直接据此回答，勿再调用 search_knowledge / search_memory）]",
        "说明：下列 Cold 命中来自 ChatGPT/LA 历史对话原文或摘要；据此回答用户「问过/聊过什么」。"
        "Warm 事实仅作补充，不得因 Warm 未命中而否认 Cold 中的对话记录。",
        f"检索主题: {topic}",
        f"Cold 对话归档:\n{cold or '（Cold 未命中）'}",
    ]
    if warm and not warm.startswith("未找到"):
        parts.append(f"Warm 相关事实:\n{warm}")
    return "\n".join(parts)


def _prefetch_web_context(user_message: str) -> str:
    """Run web search upfront for time-sensitive questions (avoids relying on small models)."""
    if is_session_recall_query(user_message):
        return ""
    if is_archive_recall_query(user_message):
        return ""
    # Personal memory / profile questions: do not interrupt with web noise.
    if re.search(
        r"(我喜欢|我讨厌|我的偏好|我叫什么|记得我|你还记得|我说过|我住在|我的目标)",
        user_message,
    ) and not re.search(r"新闻|时事|头条|热点|天气|股价|今天.*(赛|比分)", user_message):
        return ""
    if not _WEB_QUERY.search(user_message):
        return ""
    if _WORKSPACE_QUERY.search(user_message) and not re.search(
        r"新闻|时事|头条|热点|天气|股价", user_message
    ):
        return ""
    from localagent.tools import web_search
    from localagent.tools.web_search import (
        extract_searchable_query,
        inject_home_location_for_weather,
        is_weather_query,
        search_output_has_freshness_warning,
    )

    searchable = extract_searchable_query(user_message)
    if is_weather_query(searchable):
        search_query = inject_home_location_for_weather(searchable)
    else:
        search_query = searchable

    result = compress_observation(
        "web_search",
        web_search(search_query),
        user_query=user_message,
    )
    if result.startswith(("联网搜索未配置", "联网搜索失败")):
        return ""
    if search_output_has_freshness_warning(result):
        header = (
            "[联网搜索结果（已预加载，但时效核对未通过）]"
            "请勿把过期/未核实/非气象结果当作当前事实；"
            "必须再调用 web_search 换查询重试（天气用「城市 今天 天气预报」），"
            "禁止把歌词/教案/PDF 当天气证据；仅重试后仍失败才可说明证据不足。"
            "若仍作答，必须标注来源标题与完整链接。"
        )
    else:
        header = (
            "[联网搜索结果（已预加载，直接回答，勿再调用 web_search）]"
            "回答末尾必须列出所依据条目的标题与完整链接，便于用户核实。"
        )
    return f"{header}\n{result}"


def _format_session_messages(
    messages: list[dict],
    *,
    include_ts: bool = True,
) -> list[str]:
    lines: list[str] = []
    for msg in messages:
        role = "用户" if msg.get("role") == "user" else "助手"
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        ts = msg.get("ts", "") if include_ts else ""
        prefix = f"[{ts}] " if ts else ""
        lines.append(f"{prefix}{role}: {content}")
    return lines


def _pack_session_blocks(
    blocks: list[str],
    *,
    header: str,
    budget: int,
) -> str:
    """Join blocks newest-first already ordered; stop when over budget."""
    if not blocks:
        return f"{header}\n近期暂无已保存的聊天记录。"
    kept: list[str] = []
    used = len(header) + 1
    for block in blocks:
        # Each "block" here is one line; group by session headers in caller.
        add = len(block) + (1 if kept else 0)
        if kept and used + add > budget:
            break
        kept.append(block)
        used += add
    if not kept:
        # Always keep at least the first line of signal.
        kept = [blocks[0][: max(40, budget - len(header) - 20)]]
    return f"{header}\n" + "\n".join(kept)


def _prefetch_session_context(
    user_message: str,
    history: list[dict[str, str]] | None,
    session_id: str | None,
) -> str:
    """Load STM chat transcripts (rolling window or previous session)."""
    if not is_session_recall_query(user_message):
        return ""

    from localagent import config as _cfg
    from localagent.persist.conversations import (
        list_sessions_in_stm_window,
        load_conversation,
        message_create_time,
        previous_session_id,
        stm_window_start_unix,
    )

    budget = max(200, int(getattr(_cfg, "PREFETCH_BUDGET_CHARS", 1500)))

    if is_last_session_recall_query(user_message):
        header = "[上一场对话（已预加载，请直接据此回答，勿再调用工具）]"
        prev = previous_session_id(session_id)
        if not prev:
            return f"{header}\n暂无上一场已保存的对话。"
        messages = load_conversation(prev)
        if not messages:
            return f"{header}\n上一场会话 {prev} 无消息。"
        lines = [f"## 会话 {prev}（上一场）"]
        lines.extend(_format_session_messages(messages))
        return _pack_session_blocks(lines, header=header, budget=budget)

    header = "[对话记录（已预加载，请直接据此回答，勿再调用工具）]"
    since = stm_window_start_unix()
    hours = float(getattr(_cfg, "STM_WINDOW_HOURS", 24) or 24)
    blocks: list[str] = [
        f"说明：以下为近 {hours:g} 小时内的短期对话（STM），按时间新→旧排列。"
    ]

    # Pack newest-first: current history, then other window sessions by update_time.
    session_chunks: list[list[str]] = []

    if history:
        chunk = ["## 当前会话（进行中）"]
        chunk.extend(_format_session_messages(history, include_ts=False))
        if len(chunk) > 1:
            session_chunks.append(chunk)

    for sid in list_sessions_in_stm_window(descending=True):
        if sid == session_id and history:
            # Current session already covered by in-memory history.
            continue
        messages = load_conversation(sid)
        window_messages = [
            m
            for m in messages
            if (ct := message_create_time(m)) is not None and ct >= since
        ]
        if not window_messages:
            continue
        label = f"{sid}（当前）" if sid == session_id else sid
        chunk = [f"## 会话 {label}"]
        chunk.extend(_format_session_messages(window_messages))
        session_chunks.append(chunk)

    # Flatten chunks in order, stopping at budget (prefer whole recent sessions).
    flat: list[str] = [blocks[0]]
    used = len(header) + 1 + len(blocks[0])
    for chunk in session_chunks:
        chunk_text_len = sum(len(line) + 1 for line in chunk)
        if flat and used + chunk_text_len > budget:
            # Try to fit a truncated newest chunk if nothing session-like kept yet.
            if len(flat) <= 1:
                for line in chunk:
                    add = len(line) + 1
                    if used + add > budget:
                        break
                    flat.append(line)
                    used += add
            break
        flat.extend(chunk)
        used += chunk_text_len

    if len(flat) <= 1:
        return f"{header}\n近 {hours:g} 小时内暂无已保存的聊天记录。"
    return f"{header}\n" + "\n".join(flat)


def _prefetch_workspace_context(user_message: str) -> str:
    if not _WORKSPACE_QUERY.search(user_message):
        return ""
    from localagent.tools import workspace_context_tool

    result = compress_observation("workspace_context", workspace_context_tool(days=7))
    if not result:
        return ""
    return "\n".join(
        [
            "[工作区上下文（已预加载，直接回答，勿再调用 workspace_context）]",
            result,
        ]
    )


_AWARE_QUERY = re.compile(
    r"(?:"
    r"(?:最近|今天|今天下午|今天上午|昨晚|这周|这几天)"
    r".{0,20}?"
    r"(?:听|看|改|写|忙|干了|做了什么|在忙|活动)"
    r"|"
    r"(?:听了什么|看了什么|改了哪些|改了什么|在听什么|在忙什么)"
    r"|"
    r"(?:本机感知|aware|电脑上|屏幕前)"
    r".{0,12}?"
    r"(?:做|干|忙|听|看|写)?"
    r"|"
    r"(?:what (?:did|have) i (?:do|listen|watch|work)|been (?:listening|watching|coding))"
    r")",
    re.I,
)


def _prefetch_aware_context(user_message: str) -> str:
    """Inject recent Aware episodes when the user asks about local activity."""
    if not _AWARE_QUERY.search(user_message or ""):
        return ""
    try:
        from localagent.aware.episode import retrieve_aware_context
    except Exception:
        return ""
    try:
        # Window inferred from query (recent → hot/episodes; week+ → rollup).
        card = retrieve_aware_context(user_message, limit=10)
    except Exception:
        return ""
    if not (card or "").strip():
        return ""
    # Cap for chat budget; historical rollup cards may be slightly longer.
    cap = 1600 if "日摘要" in card else 1200
    clipped = card if len(card) <= cap else card[:cap] + "\n…"
    return (
        "[本机感知上下文（已预加载；敏感类仅聚合时长/时段；"
        "用户追问本人行为时据证据回答；无证据勿编造）]\n"
        + clipped
    )


def _build_system_prompt(
    *,
    personal_context: str = "",
    web_context: str = "",
    workspace_context: str = "",
    session_context: str = "",
    archive_context: str = "",
    document_context: str = "",
    aware_context: str = "",
) -> str:
    from datetime import date

    from localagent.tools.web_search import today_label

    tools_desc = json.dumps(TOOL_DEFINITIONS, ensure_ascii=False, indent=2)
    today = date.today()
    today_text = f"{today_label(today)}（{today.isoformat()}）"
    profile = load_core_profile().format_for_prompt()
    prompt = (
        f"{_system_prompt_template().format(tools=tools_desc, today=today_text)}\n\n{profile}"
    )
    if personal_context:
        prompt = f"{prompt}\n\n{personal_context}"
    if archive_context:
        prompt = f"{prompt}\n\n{archive_context}"
    if session_context:
        prompt = f"{prompt}\n\n{session_context}"
    if web_context:
        prompt = f"{prompt}\n\n{web_context}"
    if workspace_context:
        prompt = f"{prompt}\n\n{workspace_context}"
    if aware_context:
        prompt = f"{prompt}\n\n{aware_context}"
    if document_context:
        prompt = f"{prompt}\n\n{document_context}"
    return prompt


def _tool_followup_instruction(tool_name: str, result: str) -> str:
    """Build the post-tool user message; allow one more search when freshness fails."""
    from localagent.tools.web_search import search_output_has_freshness_warning, today_label

    if tool_name == "web_search" and search_output_has_freshness_warning(result):
        return (
            f"工具结果:\n{result}\n"
            f"今天是 {today_label()}。"
            "请先核对结果中的时间与地点是否与用户问题一致。"
            "若全部过期、不符或明显是歌词/教案/无关页面：必须再调用一次 web_search "
            "（天气 query 用「城市 今天 天气预报」，不要写完整年份；"
            "其他查询可含完整目标日期与地点）；"
            "禁止在未重试的情况下直接告诉用户去看手机或放弃。"
            "若重试后仍无可用证据，才可明确告知无法确认当前情况。"
            "若依据部分可用结果作答，末尾必须列出标题与完整链接。"
        )
    cite = ""
    if tool_name == "web_search":
        cite = (
            "回答末尾必须列出所依据条目的标题与完整链接（便于用户核实），"
            "禁止只写「根据联网信息」而不给来源。"
        )
    return (
        f"工具结果:\n{result}\n"
        "请先快速核对结果中的时间/地点等基础信息是否与用户问题一致；"
        "一致则给出完整简洁的最终回答，不要再次调用工具。"
        "若明显不符，说明证据不可用，不要编造或硬套过期信息。"
        f"{cite}"
    )



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

    def _with_receipt(response: str) -> str:
        return append_action_receipt(response, executed_actions)

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
    personal_context = _prefetch_personal_context(user_message)
    if personal_context:
        _status(t("chat.status_prefetch_personal"))
        logger.info("agent prefetch personal=yes")
    archive_context = _prefetch_archive_context(user_message)
    if archive_context:
        _status(t("chat.status_prefetch_archive"))
        logger.info("agent prefetch archive=yes")
    session_context = _prefetch_session_context(user_message, history, session_id)
    if session_context:
        if is_last_session_recall_query(user_message):
            _status(t("chat.status_prefetch_last_session"))
        else:
            _status(t("chat.status_prefetch_session"))
        logger.info("agent prefetch session=yes")
    web_context = _prefetch_web_context(user_message)
    if web_context:
        _status(t("chat.status_prefetch_web"))
        logger.info("agent prefetch web=yes")
    workspace_ctx = _prefetch_workspace_context(user_message)
    if workspace_ctx:
        _status(t("chat.status_prefetch_workspace"))
        logger.info("agent prefetch workspace=yes")
    aware_ctx = _prefetch_aware_context(user_message)
    if aware_ctx:
        _status(t("chat.status_prefetch_aware"))
        logger.info("agent prefetch aware=yes")

    # Heuristic total budget across JIT blocks (small local models).
    # STM recall: keep session ahead of personal/archive so recent chats survive.
    budgeted = budget_prefetch_blocks(
        {
            "personal": personal_context,
            "archive": archive_context,
            "session": session_context,
            "web": web_context,
            "workspace": workspace_ctx,
            "aware": aware_ctx,
        },
        session_first=is_session_recall_query(user_message),
    )
    personal_context = budgeted.get("personal", "")
    archive_context = budgeted.get("archive", "")
    session_context = budgeted.get("session", "")
    web_context = budgeted.get("web", "")
    workspace_ctx = budgeted.get("workspace", "")
    aware_ctx = budgeted.get("aware", "")

    messages = [
        ChatMessage(
            role="system",
            content=_build_system_prompt(
                personal_context=personal_context,
                archive_context=archive_context,
                session_context=session_context,
                web_context=web_context,
                workspace_context=workspace_ctx,
                aware_context=aware_ctx,
                document_context=(document_context or "").strip(),
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
            if router.should_hint_ollama_cold_start(prefer):
                _status(t("chat.status_generate_cold"))
            else:
                _status(t("chat.status_generate"))
        else:
            _status(t("chat.status_synthesize", n=iteration + 1))

        # Stream answers; mute tool-call payloads via the gate.
        reply = router.chat(
            messages,
            temperature=0.3,
            prefer=prefer,
            on_token=_make_answer_stream_gate(on_token),
            usage_command="chat",
            session_id=session_id,
        )
        if not isinstance(reply, str):
            reply = "" if reply is None else str(reply)

        if not reply.strip() and iteration < 2:
            logger.info("agent empty reply retry iteration=%s", iteration)
            messages.append(ChatMessage(role="assistant", content=reply or "(空)"))
            messages.append(ChatMessage(role="user", content=_empty_reply_retry()))
            continue

        call = _parse_tool_call(reply)
        if not call:
            clean = _strip_tool_blocks(reply)
            # Truncated/malformed ```tool JSON strips to ""; retry instead of blank.
            if not clean and _looks_like_tool_attempt(reply) and iteration < 2:
                logger.info("agent tool-format retry iteration=%s", iteration)
                messages.append(ChatMessage(role="assistant", content=reply))
                messages.append(ChatMessage(role="user", content=_TOOL_FORMAT_RETRY))
                continue
            if (
                _looks_incomplete_reply(clean, had_tools=bool(tool_calls))
                and iteration < 2
            ):
                logger.info("agent incomplete-reply retry iteration=%s", iteration)
                messages.append(ChatMessage(role="assistant", content=reply))
                messages.append(ChatMessage(role="user", content=_incomplete_reply_retry()))
                continue
            needs_retry = _needs_file_tool_retry(user_message, clean, tool_calls)
            if needs_retry and iteration < 2:
                logger.info("agent file-tool retry iteration=%s", iteration)
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
                            "你尚未调用 edit_file / write_file 或 run_shell 就声称已完成文件操作。"
                            "局部修改请先调用 edit_file；新建或整文件覆盖用 write_file；"
                            f"{mode_hint}"
                            "再根据工具返回结果回答用户，不要编造文件内容。"
                        ),
                    )
                )
                continue
            if needs_retry:
                clean = (
                    "未能实际写入文件：模型未调用 edit_file / write_file 或 run_shell。"
                    "请重试，或使用 /provider openrouter 等更强模型。"
                )
            if not clean.strip():
                clean = _EMPTY_RESPONSE_FALLBACK
            elif _looks_incomplete_reply(clean, had_tools=bool(tool_calls)):
                clean = (
                    f"{clean.rstrip()}…\n\n"
                    "（回答被截断。请再试一次，或提高 Ollama 的 num_predict / 换用更强模型。）"
                )
            logger.info(
                "agent turn end provider=%s model=%s tools=%s",
                router.last_provider or "-",
                router.last_model or "-",
                len(tool_calls),
            )
            return AgentResult(response=_with_receipt(clean), tool_calls=tool_calls)

        tool_name = call.get("name", "")
        tool_label = _TOOL_LABELS.get(tool_name, tool_name or t("chat.tool_fallback"))
        if resolve_lang() == "en":
            tool_label = tool_name or t("chat.tool_fallback")
        arguments = call.get("arguments", {}) or {}
        logger.info("agent tool call name=%s iteration=%s", tool_name or "-", iteration)
        query = arguments.get("query", "") or arguments.get("command", "")
        if query:
            preview = query if len(query) <= 40 else f"{query[:40]}…"
            _status(t("chat.status_tool_call", label=tool_label, preview=preview))
        else:
            _status(t("chat.status_tool_call_plain", label=tool_label))

        tool_calls.append(call)
        raw = _gated_execute(tool_name, arguments)
        result = compress_observation(
            tool_name,
            raw,
            user_query=user_message,
        )
        messages.append(ChatMessage(role="assistant", content=reply))
        messages.append(
            ChatMessage(
                role="user",
                content=_tool_followup_instruction(tool_name, result),
            )
        )
        # Older tool rounds → short digests; keep only the latest observation full.
        compact_prior_observations(messages)

    final = _strip_tool_blocks(reply)
    if not final.strip():
        final = _EMPTY_RESPONSE_FALLBACK
    elif _looks_incomplete_reply(final, had_tools=bool(tool_calls)):
        final = (
            f"{final.rstrip()}…\n\n"
            "（回答被截断。请再试一次，或提高 Ollama 的 num_predict / 换用更强模型。）"
        )
    logger.info(
        "agent turn end provider=%s model=%s tools=%s (max iterations)",
        router.last_provider or "-",
        router.last_model or "-",
        len(tool_calls),
    )
    return AgentResult(response=_with_receipt(final), tool_calls=tool_calls)


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
