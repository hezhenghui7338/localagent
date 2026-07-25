"""Query-intent detection for JIT prefetch (regex anchors + archive topic parsing)."""

from __future__ import annotations

import re
from typing import Literal

PersonalPath = Literal["family", "browse", "personal"]

_SESSION_RECALL_QUERY = re.compile(
    r"(?:"
    r"(?:今[天日]|刚才|上面|本次|这场|当前|我们|咱俩)"
    r".{0,15}?"
    r"(?:问|说|聊|讨论|提到)"
    r".{0,8}?"
    r"(?:啥|什么|哪些|内容)"
    r"|"
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

WEB_DOMAIN = re.compile(
    r"新闻|时事|头条|热点|快讯|发生什么|"
    r"股价|汇率|天气|"
    r"联网搜索|网上搜|web\s*search|"
    r"news|breaking|"
    r"what\s*time|current\s*time|"
    r"几点(?:了|钟)?|当前时间|现在时间|今天几号|今天日期|今天是几号",
    re.IGNORECASE,
)

WEB_TEMPORAL = re.compile(
    r"最近|最新|今日|今天|昨天|明天|明日|本周|近期|当下|现在|"
    r"latest|recent|today|tomorrow|"
    r"搜索一下",
    re.IGNORECASE,
)

WORKSPACE_QUERY = re.compile(
    r"我最近|最近干|改了什么|文件变|工作区|工作目录|"
    r"git|提交|commit|分支|未提交|待办|todo|TODO|"
    r"做了什么|进度怎样|项目状态|"
    r"\bworkspace\b|\brecent (?:changes|files)\b|\bwhat did i (?:change|do)\b|"
    r"\bproject status\b|\buncommitted\b",
    re.IGNORECASE,
)

AWARE_QUERY = re.compile(
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

PERSONAL_PROFILE_SIGNAL = re.compile(
    r"(我喜欢|我讨厌|我的偏好|我叫什么|记得我|你还记得|我说过|我住在|我的目标)",
    re.IGNORECASE,
)

WEB_OVERRIDE = re.compile(r"新闻|时事|头条|热点|天气|股价|今天.*(赛|比分)", re.IGNORECASE)

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

LOCATION_QUERY = re.compile(
    r"住在哪|住哪|居住|住址|家在哪|位于哪|在哪里住|我住哪|住在哪里|"
    r"\bwhere do i live\b|\bmy (?:address|home)\b|\bwhere am i (?:based|located)\b",
    re.IGNORECASE,
)


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


def is_memory_browse_query(user_message: str) -> bool:
    return bool(_MEMORY_BROWSE_QUERY.search(user_message))


def is_personal_query(user_message: str) -> bool:
    return bool(_PERSONAL_QUERY.search(user_message))


def is_family_query(user_message: str) -> bool:
    return bool(_FAMILY_QUERY.search(user_message))


def is_web_query(user_message: str) -> bool:
    """True when query needs live/web prefetch (domain anchor or temporal + no blockers)."""
    text = user_message.strip()
    if WEB_DOMAIN.search(text):
        return True
    if WEB_TEMPORAL.search(text):
        return True
    return False


def is_workspace_query(user_message: str) -> bool:
    return bool(WORKSPACE_QUERY.search(user_message))


def is_aware_query(user_message: str) -> bool:
    return bool(AWARE_QUERY.search(user_message or ""))


def personal_prefetch_path(user_message: str) -> PersonalPath | None:
    """Sub-path for personal prefetch retrieval strategy."""
    if is_family_query(user_message):
        return "family"
    if is_memory_browse_query(user_message):
        return "browse"
    if is_personal_query(user_message):
        return "personal"
    return None


def _strip_temporal_phrases(text: str) -> str:
    return " ".join(_TEMPORAL_PHRASE.sub(" ", text).split())


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


def web_blocked_by_personal(text: str) -> bool:
    return bool(PERSONAL_PROFILE_SIGNAL.search(text)) and not bool(WEB_OVERRIDE.search(text))


def web_blocked_by_workspace(text: str) -> bool:
    return bool(WORKSPACE_QUERY.search(text)) and not bool(WEB_OVERRIDE.search(text))
