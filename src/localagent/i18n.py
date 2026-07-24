"""UI / prompt language: follow system locale, overridable via LA_LANG."""

from __future__ import annotations

import locale
import os
import re
from typing import Literal

Lang = Literal["en", "zh"]

_CACHED: Lang | None = None

_ZH_PREFIX = re.compile(r"^zh(\b|_)", re.I)
_EN_PREFIX = re.compile(r"^en(\b|_)", re.I)


def reset_lang_cache() -> None:
    """Clear cached language (for tests)."""
    global _CACHED
    _CACHED = None


def _normalize_explicit(raw: str) -> Lang | None:
    value = raw.strip().lower().replace("-", "_")
    if not value or value == "auto":
        return None
    if value in ("zh", "zh_cn", "zh_tw", "zh_hk", "cn", "chinese"):
        return "zh"
    if value in ("en", "en_us", "en_gb", "english"):
        return "en"
    if _ZH_PREFIX.match(value):
        return "zh"
    if _EN_PREFIX.match(value):
        return "en"
    return None


def _from_locale_tag(tag: str | None) -> Lang | None:
    if not tag:
        return None
    tag = tag.strip()
    if not tag or tag in ("C", "POSIX"):
        return None
    # LANG-style: zh_CN.UTF-8 / en_US.UTF-8
    primary = tag.split(".", 1)[0].replace("-", "_")
    if _ZH_PREFIX.match(primary):
        return "zh"
    if _EN_PREFIX.match(primary):
        return "en"
    return None


def _system_lang() -> Lang | None:
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        hit = _from_locale_tag(os.environ.get(key, ""))
        if hit:
            return hit
    try:
        loc = locale.getlocale()
    except (ValueError, locale.Error):
        loc = (None, None)
    if loc and loc[0]:
        hit = _from_locale_tag(loc[0])
        if hit:
            return hit
    try:
        preferred = locale.getpreferredencoding(False)
    except Exception:
        preferred = ""
    # Encoding alone is not a language signal; ignore.
    _ = preferred
    return None


def resolve_lang() -> Lang:
    """Return active UI/reply language: LA_LANG > system locale > en."""
    global _CACHED
    if _CACHED is not None:
        return _CACHED
    explicit = _normalize_explicit(os.environ.get("LA_LANG", ""))
    if explicit:
        _CACHED = explicit
        return _CACHED
    _CACHED = _system_lang() or "en"
    return _CACHED


def default_news_rss_url(lang: Lang | None = None) -> str:
    """BestBlogs default feed for the active (or given) language."""
    code = lang or resolve_lang()
    path_lang = "zh" if code == "zh" else "en"
    return (
        f"https://www.bestblogs.dev/{path_lang}/feeds/rss"
        "?category=ai&minScore=80&timeFilter=1d"
    )


# --- Message catalog (user-visible UI) ---

_MESSAGES: dict[Lang, dict[str, str]] = {
    "zh": {
        "banner.tips_title": "入门提示",
        "banner.tip_chat": "直接输入问题开始对话",
        "banner.tip_tab": "/ + Tab 补全命令",
        "banner.tip_help": "/help 查看全部命令",
        "banner.tip_status": "/status 查看数据层",
        "banner.tip_provider": "/provider 切换模型路径",
        "banner.tip_model": "/model 切换默认模型",
        "banner.tip_websearch": "/websearch <关键词> 联网",
        "banner.tip_deepsearch": "/deepsearch <主题> 研究",
        "banner.tip_quit": "/q / Ctrl+C×2 退出",
        "banner.daily_actions": "Daily Actions",
        "banner.daily_fallback": "la status 查看今日信号",
        "banner.data_layers": "数据层",
        "banner.layers_fallback": "la status 查看数据层",
        "banner.web_search": "联网 · {label}",
        "web_search.ddgs": "ddgs（免费）",
        "session.help_header": "会话内命令（进入 LA / LA chat 后，以 / 开头；: 为兼容别名）：",
        "session.help_help": "  /help, /h              显示本帮助",
        "session.help_status": "  /status                今日信号 + 数据层（Hot/Warm/Cold/Aware）",
        "session.help_provider": "  /provider, /p [name]   查看或切换模型路径",
        "session.help_model": "  /model [name|N]        查看/翻页/切换当前路径模型（写入配置）",
        "session.help_model_page": "                          翻页: next|prev|page N；序号为本页 1–10",
        "session.help_memory": "  /memory [action]       记忆概览；无参显示 status（与外层 LA memory 相同）",
        "session.help_rag": "  /rag [action]          知识库概览；无参显示 status（与外层 LA rag 相同）",
        "session.help_reflect": "  /reflect <问题>        综合推理：记忆召回 → 知识库 → 归纳",
        "session.help_websearch": "  /websearch <关键词>    联网搜索（专注互联网）",
        "session.help_deepsearch": "  /deepsearch <主题>     多步联网深度研究",
        "session.help_polish": "  /polish <草稿>         一键润色（场景识别 + 复制主推）",
        "session.help_quit": "  /q, /quit, /exit       退出对话",
        "session.help_equiv": "外层 LA <command> 与会话内 /<command> 等价（/chat 除外）。",
        "session.help_shortcuts": (
            "会话快捷方式：/add → /ingest text，/search → /memory search，/forget → /memory forget。"
        ),
        "session.missing_cmd": "[LA] 缺少命令。输入 /help 查看可用命令。",
        "session.already_chat": "[LA] 已在对话中，无需 /chat。输入问题开始聊天，或 /help 查看命令。",
        "session.provider_current": "当前路径: {hint}",
        "session.provider_usage": "用法: /provider auto|{providers}",
        "session.provider_switched": "[provider] 已切换为 {hint}",
        "session.model_empty": "未获取到可用模型列表（可仍用 /model <名称> 直接设置）。",
        "session.model_usage": "用法: /model <名称>",
        "session.model_list": "可用模型 ({total}) 第 {page}/{pages} 页：",
        "session.model_page_hint": "翻页: /model next|prev|page N",
        "session.model_select": "选择: /model <1-{n}> 或完整名称",
        "session.model_set": "[model] 已将 {provider} 默认模型设为 {model}",
        "session.model_wrote": "[model] 已写入 {path}（下次启动默认使用）",
        "session.model_path_auto": "当前路径: auto → {effective}",
        "session.model_path": "当前路径: {effective}",
        "session.model_current": "当前模型: {current}",
        "session.model_unset": "(未配置)",
        "session.model_no_page": "[model] 无可用模型列表，无法翻页。可直接 /model <名称>",
        "session.model_page_usage": "用法: /model page <1-{pages}>",
        "session.model_bad_index": (
            "[model] 序号无效，本页请输入 1–{n}（先 /model 或 /model next 翻页）"
        ),
        "session.model_not_in_list": "[model] 提示: {name!r} 不在当前列表中，仍将写入配置",
        "session.deepsearch_usage": "用法: /deepsearch <主题>",
        "session.deepsearch_working": "研究中: {topic}",
        "session.deepsearch_cancelled": "\n[chat] deepsearch 已取消",
        "session.deepsearch_failed": "[deepsearch 失败] {exc}",
        "session.empty_cmd": "[LA] 空命令。输入 /help 查看可用命令。",
        "session.m_deprecated": (
            "[LA] /m 已弃用（易与 model / memory 混淆）。"
            "切换模型用 /model，查询记忆用 /memory query。"
        ),
        "session.interrupted": "\n[LA] 已中断",
        "session.cmd_failed": "[LA] 命令失败: {exc}",
        "chat.warn_openai_key": (
            "[chat] 警告: openai 未配置 api_key。"
            " 请 LA config set-key openai <key> 或在 LA 会话中 /config set-key openai <key>。"
        ),
        "chat.hint_ollama_slow": "[chat] 提示: Ollama 本地模型较慢时可 /provider {alt} 加速",
        "chat.cancel_once": "\n[chat] 已取消；再按一次 Ctrl+C 退出，或继续输入",
        "chat.processing": "处理中…",
        "chat.request_cancelled": "\n[chat] 请求已取消",
        "chat.error": "[错误] {exc}",
        "chat.empty_response": "[错误] 模型返回了空内容，请重试。",
        "chat.ollama_failover": "[chat] 本地 Ollama 响应过慢，已自动切换 {provider}",
        "approval.deny_rm_root": "禁止删除根目录",
        "approval.deny_mkfs": "禁止格式化磁盘",
        "approval.deny_dd_dev": "禁止直接写入块设备",
        "approval.deny_overwrite_disk": "禁止覆写磁盘设备",
        "approval.deny_fork_bomb": "禁止 fork bomb",
        "approval.risk_rm": "删除文件/目录",
        "approval.risk_sudo": "以管理员权限执行",
        "approval.risk_chmod": "修改文件权限",
        "approval.risk_chown": "修改文件所有者",
        "approval.risk_mv_cp": "移动/复制文件",
        "approval.risk_destructive": "破坏性文件操作",
        "approval.risk_find_delete": "find 批量删除",
        "approval.risk_force_push": "强制推送",
        "approval.risk_hard_reset": "硬重置",
        "approval.risk_git_clean": "强制清理工作区",
        "approval.risk_kill": "终止进程",
        "approval.risk_pipe_sh": "下载并执行脚本",
        "approval.risk_eval": "动态执行代码",
        "approval.risk_redirect": "重定向写入绝对路径",
        "approval.risk_dd": "底层磁盘读写",
        "approval.risk_power": "关机/重启",
        "approval.risk_uninstall": "卸载软件包",
        "approval.empty_cmd": "(空命令)",
        "approval.path_unset": "(未指定路径)",
        "approval.write_append": "追加",
        "approval.write_overwrite": "覆盖写入",
        "approval.write_reason": "{action}本地文件",
        "approval.write_summary": "{path} ({action}, {n} 字符)\n预览: {preview}",
        "approval.edit_all": "全部替换",
        "approval.edit_one": "单处替换",
        "approval.edit_reason": "精确编辑本地文件",
        "approval.label_shell": "执行命令",
        "approval.label_edit": "编辑文件",
        "approval.label_write": "写入文件",
        "approval.request": "⚠ Agent 请求{label}，需你确认后才会执行。",
        "approval.risk_line": "风险: {reason}",
        "approval.cmd_line": "命令: {cmd}",
        "approval.cwd_line": "目录: {cwd}",
        "approval.target_line": "目标: {summary}",
        "approval.q_dangerous": "⚠ 这是潜在危险操作，确定要执行吗？",
        "approval.q_session": "是否允许执行？（a = 本会话同类安全操作不再询问）",
        "approval.q_default": "是否允许执行？",
        "approval.blocked": "错误: {reason}。",
        "approval.blocked_default": "该操作已被安全策略禁止",
        "approval.denied": "用户拒绝执行该操作。",
        "cli.description": (
            "LocalAgent — The AI that lives on your computer · 栖居在你电脑里的 AI。\n"
            "本地优先，真记得你，把事办完。\n\n"
            "主路径（少即是多）：\n"
            "  la / la chat     对话\n"
            "  la setup [-y]    安装/拉取本地 Ollama 模型\n"
            "  la config …      纯本地或自有 API 配置\n"
            "  la status        今日信号 + 数据层（Hot/Warm/Cold/Aware）\n\n"
            "日常能力见 memory / rag / audit；运维与实验见 tasks / logs / graph 等。"
        ),
        "cli.epilog": (
            "示例：\n"
            "  la                  # 进入对话（等同 la chat）\n"
            "  la setup -y         # 一键装好本地模型\n"
            "  la config list      # 查看配置\n"
            "  la memory pending   # 确认待写入记忆\n"
            "  la ingest doc notes.md  # 文档持久记忆化\n"
            "  la ingest text \"…\" # 单条写入\n"
            "  la summarize doc.md # 一键总结（默认不入库）\n"
            "  la news brief       # 今日新闻简报（先 la news sync）\n"
            "  la aware                  # 当前状态 + 近 3h 动态（--since / tick）\n"
            "  la polish \"催进度草稿\"  # 一键润色（默认复制主推）\n"
            "\n"
            "进入对话后可用 /<command>（输入 /help；: 为兼容别名）。\n"
            "使用 LA <command> -h 查看某个命令的完整说明。"
        ),
        "cli.chat_help": (
            "[--session-id ID] [-p auto|{providers}]  【主路径】交互式对话"
        ),
        "cli.chat_desc": "启动交互式对话 REPL（主路径）",
        "cli.version_help": "显示版本号并退出",
        "cli.debug_help": "启用 DEBUG 诊断日志（同时写入文件并输出到 stderr）",
        "status.section_layers": "── 数据层 ──",
        "status.section_recall": "── 综合召回 ──",
        "status.tips_header": "提示：",
        "status.tip_news": "  la news brief          # 今日简报",
        "status.tip_pending": "  la memory pending      # 审阅待写入记忆",
        "status.tip_memory": "  la memory status       # Warm / Hot 引擎诊断",
        "status.tip_rag": "  la rag status          # Cold 知识库诊断",
        "status.tip_tasks": "  la workspace tasks     # 托管待办（done/dismiss/snooze）",
        "status.tip_add": "  la workspace add \"…\" --why \"…\"  # 显式添加待办",
        "status.tip_scan": "  la workspace scan      # 诊断扫描代码 TODO（未入队）",
        "status.tip_aware": "  la aware               # 当前状态 + 近 3 小时动态",
        "status.tip_aware_since": "  la aware --since 1w    # 最近一周变化",
        "status.tip_aware_sug": "  la aware suggestion    # 感知建议（approve/reject 为其子命令）",
        "status.tip_ungrant": "  la aware ungrant …     # 解除监测授权",
        "daily.news_ready": "今日新闻已就绪",
        "daily.news_unsynced": "今日新闻未 sync",
        "daily.news_line": "新闻 · {news}",
        "daily.pending_line": "记忆 pending · {n}",
        "daily.todo_line": "workspace 待办 · {n}",
        "daily.aware_line": "aware · 今日事件 {events} / suggestion {sug}",
        "layers.hot_configured": "Hot · 已配置 · {prefs}偏好",
        "layers.hot_anchors": " · {n}锚点",
        "layers.hot_unset": "Hot · 未配置",
        "layers.warm_banner": "Warm · {facts}事实 · pending {pending}",
        "layers.cold_banner": "Cold · kb{kb} · 对话块{dialog} · ChatGPT{chatgpt}",
        "layers.aware_banner": "Aware · 今日{n}",
        "layers.banner_detail_hint": "la status 查看明细",
        "layers.hot_detail": "Hot   已配置 · {name} · {prefs}偏好 · {anchors}锚点",
        "layers.hot_detail_unset": "Hot   未配置",
        "layers.warm_detail": (
            "Warm  {facts}事实 · pending {pending}"
            " · 来源 chat={chat} chatgpt={chatgpt} file={file} other={other}"
        ),
        "layers.cold_detail": (
            "Cold  kb={kb}"
            " · 块 kb={kb_chunks} chat={chat} chatgpt={chatgpt}"
            " · LA会话 {sessions}"
            " · ChatGPT已导入 {imported}"
            " · 收藏 news={bookmarks}"
            " summarize={summarize}"
        ),
        "layers.aware_detail": "Aware 今日事件 {events} · suggestion {sug}",
        "layers.recall_order": (
            "默认顺序: Hot/Warm(personal) → Cold对话归档(archive) → session → web → workspace → aware"
        ),
        "layers.recall_time": (
            "时间邻近加权已启用（记忆半衰期 {recency:g} 天 / 时间锚衰减 {time_hl:g} 天）；"
            "STM 类问题会把 session 提前"
        ),
        "chat.status_connecting": "连接模型 ({hint})…",
        "chat.status_prefetch_personal": "预加载个人记忆…",
        "chat.status_prefetch_archive": "检索对话归档…",
        "chat.status_prefetch_last_session": "加载上一场对话…",
        "chat.status_prefetch_session": "加载短期对话…",
        "chat.status_prefetch_web": "联网搜索…",
        "chat.status_prefetch_workspace": "加载工作区上下文…",
        "chat.status_prefetch_aware": "加载本机感知…",
        "chat.status_generate": "生成回复…",
        "chat.status_generate_cold": "生成回复（本地模型首次加载可能较慢）…",
        "chat.status_synthesize": "综合工具结果 (第 {n} 轮)…",
        "chat.status_await_approval": "等待用户确认操作…",
        "chat.status_write_memory": "写入长期记忆…",
        "chat.status_tool_call": "调用 {label}: {preview}",
        "chat.status_tool_call_plain": "调用 {label}…",
        "chat.tool_fallback": "工具",
        "ollama.ram_choose": "检测到系统内存 {ram} → 选用 {model}（{label}，{size}）",
        "ollama.ram_recommend": "检测到系统内存 {ram} → 推荐 {model}（{label}，{size}）",
        "ollama.not_detected": "未检测到本机 Ollama。",
        "ollama.tier_Mini": "Mini",
        "ollama.tier_轻量": "轻量",
        "ollama.tier_推荐": "推荐",
        "ollama.tier_高配": "高配",
        "aware.title_overview": "LocalAgent · Aware · 概览",
        "aware.title_delta": "LocalAgent · Aware · 自上次探测 · 概览",
        "aware.title_window": "LocalAgent · Aware · {window} · 概览",
        "aware.title_detail_now": "LocalAgent · Aware · 当前",
        "aware.title_detail_delta": "LocalAgent · Aware · 自上次探测",
        "aware.section_focus": "主注意力",
        "aware.section_state": "当前状态",
        "aware.section_activity": "{window}（按注意力）",
        "aware.section_dynamics": "感知动态",
        "aware.section_episodes": "近期 Episode（按注意力）",
        "aware.section_system": "系统",
        "aware.no_focus": "  （暂无清晰前台焦点）",
        "aware.no_snapshot": "  · 无实时快照（可先 la aware grant / 打开浏览器）",
        "aware.tip_overview": (
            "提示: 直接提问进入 aware> · --no-chat 只打印 · --detail 分源明细 · tick"
        ),
        "aware.last_tick": "上次 tick · {when}",
        "aware.never_run": "尚未运行",
        "aware.granted": "已授权 · {sources}",
        "aware.granted_none": "无（la aware grant …）",
        "aware.recent_n": "最近 {n} {unit}",
        "aware.unit_h": "小时",
        "aware.unit_d": "天",
        "aware.unit_w": "周",
        "aware.unit_m": "个月",
        "aware.unit_y": "年",
        "aware.period_dawn": "清晨",
        "aware.period_morning": "上午",
        "aware.period_afternoon": "下午",
        "aware.period_evening": "傍晚",
        "aware.period_night": "晚上",
        "aware.period_late": "深夜",
        "aware.daypart_day": "白天",
        "aware.daypart_night": "晚上",
        "aware.daypart_late": "深夜",
        "aware.since_invalid": (
            "无效 --since: {value!r}（格式: <N>h|<N>d|<N>w|<N>m|<N>y，如 3h、2d、1w）"
        ),
        "aware.input_idle": "今日输入活跃: 尚无（已采样，空闲较高）",
        "aware.input_active": "今日输入活跃: 约 {minutes:.0f} 分钟",
        "aware.input_active_apps": "今日输入活跃: 约 {minutes:.0f} 分钟（{apps}）",
        "aware.input_idle_window": "{window}输入活跃: 尚无（已采样，空闲较高或仅为前台存在）",
        "aware.input_active_window": "{window}输入活跃: 约 {minutes:.0f} 分钟",
        "aware.input_active_apps_window": "{window}输入活跃: 约 {minutes:.0f} 分钟（{apps}）",
        "aware.viewing": "正在看",
        "aware.bg_selected": "后台选中",
        "aware.not_viewing": "非正在看",
        "aware.current_prefix": "当前:",
        "aware.tabs_unit": "标签",
        "aware.unauthorized": "未授权",
        "aware.no_change": "相较上次无新变化",
        "aware.mode_now": "模式: 当前概览（当前状态 + 活动窗 {window}）",
        "aware.mode_delta": "模式: 自上次探测",
        "aware.mode_window": "模式: 时间窗 · {window}",
        "aware.heuristic_primary": "主要：{text}",
        "aware.heuristic_secondary": "其次：{text}",
        "aware.heuristic_almost_none": "几乎没有：后台选中标签（未浏览）",
        "aware.heuristic_empty": "近期无已记录的感知活动（可先 la aware grant / tick）",
        "aware.episode_empty": "（近窗无 Episode）",
        "aware.episode_chars": " · ~{n}字",
        "aware.episode_cmds": " · {n}条命令",
        "aware.episode_fs_title": "{scene} · 新增{created}/编辑{modified}",
        "aware.episode_term_title": "终端会话 · {n} 条命令",
        "aware.episode_git_title": "git · {n} 条变化",
        "aware.episode_sensitive_browse": "敏感类浏览（仅时长信号）",
        "aware.episode_sensitive_page": "敏感类浏览页（仅时长信号）",
        "aware.episode_sensitive_fg": "敏感类前台活动（仅时长）",
        "aware.detail_unauthorized": "  （未授权 · la aware grant {name}）",
        "aware.detail_tip": "提示: la aware | --detail | --since 1w | tick | grant / ungrant",
        "aware.detail_no_data": "  （无数据）",
        "aware.cmd_unknown": "[aware] 未知子命令: {action}",
        "aware.status_title": "LocalAgent · Aware",
        "aware.status_last_tick": "上次 tick · {when}",
        "aware.status_never": "尚未运行",
        "aware.status_sched_on": "开",
        "aware.status_sched_off": "关",
        "aware.status_schedule": (
            "定时 · {state} ({backend}, 每 {minutes} 分钟) · {detail}"
        ),
        "aware.status_counts": "今日事件 · {events}  |  suggestion · {sug}",
        "aware.status_grants": "授权（grant / ungrant）：",
        "aware.status_not_impl": " (尚未实现)",
        "aware.status_hint_ungrant": "  → ungrant {name}",
        "aware.status_view_hint": "查看: la aware · la aware --since 1w · la aware tick",
        "aware.status_ungrant_hint": "解除: la aware ungrant <source>|all",
        "aware.status_sug_hint": "建议: la aware suggestion · approve|reject",
        "aware.grant_usage": "[aware] 用法: la aware grant <source>|all …",
        "aware.grant_choices": "[aware] 可选: all {sources}",
        "aware.grant_unknown": "[aware] 未知 source: {source}",
        "aware.grant_not_impl": "[aware] {source} 尚未实现，跳过",
        "aware.grant_will": "[aware] 将授权读取 ({source})：",
        "aware.grant_confirm": "确认授权 {source}？",
        "aware.grant_cancelled": "[aware] 已取消: {source}",
        "aware.grant_no_browser": "[aware] 未发现浏览器 History；仍写入授权",
        "aware.grant_ok": "[aware] 已授权: {source}",
        "aware.ungrant_usage": "[aware] 用法: la aware ungrant <source>|all",
        "aware.ungrant_unknown": "[aware] 未知 source: {source}",
        "aware.ungrant_ok": (
            "[aware] 已解除: {source} · 可用 la aware grant {source} 重新授权"
        ),
        "aware.paths_list": "[aware] fs 监视路径：",
        "aware.paths_not_dir": "[aware] 不是目录: {path}",
        "aware.paths_hint_grant": "[aware] 提示: fs 尚未 grant；请再运行 la aware grant fs",
        "aware.paths_added": "[aware] 已添加: {path}",
        "aware.paths_removed": "[aware] 已移除: {path}",
        "aware.paths_usage": "[aware] paths 子命令: list | add | rm",
        "aware.schedule_status": (
            "[aware] schedule: {state} backend={backend} every={minutes}m · {detail}"
        ),
        "aware.schedule_on_fail": "[aware] schedule on 失败: {exc}",
        "aware.schedule_on_ok": "[aware] schedule on · {backend} · {detail}",
        "aware.schedule_off_ok": "[aware] schedule off · {detail}",
        "aware.schedule_usage": "[aware] schedule 子命令: on | off | status",
        "aware.tick_skipped": "[aware] tick 跳过: {reason}",
        "aware.tick_auto": "  auto · {line}",
        "aware.tick_sug_new": "  suggestion 新增 · {n}（la aware suggestion）",
        "aware.tick_error": "  ! {err}",
        "aware.sug_usage": "[aware] suggestion 子命令: list | approve | reject",
        "aware.sug_empty": "[aware] suggestion 为空",
        "aware.sug_list_header": "[aware] suggestion ({n})：",
        "aware.sug_help": (
            "批准: la aware suggestion approve <id>|all\n"
            "拒绝: la aware suggestion reject <id>|all"
        ),
        "aware.sug_not_found": "[aware] 未找到: {target}",
        "aware.sug_deny_cmd": "[aware] 拒绝执行非白名单命令: {cmd}",
        "aware.sug_acked": "[aware] 已确认 {kind} · {title}",
        "aware.sug_exec": "[aware] 执行: {cmd}",
        "aware.sug_exit_code": "[aware] 命令退出码 {code}",
        "aware.sug_approved": "[aware] 已批准执行 {ok}/{total}",
        "aware.sug_rejected": "[aware] 已拒绝 {n} 条",
        "aware.events_none": "[aware] 无事件",
        "aware.events_summary": "[aware] 近 {hours}h 事件摘要（--raw 看明细）",
        "aware.events_total": "[aware] 共 {n} 条",
        "aware.repl_help_intro": (
            "当前是「感知对话」：围绕本机 Aware 行为深入聊；闲聊请另开 la chat。"
        ),
        "aware.repl_help_cmds": "命令：",
        "aware.repl_help_overview": "  /overview, /o   重新显示智能概览",
        "aware.repl_help_detail": "  /detail         显示分源明细",
        "aware.repl_help_context": "  /context, /c    显示当前注入的感知上下文",
        "aware.repl_help_status": "  /status         授权 / suggestion / session",
        "aware.repl_help_help": "  /help, /h       显示本帮助",
        "aware.repl_help_provider": "  /provider, /p   切换模型路径",
        "aware.repl_help_quit": "  /q, /quit, /exit 结束感知对话",
        "aware.repl_help_example": "直接输入问题即可，例如：我今天下午改了哪些文件？",
        "aware.repl_entered": "[aware] 已进入感知对话（session={session}）",
        "aware.repl_hint": "[aware] 可追问本机行为；/help 查看命令，/exit 结束。",
        "aware.repl_cancel_once": "\n[aware] 已取消；再按一次 Ctrl+C 退出，或继续提问",
        "aware.repl_ended": "[aware] 感知对话结束（可再运行 la aware 继续）",
        "aware.repl_status_session": "[aware] session: {session}",
        "aware.repl_status_last_tick": "[aware] 上次 tick · {when}",
        "aware.repl_status_counts": (
            "[aware] 今日事件 {events} · suggestion {sug}"
        ),
        "aware.repl_answering": "围绕感知上下文回答…",
        "aware.repl_request_cancelled": "\n[aware] 请求已取消",
        "aware.repl_error": "[错误] {exc}",
        "aware.repl_empty_response": "[错误] 模型返回了空内容，请重试。",
        "aware.repl_ollama_failover": (
            "[aware] 本地 Ollama 响应过慢，已自动切换 {provider}"
        ),
        "aware.tick_skip_busy": "another tick is already running",
        "aware.tick_skip_no_sensors": (
            "无已授权且已实现的传感器；先 la aware grant fs git terminal browser apps"
        ),
        "aware.sched_launchd_missing": "未安装 LaunchAgent",
        "aware.sched_schtasks_missing": "未注册任务计划",
        "aware.sched_cron_on": "crontab 已含 aware tick",
        "aware.sched_cron_off": "crontab 未配置",
        "aware.sched_no_crontab": "本机无 crontab",
        "aware.sched_launchctl_manual": "需手动 load",
        "aware.sched_launchctl_suffix": " （launchctl: {msg}）",
        "aware.sched_schtasks_fail": "schtasks 创建失败",
        "aware.sched_schtasks_hint": "；可手动运行: la aware tick",
        "aware.sched_cron_write_fail": "crontab 写入失败",
        "aware.sched_cron_written": "已写入用户 crontab",
        "aware.sched_launchd_unloaded": "已卸载 LaunchAgent",
        "aware.sched_schtasks_deleted": "已删除任务计划",
        "aware.sched_cron_removed": "已从 crontab 移除",
        "aware.sensor_apps_front": "前台应用名称 / 窗口标题（System Events）",
        "aware.sensor_apps_media": "正在播放的曲目（Music / Spotify，若在播放）",
        "aware.sensor_apps_idle": "根据系统空闲时间估算输入活跃时长（按前台应用分桶）",
        "aware.sensor_apps_note": (
            "说明: 不记录按键内容；macOS 可能需「辅助功能 / 自动化」权限。"
        ),
        "aware.sensor_apps_macos_only": "apps 传感器当前仅支持 macOS",
        "aware.sensor_apps_osascript_fail": "osascript 失败: {exc}",
        "aware.sensor_apps_unknown_err": "未知错误",
        "aware.sensor_apps_no_front": "未读到前台应用",
        "aware.sensor_apps_parse_fail": "解析前台应用失败",
        "aware.sensor_apps_format_bad": "前台应用格式异常",
        "aware.sensor_browser_none": "（未发现浏览器 History 数据库）",
        "aware.sensor_browser_note": (
            "说明: 只读拷贝后查询；不读取 Cookie/密码。macOS Safari 可能需要「完全磁盘访问」。"
        ),
        "aware.sensor_git_workspace": "工作区（若为 git 仓库）: {path}",
        "aware.sensor_terminal_none": "（未发现 shell history 文件）",
        "aware.tabs_unsupported": (
            "当前平台暂不支持读取打开的标签页（仅 macOS）；可用 la aware --since 查看近期访问"
        ),
        "aware.tabs_osascript_fail": "osascript 失败: {exc}",
        "aware.tabs_unknown_err": "未知错误",
        "aware.tabs_permission_hint": (
            "请在「系统设置 → 隐私与安全性 → 自动化」中允许终端/LA 控制浏览器；"
            "Chrome 或需开启「查看 → 开发者 → 允许来自 Apple 事件的 JavaScript」。"
        ),
        "aware.tabs_error_with_hint": "{err}。{hint}",
        "aware.tabs_no_browser": "未检测到运行中的浏览器窗口（或缺少自动化权限）",
        "aware.tabs_parse_fail": "解析浏览器标签失败",
        # --- news ---
        "news.need_action": (
            "[news] 请指定子命令：sync | brief | skim | read | mark | schedule | interests | status"
        ),
        "news.unknown_action": "[news] 未知子命令: {action}",
        "news.sync_fail": "[news] sync 失败: {error}",
        "news.sync_done": (
            "[news] sync 完成: 拉取 {fetched} 条（新增 {inserted}，更新 {updated}）"
        ),
        "news.source": "[news] 源: {url}",
        "news.view_brief": "[news] 查看: la news brief",
        "news.not_found": "[news] 未找到: {target}",
        "news.read_fail": "[news] read 失败: {error}",
        "news.msg_prefix": "[news] {msg}",
        "news.sched_enabled": "已启用",
        "news.sched_disabled": "未启用",
        "news.sched_status": "[news] 定时 sync: {state}（{backend}）",
        "news.sched_time": "[news] 时间: 每天 {hour:02d}:{minute:02d}",
        "news.sched_detail": "[news] 详情: {detail}",
        "news.auto_sync": "[news] LA_NEWS_AUTO_SYNC={value}",
        "news.sched_error": "[news] {exc}",
        "news.sched_on_ok": (
            "[news] 已开启定时 sync：每天 {hour:02d}:{minute:02d}（{backend}）"
        ),
        "news.sched_off_ok": "[news] 已关闭定时 sync（{backend}）",
        "news.sched_unknown": "[news] 未知 schedule 动作: {sub}（on|off|status）",
        "news.interests_updated": "[news] 已更新 interests: {interests}",
        "news.interests_list": "[news] interests: {interests}",
        "news.mute_keywords": "[news] mute_keywords: {keywords}",
        "news.empty_parens": "（空）",
        "news.interests_line": "[news] interests: {value}",
        "news.boost_line": "[news] boost: {value}",
        "news.mute_line": "[news] mute: {value}",
        "news.brief_size": "[news] brief_size: {n}",
        "news.status_rss": "[news] RSS: {url}",
        "news.status_dir": "[news] 数据目录: {path}",
        "news.status_last_sync": "[news] 上次 sync: {when}",
        "news.status_never": "从未",
        "news.status_last_count": "[news] 上次条数: {n}",
        "news.status_last_error": "[news] 上次错误: {error}",
        "news.status_schedule": "[news] 定时: {state} {hour:02d}:{minute:02d} ({backend})",
        "news.status_sched_on": "开",
        "news.status_sched_off": "关",
        "news.status_interests": "[news] 兴趣: {interests}",
        "news.sources_default": "[news] 默认源 (BestBlogs RSS):",
        "news.sources_filter_hint": (
            "[news] 可用过滤参数示例: category=ai&minScore=85&featured=y&timeFilter=1d"
        ),
        "news.sources_override": (
            "[news] 覆盖: 环境变量 LA_NEWS_RSS_URL 或 la news sync --url …"
        ),
        "news.prefix_current": "【当前】",
        "news.prefix_skim": "【速读】",
        "news.no_summary": "（暂无摘要）",
        "news.section_detail": "详细摘要",
        "news.section_viewpoints": "主要观点",
        "news.section_quotes": "金句",
        "news.meta_selected": "入选  {reasons}",
        "news.meta_candidate": "候选",
        "news.meta_ai_score": "AI初评 {score}",
        "news.meta_mins": "{n}分钟",
        "news.meta_published": "发布  {bits}",
        "news.meta_id": "编号  {id}",
        "news.meta_url": "原文  {url}",
        "news.brief_title": "# 今日新闻简报 · {day}",
        "news.brief_count": (
            "共 {n} 条 · `la news read <id>` 精读 · 点击标题或原文链接打开浏览器"
        ),
        "news.brief_empty": "_暂无条目。先运行 `la news sync`。_",
        "news.brief_one_liner": "- 一句话: {summary}",
        "news.brief_why": "- 为何入选: {reason}",
        "news.brief_published": "- 发布: {day}",
        "news.brief_url": "- 原文: {url}",
        "news.brief_tip": (
            "提示: `la news skim <id>` 速读 · `la news mark <id> bookmark|skip`"
        ),
        "news.browser_today": "今日",
        "news.browser_header": "今日简报 · {day} · {pos}",
        "news.browser_empty": "（暂无条目）",
        "news.browser_help": (
            "键位: ↑↓/jk 切换  PgUp/PgDn/空格 滚动  o/Enter 打开浏览器\n"
            "      s 速读  r 精读并深聊  b 收藏  x 跳过  c 复制链接  ? 帮助  q/Esc 退出"
        ),
        "news.browser_opened": "已在浏览器打开",
        "news.browser_open_fail": "打开浏览器失败，可按 c 复制链接",
        "news.browser_skim_shown": "已显示速读卡 · 再按 ↑↓ 返回摘要",
        "news.browser_copied": "已复制原文链接到剪贴板",
        "news.browser_copy_fail": "复制失败: {url}",
        "news.browser_no_items": "[news] 暂无条目。先运行 `la news sync`。",
        "news.browser_enter": (
            "[news] 进入交互简报（↑↓ 切换 · PgDn/空格 滚动 · o 打开 · r 精读深聊 · q 退出）"
        ),
        "news.browser_list_empty": "[news] 列表已空。",
        "news.browser_quit": "[news] 已退出简报浏览器",
        "news.browser_reading": "[news] 精读: {title}",
        "news.browser_read_fail": "精读失败: {error}",
        "news.browser_back": "[news] 已返回简报浏览器",
        "news.browser_chat_done": "深聊结束 · 继续 ↑↓ 浏览",
        "news.browser_fetching": "抓取并总结原文…",
        # --- memory ---
        "memory.pending_empty": "[memory pending] 队列为空",
        "memory.pending_count": "[memory pending] {shown}/{total} 条待确认：",
        "memory.pending_more": "  … 另有 {n} 条，去掉 --limit 查看全部",
        "memory.pending_approve_hint": "  批准: LA memory approve <id>|--all",
        "memory.pending_reject_hint": "  拒绝: LA memory reject <id>|--all",
        "memory.approve_need_id": "[memory approve] 请指定 id 或 --all",
        "memory.approve_done": (
            "[memory approve] 已写入 Warm {n} 条；剩余待确认 {pending}"
        ),
        "memory.reject_need_id": "[memory reject] 请指定 id 或 --all",
        "memory.reject_done": "[memory reject] 已丢弃 {n} 条；剩余待确认 {pending}",
        "memory.search_forget_hint": "→ LA memory forget <id>  删除某条记忆",
        "memory.status_title": "[memory status] Warm 层记忆引擎诊断",
        "memory.status_backend": "  当前后端:     {backend} ({cls})",
        "memory.status_preference": "  配置偏好:     {preference} (LA_MEMORY_BACKEND)",
        "memory.status_python": "  Python:       {version}",
        "memory.status_mem0": "  Mem0:         {state}",
        "memory.installed": "已安装",
        "memory.not_installed": "未安装",
        "memory.on": "开启",
        "memory.off": "关闭",
        "memory.status_infer": "  Infer:        {state} (LA_MEM0_INFER)",
        "memory.status_llm": "  LLM:          {provider}/{model}",
        "memory.status_embedder": (
            "  Embedder:     {provider}/{model} (dims={dims})"
        ),
        "memory.status_retain_fallback": (
            "  Retain 降级:  {state} (LA_MEM0_RETAIN_JSON_FALLBACK)"
        ),
        "memory.status_mem0_dir": "  Mem0 数据:    {path}",
        "memory.status_count": "  记忆条数:     {n}",
        "memory.status_unindexed": (
            "  未入向量:     {n} （JSON 有记录但未进 Mem0/Qdrant，可 LA memory reindex）"
        ),
        "memory.status_sources": (
            "  来源分布:     chat={chat}  chatgpt={chatgpt}  file={file}  other={other}"
        ),
        "memory.status_chat_sessions": (
            "  LA 对话档案:  {sessions} 个会话（已记忆化索引 {ingested}）"
        ),
        "memory.status_chatgpt": "  ChatGPT 导入: 已处理 {n} 条",
        "memory.status_cold": (
            "  Cold 对话块:  chat={chat}  chatgpt={chatgpt}  (LA rag search 可召回)"
        ),
        "memory.status_hot_profile": "  Hot 画像:     {state} ({path})",
        "memory.configured": "已配置",
        "memory.not_configured": "未配置",
        "memory.status_graph": (
            "  关系图:       {state} (LA_MEMORY_GRAPH；LA memory graph stats)"
        ),
        "memory.status_profile_pin": "  Profile pin:  {mode} (LA_PROFILE_PIN_LLM)",
        "memory.pin_llm": "LLM",
        "memory.pin_regex": "正则",
        "memory.status_bank": "  Bank ID:      {bank_id}",
        "memory.status_store": "  本地索引:     {path}",
        "memory.status_error": "  错误:         {error}",
        "memory.status_json_fallback_hint": (
            "\n提示: Mem0 初始化失败时会回退到 JSON。检查 Ollama 嵌入模型或 LA_MEM0_EMBEDDER_*。"
        ),
        "memory.status_unindexed_hint": "提示: 存在未入向量索引的记忆，语义召回可能不完整。",
        "memory.status_next": "\n下一步:",
        "memory.status_next_query": "  LA memory query              浏览最近记忆",
        "memory.status_next_search": "  LA memory search <q>         语义搜索",
        "memory.status_next_ingest": "  LA ingest chat|chatgpt|text  持久记忆化（写入入口）",
        "memory.type_preference": "偏好",
        "memory.type_fact": "事实",
        "memory.type_plan": "计划",
        "memory.type_experience": "经历",
        "memory.type_observation": "观察",
        "memory.type_world": "世界知识",
        "memory.unknown_time": "未知时间",
        "memory.untitled": "未命名记忆",
        "memory.unknown_source": "未知来源",
        "memory.relevance": "相关度 {score:.2f}",
        "memory.source_label": "来源: {source}",
        "memory.time_anchor": "时间锚点: {anchor}",
        "memory.semantic_temporal": "语义 {semantic:.2f} · 时间衰减 {temporal:.2f}",
        "memory.char_count": "原始长度: {n} 字",
        "memory.found_n": "找到 {n} 条相关记忆",
        "memory.found_query": "（查询: {query}）",
        "workspace.purged": "[workspace] 已清理 {removed} 条终态待办",
        "workspace.no_tasks": "[workspace] 无任务记录（{root}）",
        "workspace.all_tasks": "[workspace] 全部任务 ({root}) · {n} 条",
        "workspace.rejected": "[workspace] 未创建: {exc}",
        "workspace.added": "[workspace] 已添加 [{id}] {title}",
        "workspace.why": "  为何: {rationale}",
        "workspace.done_hint": "  → la workspace done {id}",
        "workspace.not_found": "[workspace] 未找到该待办",
        "workspace.done": "[workspace] 已完成 [{id}] {title}",
        "workspace.dismissed": "[workspace] 已丢弃 [{id}] {title}",
        "workspace.snoozed": "[workspace] 已搁置 [{id}] {title} → {until}",
        "workspace.reject_title": "title 至少 {n} 个字符",
        "workspace.reject_rationale": (
            "rationale（--why）至少 {n} 个字符，说明为何值得占用注意力"
        ),
        "workspace.reject_source": "非法 source: {source}",
        "workspace.reject_dup": "已有相同待办 [{id}]: {title}",
        "workspace.reject_recent": "近 7 日内已提议过相同待办 [{id}]: {title}",
        "workspace.reject_daily": "今日 agent 入队已达上限（{limit}）",
        "workspace.line_expires": "  ·到期 {exp}",
        "workspace.line_why": "    为何: {rationale}",
        "workspace.line_hint": "    办完: {hint}",
        "workspace.line_evidence": "    旁证: {evidence}",
        "workspace.line_actions": (
            "    → la workspace done {id}  |  dismiss {id}  |  snooze {id}"
        ),
        "workspace.open_empty": (
            "工作区托管待办: 无（{root}）\n提示: la workspace add \"…\" --why \"…\""
        ),
        "workspace.open_header": "工作区托管待办 ({count} 条 open，显示前 {shown}):",
        "workspace.summary_empty": (
            "托管待办: 无\n提示: la workspace add \"标题\" --why \"理由\""
        ),
        "workspace.summary_header": "托管待办 ({count} 条 open，显示前 {shown}):",
        "workspace.summary_more": "  … 共 {count} 条；la workspace tasks / done <id>",
        "workspace.summary_actions": (
            "  完成: la workspace done <id>  |  搁置: snooze <id>  |  丢弃: dismiss <id>"
        ),
        "workspace.git_error": "Git: {error}",
        "workspace.git_not_repo": "Git: 当前目录不是 git 仓库",
        "workspace.git_branch": "Git 分支: {branch}",
        "workspace.git_clean": "工作区: 干净（无未提交变更）",
        "workspace.git_staged": "已暂存 {n}",
        "workspace.git_unstaged": "未暂存 {n}",
        "workspace.git_untracked": "未跟踪 {n}",
        "workspace.git_dirty": "工作区: {parts}",
        "workspace.git_recent": "最近提交:",
        "workspace.diag_header": "[workspace] 诊断扫描（未入队）({root})",
        "workspace.diag_note": (
            "说明: 代码 TODO/checkbox 仅供参考；正式待办请用 la workspace tasks / add"
        ),
        "workspace.diag_empty": "  未扫描到可读的 TODO/FIXME 或未勾选 checkbox",
        "workspace.diag_hits": "[workspace] 诊断命中 {n} 条（未入队）",
        "workspace.root": "工作区: {root}",
        "workspace.recent_files": "最近 {days} 天修改的文件:",
        "workspace.no_recent": "  （无近期变更，或目录不可访问）",
        "workspace.files_more": "  … 共 {n} 个文件",
        "workspace.diag_summary_hits": "诊断扫描命中 {n}（未入队，显示前 5）:",
        "workspace.diag_summary_empty": "诊断扫描: 无命中（未入队）",
        "summarize.no_sessions": "[summarize] 暂无文档对话会话",
        "summarize.resume_hint": (
            "[summarize] 续聊: la summarize <path> --resume  或  la summarize --id <id>"
        ),
        "summarize.session_not_found": "[summarize] error: 未找到会话 {id}",
        "summarize.session_file_missing": "[summarize] error: 会话文件不存在: {path}",
        "summarize.need_path": "[summarize] error: 请指定文件路径，或使用 --list / --id",
        "summarize.multi_no_chat": "[summarize] error: 多文件仅支持仅速读模式，请加 --no-chat",
        "summarize.no_existing": "[summarize] 无既有会话，将新建文档对话",
        "summarize.file": "[summarize] 文件: {path}",
        "summarize.interrupted": "\n[summarize] 已中断",
        "summarize.error": "[summarize] error: {exc}",
        "summarize.chars": "{n} 字",
        "summarize.pages": "{n} 页",
        "summarize.ocr": "OCR",
        "summarize.ocr_pages": "{n} 页 OCR",
        "summarize.ocr_conf": "avg_conf={conf}",
        "summarize.llm": "LLM",
        "summarize.heuristic": "启发式",
        "ocr.usage": "[ocr] 用法: la ocr <path> [--out FILE] [--keep] [--json]",
        "ocr.error": "[ocr] error: {exc}",
        "ocr.interrupted": "\n[ocr] 已中断",
        "ocr.wrote": "[ocr] 已写入: {path}",
        "ocr.meta_prefix": "[ocr] {meta}",
        "ocr.meta_file": "{filename}",
        "ocr.meta_conf": "avg_conf={conf}",
        "ocr.meta_lines": "{n} 行",
        "ocr.meta_pages": "{n} 页",
        "ocr.warning": "[ocr] 注意: {warning}",
        "ocr.kept": "[ocr] 已收藏到知识库: {target}",
        "summarize.warning": "[summarize] 注意: {warning}",
        "summarize.kept": "[summarize] 已收藏到知识库: {target}",
        "summarize.not_kept": "[summarize] 未收藏（默认）。{hint}",
        "summarize.keep_hint": (
            "默认不入库（瞬时读懂）。需要收藏到知识库时："
            "文档对话内输入 /keep，或启动时加 --keep / `la summarize <path> --no-chat --keep`。"
        ),
        "summarize.wrote": "[summarize] 已写入: {path}",
        "summarize.file_updated": "[summarize] 文件已更新，重新生成速读卡…",
        "summarize.resume_session": "[summarize] 续聊会话 {id} · {filename}",
        "summarize.not_kept_resume": (
            "[summarize] 未收藏（默认）。会话内输入 /keep 可收藏到知识库。"
        ),
        "summarize.help_intro": (
            "当前是「文档对话」：只围绕已打开的文件；和助手闲聊请另开 la chat。"
        ),
        "summarize.help_commands": "命令：",
        "summarize.help_summary": "  /summary, /s     重新显示速读卡",
        "summarize.help_keep": "  /keep            收藏当前文档到知识库（默认不入库）",
        "summarize.help_keep_again": "                   （已收藏，再执行会提示路径）",
        "summarize.help_status": "  /status          显示文件路径 / 是否已收藏 / session",
        "summarize.help_help": "  /help, /h        显示本帮助",
        "summarize.help_provider": "  /provider, /p    切换模型路径",
        "summarize.help_quit": (
            "  /q, /quit, /exit 结束文档对话（可 la summarize <path> --resume 续聊）"
        ),
        "summarize.help_ask": "直接输入问题即可围绕该文档深入追问。",
        "summarize.entered": (
            "[summarize] 已进入文档对话：{filename}{pages}"
            "（session={session}）"
        ),
        "summarize.pages_suffix": " · {n} 页",
        "summarize.enter_hint": "[summarize] 可继续追问本文件；/help 查看命令，/exit 结束。",
        "summarize.retrieval_mode": (
            "[summarize] 长文模式：按问题检索原文片段（index={index}）"
        ),
        "summarize.not_kept_repl": "[summarize] 未收藏。会话内输入 /keep 可收藏到知识库。",
        "summarize.kept_path": "[summarize] 已收藏: {target}",
        "summarize.cancel_once": "\n[summarize] 已取消；再按一次 Ctrl+C 退出，或继续提问",
        "summarize.ended": "[summarize] 文档对话结束（可用 la summarize <path> --resume 续聊）",
        "summarize.status_kept": "已收藏 → {target}",
        "summarize.status_not_kept": "未收藏（默认；/keep 写入知识库）",
        "summarize.status_file": "[summarize] 文件: {path}",
        "summarize.status_kept_label": "[summarize] 收藏: {kept}",
        "summarize.status_session": "[summarize] session: {session}",
        "summarize.status_archive": "[summarize] 对话档案: {session}",
        "summarize.status_chars": "[summarize] 字数: {n}",
        "summarize.status_pages": "[summarize] 页数: {n}",
        "summarize.keep_fail": "[summarize] 收藏失败: {exc}",
        "summarize.answering": "围绕文档回答…",
        "summarize.request_cancelled": "\n[summarize] 请求已取消",
        "summarize.ollama_failover": (
            "[summarize] 本地 Ollama 响应过慢，已自动切换 {provider}"
        ),
        "summarize.read_fail": "无法读取文件: {path}",
        "polish.scene": "场景={label}",
        "polish.audience": "读者={audience}",
        "polish.attitude": "态度={attitude}",
        "polish.risks": "风险={risks}",
        "polish.style": "文风={note}",
        "polish.low_conf": "置信偏低·按默认场景处理",
        "polish.tag_detect": "【识别】",
        "polish.tag_primary": "【主推】",
        "polish.tag_alt": "【备选·{label}】",
        "polish.tag_changes": "【改动】",
        "polish.default_changes": "微调措辞与语气",
        "polish.unspecified": "未指定",
        "polish.status_model": "调用模型…",
        "polish.status_detect": "识别场景与态度…",
        "polish.status_rewrite": "改写中…",
        "polish.empty_draft": "草稿为空",
        "polish.no_rewrite": "模型未返回可用改写结果，请稍后重试或切换 /provider",
        "polish.no_primary": "模型未给出主推正文",
        "polish.label_primary": "主推",
        "polish.label_alt": "备选·{label}",
        "polish.copied_primary_interactive": (
            "✓ 已复制【主推】到剪贴板 · 按 2={soft} / "
            "3={firm} 换拷 · 1=再拷主推 · Enter/n 结束"
        ),
        "polish.copied_primary": "✓ 已复制【主推】到剪贴板",
        "polish.clipboard_unavailable": "剪贴板不可用，请手动复制【主推】区块",
        "polish.copy_prompt": "复制> ",
        "polish.copy_ended": "已结束复制",
        "polish.invalid_choice": (
            "无效选项: {choice!r}（1=主推 / 2={soft} / 3={firm} / n）"
        ),
        "polish.copied_label": "✓ 已复制【{label}】到剪贴板",
        "polish.copy_failed": "复制【{label}】失败，请手动复制",
        "polish.usage": (
            "[polish] 用法: la polish [--scene email|moments|resume|biz] "
            "[--tone …] [--no-copy] [--file path] <草稿>\n"
            "       echo \"草稿\" | la polish\n"
            "会话内: /polish <草稿>"
        ),
        "polish.unknown_scene": (
            "[polish] error: 未知场景 {scene!r}（可用: {scenes}）"
        ),
        "polish.status_working": "识别场景并改写…",
        "polish.interrupted": "\n[polish] 已中断",
        "polish.error": "[polish] error: {exc}",
        "polish.file_missing": "文件不存在: {path}",
        "audit.summary_title": "[audit] 摘要{range}",
        "audit.calls_line": "  调用: {calls}  Token: {tokens}  估算费用: ${cost:.4f}",
        "audit.provider_line": "    {name}: {calls} 次, {tokens} tokens, ${cost:.4f}",
        "audit.behavior_line": (
            "行为: shell={shell}  write={write}  web={web}  护栏={guard}"
        ),
        "audit.blocked_denied": "  拦截 blocked={blocked}  拒绝 denied={denied}",
        "audit.memory_health_line": (
            "记忆健康: facts={facts} · kb={kb} · indexed={indexed}"
        ),
        "audit.workspace_header": "工作区（摘要）:",
        "audit.export_hint": (
            "→ LA audit --report report.md  导出 Markdown；--report report.html 导出 HTML"
        ),
        "audit.report_written": "[audit] 报告已写入 {path}",
        "audit.md_title": "# LocalAgent 审计报告",
        "audit.md_generated": "生成时间: {when}",
        "audit.md_range": "统计范围: {range}",
        "audit.md_range_since": "（自 {since}）",
        "audit.md_range_all": "（全部记录）",
        "audit.md_workspace": "工作区: `{workspace}`",
        "audit.md_usage": "## Token 与服务花费",
        "audit.md_calls": "- 调用次数: {n}",
        "audit.md_tokens": "- Token 合计: {n}",
        "audit.md_cost": "- 估算费用 (USD): ${cost:.4f}",
        "audit.md_by_provider": "### 按 Provider",
        "audit.md_table_provider": "| Provider | 调用 | Token | 估算费用 (USD) |",
        "audit.md_by_command": "### 按命令类型",
        "audit.md_cmd_count": "- `{cmd}`: {n} 次",
        "audit.md_by_model": "### 按模型",
        "audit.md_table_model": "| 模型 | 调用 | Token | 估算费用 (USD) |",
        "audit.md_security": "## 文件安全",
        "audit.md_security_none": "未发现高风险项。",
        "audit.md_security_count": "共 {n} 项（高危 {high}）",
        "audit.md_table_security": "| 级别 | 路径 | 说明 | 建议 |",
        "audit.md_behavior": "## Agent 行为与护栏",
        "audit.md_shell": "- 本地命令 `run_shell`: {n} 次",
        "audit.md_write": "- 写文件 `write_file`: {n} 次",
        "audit.md_web": "- 联网查询 `web_search`: {n} 次",
        "audit.md_guard": "- 护栏触发: {n} 次",
        "audit.md_outcomes": "### 工具决策结果",
        "audit.md_blocked": "### 本周期拦截",
        "audit.md_denied": "### 用户拒绝",
        "audit.md_no_behavior": "暂无行为事件记录。",
        "audit.md_memory": "## 记忆健康",
        "audit.md_ws_snap": "## 工作区快照",
        "audit.md_footer": "*费用为基于默认单价的估算，可在 .env 中设置 LA_COST_* 覆盖。*",
        "audit.html_title": "LocalAgent 审计报告",
        "audit.sec_ok": "文件安全: 未发现高风险项",
        "audit.sec_header": "文件安全: {n} 项发现（高危 {high}）",
        "audit.sec_more": "  … 共 {n} 项",
        "audit.sec_world_readable": "文件对其他用户可读",
        "audit.sec_world_fix": "考虑 chmod 600 或移出索引目录",
        "audit.sec_aws_key": "可能的 AWS Access Key",
        "audit.sec_openai_key": "可能的 OpenAI/API sk- 密钥",
        "audit.sec_private_key": "私钥内容",
        "audit.sec_secret_fix": "从 kb/ 移除该文件，轮换已泄露密钥，检查 git 历史",
        "audit.sec_symlink_bad": "软链目标无法解析",
        "audit.sec_symlink_fix": "检查 LA add-file 源路径是否有效",
        "audit.sec_sensitive_name": "索引了敏感文件名（.env、密钥等）",
        "audit.sec_sensitive_fix": "LA reset-memory 后删除 kb/ 软链，勿将密钥文件加入索引",
        "audit.sec_env_indexed": "工作区 .env 已被索引到 kb/",
        "audit.sec_env_fix": "删除 kb/.env 软链并 reset-memory 中相关条目",
        "audit.sec_path_blocked": "敏感路径禁止索引/读取: {name}",
        "audit.health_facts": "记忆条目: {n}",
        "audit.health_kb": "kb/ 文件: {kb}，已索引: {indexed}",
        "audit.health_failed": "失败的后台索引任务: {n}",
        "audit.health_orphan": "sync_index 孤儿条目: {n}",
        "audit.health_missing": "kb/ 未索引文件: {n}",
        "audit.health_note_ingest": "存在 kb/ 文件未索引，运行 LA rag ingest",
        "prompt.reply_lang": "请用简洁完整的中文回答。",

        "prompt.retry_incomplete": (
            "你的上一条回答不完整或被截断了。"
            "请基于已有工具结果，用简洁完整的中文直接给出最终答案，不要再调用工具。"
        ),
        "prompt.aware_summary": (
            "根据本机感知事实卡，用中文写 3～6 行动态（不要标题）。"
            "时间范围：{window}；须覆盖该整段窗口，按日期/时段组织主次。\n"
        ),
        "prompt.tone_evening_chat": (
            "### 夜深收束（本地时间已晚）\n"
            "正事完整说完后，若本回合是对用户的最终自然语言答复，可在末尾空一行加一句收束，"
            "优先用：「夜深了，早点休息哦。」\n"
            "规则：\n"
            "- 先把问题答完；收束不得插入正文、代码块或列表中间\n"
            "- 只要产物/JSON/补丁、工具确认中、或用户在连续追问调试时：不要加\n"
            "- 本会话若已出现过休息提醒：不要再加\n"
            "- 禁止情绪诊断、禁止长篇劝健康、禁止卖陪伴\n"
        ),
        "prompt.tone_evening_aware": (
            "夜深收束：动态写完后可选末行一句「夜深了，收工休息也不迟。」"
            "勿插入事实中间；勿情绪诊断或鸡汤。\n"
        ),
        "prompt.memory_summarize": (
            "请用简洁中文（或原文语言）概括下列内容，保留关键事实、人名、时间与结论。"
        ),
        "prompt.reflect_answer": "问题：{query}\n\n证据：\n{evidence}\n\n请用简洁中文回答：",
        "prompt.polish_system": (
            "你是资深中文写作润色编辑。根据场合态度改写草稿，保留原意与事实。\n"
        ),
        "prompt.deep_report": "基于以下多轮搜索结果，撰写关于「{topic}」的深度研究报告（中文，结构化）：\n\n",
    },
    "en": {
        "banner.tips_title": "Getting started",
        "banner.tip_chat": "Type a question to start chatting",
        "banner.tip_tab": "/ + Tab to complete commands",
        "banner.tip_help": "/help for all commands",
        "banner.tip_status": "/status for data layers",
        "banner.tip_provider": "/provider to switch model path",
        "banner.tip_model": "/model to switch default model",
        "banner.tip_websearch": "/websearch <query> for the web",
        "banner.tip_deepsearch": "/deepsearch <topic> to research",
        "banner.tip_quit": "/q or Ctrl+C×2 to quit",
        "banner.daily_actions": "Daily Actions",
        "banner.daily_fallback": "la status for today's signals",
        "banner.data_layers": "Data layers",
        "banner.layers_fallback": "la status for data layers",
        "banner.web_search": "Web · {label}",
        "web_search.ddgs": "ddgs (free)",
        "session.help_header": (
            "In-session commands (after la / la chat; prefix with /; : is a legacy alias):"
        ),
        "session.help_help": "  /help, /h              Show this help",
        "session.help_status": "  /status                Today's signals + data layers (Hot/Warm/Cold/Aware)",
        "session.help_provider": "  /provider, /p [name]   Show or switch model path",
        "session.help_model": "  /model [name|N]        List/page/switch model for current path (persisted)",
        "session.help_model_page": "                          Page: next|prev|page N; index is 1–10 on this page",
        "session.help_memory": "  /memory [action]       Memory overview; no args → status (same as la memory)",
        "session.help_rag": "  /rag [action]          Knowledge overview; no args → status (same as la rag)",
        "session.help_reflect": "  /reflect <question>    Reason: memory → knowledge → synthesize",
        "session.help_websearch": "  /websearch <query>     Web search",
        "session.help_deepsearch": "  /deepsearch <topic>    Multi-step web research",
        "session.help_polish": "  /polish <draft>        One-shot polish (scene detect + copy primary)",
        "session.help_quit": "  /q, /quit, /exit       Leave chat",
        "session.help_equiv": "Outer la <command> matches in-session /<command> (except /chat).",
        "session.help_shortcuts": (
            "Shortcuts: /add → /ingest text, /search → /memory search, /forget → /memory forget."
        ),
        "session.missing_cmd": "[LA] Missing command. Type /help for available commands.",
        "session.already_chat": (
            "[LA] Already in chat; /chat is not needed. Type a question, or /help for commands."
        ),
        "session.provider_current": "Current path: {hint}",
        "session.provider_usage": "Usage: /provider auto|{providers}",
        "session.provider_switched": "[provider] Switched to {hint}",
        "session.model_empty": "No model list available (you can still /model <name>).",
        "session.model_usage": "Usage: /model <name>",
        "session.model_list": "Models ({total}) page {page}/{pages}:",
        "session.model_page_hint": "Page: /model next|prev|page N",
        "session.model_select": "Pick: /model <1-{n}> or full name",
        "session.model_set": "[model] Set default model for {provider} to {model}",
        "session.model_wrote": "[model] Wrote {path} (used on next launch)",
        "session.model_path_auto": "Current path: auto → {effective}",
        "session.model_path": "Current path: {effective}",
        "session.model_current": "Current model: {current}",
        "session.model_unset": "(unset)",
        "session.model_no_page": "[model] No model list to page. Use /model <name> directly.",
        "session.model_page_usage": "Usage: /model page <1-{pages}>",
        "session.model_bad_index": (
            "[model] Invalid index; enter 1–{n} on this page (list with /model or /model next)"
        ),
        "session.model_not_in_list": (
            "[model] Note: {name!r} is not in the current list; writing config anyway"
        ),
        "session.deepsearch_usage": "Usage: /deepsearch <topic>",
        "session.deepsearch_working": "Researching: {topic}",
        "session.deepsearch_cancelled": "\n[chat] deepsearch cancelled",
        "session.deepsearch_failed": "[deepsearch failed] {exc}",
        "session.empty_cmd": "[LA] Empty command. Type /help for available commands.",
        "session.m_deprecated": (
            "[LA] /m is deprecated (easy to confuse with model / memory). "
            "Use /model to switch models, /memory query for memories."
        ),
        "session.interrupted": "\n[LA] Interrupted",
        "session.cmd_failed": "[LA] Command failed: {exc}",
        "chat.warn_openai_key": (
            "[chat] Warning: openai api_key is not set."
            " Run la config set-key openai <key> or /config set-key openai <key> in chat."
        ),
        "chat.hint_ollama_slow": (
            "[chat] Tip: if local Ollama is slow, try /provider {alt} for speed"
        ),
        "chat.cancel_once": "\n[chat] Cancelled; Ctrl+C again to quit, or keep typing",
        "chat.processing": "Working…",
        "chat.request_cancelled": "\n[chat] Request cancelled",
        "chat.error": "[error] {exc}",
        "chat.empty_response": "[error] Model returned empty content; please retry.",
        "chat.ollama_failover": "[chat] Local Ollama was too slow; switched to {provider}",
        "approval.deny_rm_root": "Deleting the filesystem root is blocked",
        "approval.deny_mkfs": "Formatting disks is blocked",
        "approval.deny_dd_dev": "Writing block devices directly is blocked",
        "approval.deny_overwrite_disk": "Overwriting disk devices is blocked",
        "approval.deny_fork_bomb": "Fork bombs are blocked",
        "approval.risk_rm": "Delete files/directories",
        "approval.risk_sudo": "Run with admin privileges",
        "approval.risk_chmod": "Change file permissions",
        "approval.risk_chown": "Change file ownership",
        "approval.risk_mv_cp": "Move/copy files",
        "approval.risk_destructive": "Destructive file operation",
        "approval.risk_find_delete": "Bulk delete via find",
        "approval.risk_force_push": "Force push",
        "approval.risk_hard_reset": "Hard reset",
        "approval.risk_git_clean": "Force-clean working tree",
        "approval.risk_kill": "Kill process",
        "approval.risk_pipe_sh": "Download and execute a script",
        "approval.risk_eval": "Dynamic code execution",
        "approval.risk_redirect": "Redirect write to absolute path",
        "approval.risk_dd": "Low-level disk I/O",
        "approval.risk_power": "Shutdown/reboot",
        "approval.risk_uninstall": "Uninstall packages",
        "approval.empty_cmd": "(empty command)",
        "approval.path_unset": "(path not specified)",
        "approval.write_append": "append",
        "approval.write_overwrite": "overwrite",
        "approval.write_reason": "{action} local file",
        "approval.write_summary": "{path} ({action}, {n} chars)\nPreview: {preview}",
        "approval.edit_all": "replace all",
        "approval.edit_one": "replace once",
        "approval.edit_reason": "Precise edit of a local file",
        "approval.label_shell": "run a command",
        "approval.label_edit": "edit a file",
        "approval.label_write": "write a file",
        "approval.request": "⚠ Agent wants to {label}; confirm before it runs.",
        "approval.risk_line": "Risk: {reason}",
        "approval.cmd_line": "Command: {cmd}",
        "approval.cwd_line": "Directory: {cwd}",
        "approval.target_line": "Target: {summary}",
        "approval.q_dangerous": "⚠ This looks dangerous. Proceed anyway?",
        "approval.q_session": "Allow? (a = don't ask again for similar safe ops this session)",
        "approval.q_default": "Allow this action?",
        "approval.blocked": "Error: {reason}.",
        "approval.blocked_default": "blocked by safety policy",
        "approval.denied": "User denied this action.",
        "cli.description": (
            "LocalAgent — The AI that lives on your computer.\n"
            "Local First. Memory Forever. Actions Automated.\n\n"
            "Main paths:\n"
            "  la / la chat     Chat\n"
            "  la setup [-y]    Install/pull local Ollama models\n"
            "  la config …      Local-only or bring-your-own API setup\n"
            "  la status        Today's signals + data layers (Hot/Warm/Cold/Aware)\n\n"
            "Day-to-day: memory / rag / audit; ops/experiments: tasks / logs / graph, etc."
        ),
        "cli.epilog": (
            "Examples:\n"
            "  la                  # enter chat (same as la chat)\n"
            "  la setup -y         # one-shot local model setup\n"
            "  la config list      # show config\n"
            "  la memory pending   # confirm pending memories\n"
            "  la ingest doc notes.md  # persist a document into memory\n"
            "  la ingest text \"…\" # write a single fact\n"
            "  la summarize doc.md # one-shot summary (not ingested by default)\n"
            "  la news brief       # today's news brief (run la news sync first)\n"
            "  la aware                  # current state + last 3h (--since / tick)\n"
            "  la polish \"nudge draft\"  # one-shot polish (copies primary by default)\n"
            "\n"
            "In chat, use /<command> (type /help; : is a legacy alias).\n"
            "Use LA <command> -h for full help on a command."
        ),
        "cli.chat_help": (
            "[--session-id ID] [-p auto|{providers}]  [main] interactive chat"
        ),
        "cli.chat_desc": "Start the interactive chat REPL (main path)",
        "cli.version_help": "Show version and exit",
        "cli.debug_help": "Enable DEBUG diagnostic logs (file + stderr)",
        "status.section_layers": "── Data layers ──",
        "status.section_recall": "── Combined recall ──",
        "status.tips_header": "Tips:",
        "status.tip_news": "  la news brief          # today's briefing",
        "status.tip_pending": "  la memory pending      # review pending memories",
        "status.tip_memory": "  la memory status       # Warm / Hot engine diagnostics",
        "status.tip_rag": "  la rag status          # Cold knowledge diagnostics",
        "status.tip_tasks": "  la workspace tasks     # managed todos (done/dismiss/snooze)",
        "status.tip_add": "  la workspace add \"…\" --why \"…\"  # add a todo explicitly",
        "status.tip_scan": "  la workspace scan      # scan code TODOs (not enqueued)",
        "status.tip_aware": "  la aware               # current state + last 3h",
        "status.tip_aware_since": "  la aware --since 1w    # changes in the last week",
        "status.tip_aware_sug": "  la aware suggestion    # awareness suggestions (approve/reject)",
        "status.tip_ungrant": "  la aware ungrant …     # revoke monitoring grant",
        "daily.news_ready": "today's news ready",
        "daily.news_unsynced": "today's news not synced",
        "daily.news_line": "News · {news}",
        "daily.pending_line": "Memory pending · {n}",
        "daily.todo_line": "Workspace todos · {n}",
        "daily.aware_line": "Aware · today {events} events / suggestion {sug}",
        "layers.hot_configured": "Hot · configured · {prefs} prefs",
        "layers.hot_anchors": " · {n} anchors",
        "layers.hot_unset": "Hot · not configured",
        "layers.warm_banner": "Warm · {facts} facts · pending {pending}",
        "layers.cold_banner": "Cold · kb{kb} · dialog {dialog} · ChatGPT{chatgpt}",
        "layers.aware_banner": "Aware · today {n}",
        "layers.banner_detail_hint": "la status for details",
        "layers.hot_detail": "Hot   configured · {name} · {prefs} prefs · {anchors} anchors",
        "layers.hot_detail_unset": "Hot   not configured",
        "layers.warm_detail": (
            "Warm  {facts} facts · pending {pending}"
            " · sources chat={chat} chatgpt={chatgpt} file={file} other={other}"
        ),
        "layers.cold_detail": (
            "Cold  kb={kb}"
            " · chunks kb={kb_chunks} chat={chat} chatgpt={chatgpt}"
            " · LA sessions {sessions}"
            " · ChatGPT imported {imported}"
            " · bookmarks news={bookmarks}"
            " summarize={summarize}"
        ),
        "layers.aware_detail": "Aware today {events} events · suggestion {sug}",
        "layers.recall_order": (
            "Default order: Hot/Warm(personal) → Cold archive → session → web → workspace → aware"
        ),
        "layers.recall_time": (
            "Recency weighting on (memory half-life {recency:g}d / time-anchor decay {time_hl:g}d); "
            "STM questions promote session"
        ),
        "chat.status_connecting": "Connecting model ({hint})…",
        "chat.status_prefetch_personal": "Prefetching personal memory…",
        "chat.status_prefetch_archive": "Searching conversation archive…",
        "chat.status_prefetch_last_session": "Loading previous session…",
        "chat.status_prefetch_session": "Loading short-term chat…",
        "chat.status_prefetch_web": "Searching the web…",
        "chat.status_prefetch_workspace": "Loading workspace context…",
        "chat.status_prefetch_aware": "Loading local awareness…",
        "chat.status_generate": "Generating reply…",
        "chat.status_generate_cold": "Generating reply (local model first load may be slow)…",
        "chat.status_synthesize": "Synthesizing tool results (round {n})…",
        "chat.status_await_approval": "Waiting for your approval…",
        "chat.status_write_memory": "Writing long-term memory…",
        "chat.status_tool_call": "Calling {label}: {preview}",
        "chat.status_tool_call_plain": "Calling {label}…",
        "chat.tool_fallback": "tool",
        "ollama.ram_choose": "Detected {ram} RAM → selecting {model} ({label}, {size})",
        "ollama.ram_recommend": "Detected {ram} RAM → recommend {model} ({label}, {size})",
        "ollama.not_detected": "No local Ollama detected.",
        "ollama.tier_Mini": "Mini",
        "ollama.tier_轻量": "Light",
        "ollama.tier_推荐": "Recommended",
        "ollama.tier_高配": "High",
        "aware.title_overview": "LocalAgent · Aware · Overview",
        "aware.title_delta": "LocalAgent · Aware · Since last probe · Overview",
        "aware.title_window": "LocalAgent · Aware · {window} · Overview",
        "aware.title_since": "LocalAgent · Aware · {window} · Overview",  # alias
        "aware.title_detail_now": "LocalAgent · Aware · Now",
        "aware.title_detail_delta": "LocalAgent · Aware · Since last probe",
        "aware.section_focus": "Primary focus",
        "aware.section_state": "Current state",
        "aware.section_activity": "{window} (by attention)",
        "aware.section_by_attention": "{window} (by attention)",  # alias
        "aware.section_dynamics": "Awareness dynamics",
        "aware.section_episodes": "Recent episodes (by attention)",
        "aware.section_system": "System",
        "aware.no_focus": "  (no clear foreground focus)",
        "aware.no_snapshot": "  · no live snapshot (try la aware grant / open a browser)",
        "aware.no_live_snapshot": (
            "  · no live snapshot (try la aware grant / open a browser)"
        ),  # alias
        "aware.tip_overview": (
            "Tip: ask to enter aware> · --no-chat print only · --detail per source · tick"
        ),
        "aware.last_tick": "Last tick · {when}",
        "aware.never_run": "never run",
        "aware.never_ran": "never run",  # alias
        "aware.granted": "Granted · {sources}",
        "aware.granted_none": "none (la aware grant …)",
        "aware.unit_h": "hours",
        "aware.unit_d": "days",
        "aware.unit_w": "weeks",
        "aware.unit_m": "months",
        "aware.unit_y": "years",
        "aware.recent_n": "Last {n} {unit}",
        "aware.period_dawn": "early morning",
        "aware.period_morning": "morning",
        "aware.period_afternoon": "afternoon",
        "aware.period_evening": "evening",
        "aware.period_night": "night",
        "aware.period_late": "late night",
        "aware.period_latenight": "late night",  # alias
        "aware.daypart_day": "daytime",
        "aware.daypart_night": "night",
        "aware.daypart_late": "late night",
        "aware.daypart_latenight": "late night",  # alias
        "aware.since_invalid": (
            "Invalid --since: {value!r} (format: <N>h|<N>d|<N>w|<N>m|<N>y, e.g. 3h, 2d, 1w)"
        ),
        "aware.input_idle": "Today's input activity: none yet (sampled; mostly idle)",
        "aware.input_active": "Today's input activity: ~{minutes:.0f} min",
        "aware.input_active_apps": "Today's input activity: ~{minutes:.0f} min ({apps})",
        "aware.input_idle_window": (
            "{window} input activity: none yet (sampled; idle or foreground-only)"
        ),
        "aware.input_active_window": "{window} input activity: ~{minutes:.0f} min",
        "aware.input_active_apps_window": (
            "{window} input activity: ~{minutes:.0f} min ({apps})"
        ),
        "aware.current_prefix": "Current:",
        "aware.viewing": "viewing",
        "aware.bg_selected": "bg-selected",
        "aware.not_viewing": "not viewing",
        "aware.tabs_unit": "tabs",
        "aware.unauthorized": "not granted",
        "aware.no_change": "no new changes since last probe",
        "aware.no_change_delta": "no new changes since last probe",  # alias
        "aware.mode_now": "Mode: current overview (current state + activity window {window})",
        "aware.mode_delta": "Mode: since last probe",
        "aware.mode_window": "Mode: time window · {window}",
        "aware.heuristic_primary": "Primary: {text}",
        "aware.heuristic_secondary": "Secondary: {text}",
        "aware.heuristic_almost_none": "Almost none: background-selected tabs (not browsing)",
        "aware.heuristic_empty": (
            "No recorded awareness activity recently (try la aware grant / tick)"
        ),
        "aware.detail_unauthorized": "  (not granted · la aware grant {name})",
        "aware.unauthorized_grant": "  (not granted · la aware grant {name})",  # alias
        "aware.detail_tip": "Tip: la aware | --detail | --since 1w | tick | grant / ungrant",
        "aware.detail_no_data": "  (no data)",
        "aware.episode_empty": "(no episodes in window)",
        "aware.episode_cmds": " · {n} commands",
        "aware.episode_chars": " · ~{n} chars",
        "aware.episode_fs_title": "{scene} · +{created}/~{modified}",
        "aware.episode_term_title": "Terminal session · {n} commands",
        "aware.episode_git_title": "git · {n} changes",
        "aware.episode_terminal": "Terminal session · {n} commands",  # alias
        "aware.episode_git": "git · {n} changes",  # alias
        "aware.episode_files": "{scene} · +{created}/~{modified}",  # alias
        "aware.episode_sensitive_browse": "Sensitive browsing (duration only)",
        "aware.episode_sensitive_page": "Sensitive browse page (duration only)",
        "aware.episode_sensitive_fg": "Sensitive foreground (duration only)",
        "aware.cmd_unknown": "[aware] Unknown subcommand: {action}",
        "aware.status_title": "LocalAgent · Aware",
        "aware.status_last_tick": "Last tick · {when}",
        "aware.status_never": "never run",
        "aware.status_sched_on": "on",
        "aware.status_sched_off": "off",
        "aware.status_schedule": (
            "Schedule · {state} ({backend}, every {minutes} min) · {detail}"
        ),
        "aware.status_counts": "Today's events · {events}  |  suggestion · {sug}",
        "aware.status_grants": "Grants (grant / ungrant):",
        "aware.status_not_impl": " (not implemented)",
        "aware.status_hint_ungrant": "  → ungrant {name}",
        "aware.status_view_hint": "View: la aware · la aware --since 1w · la aware tick",
        "aware.status_ungrant_hint": "Revoke: la aware ungrant <source>|all",
        "aware.status_sug_hint": "Suggestions: la aware suggestion · approve|reject",
        "aware.grant_usage": "[aware] Usage: la aware grant <source>|all …",
        "aware.grant_choices": "[aware] Choices: all {sources}",
        "aware.grant_unknown": "[aware] Unknown source: {source}",
        "aware.grant_not_impl": "[aware] {source} not implemented yet; skipped",
        "aware.grant_will": "[aware] Will grant read access ({source}):",
        "aware.grant_confirm": "Grant {source}?",
        "aware.grant_cancelled": "[aware] Cancelled: {source}",
        "aware.grant_no_browser": "[aware] No browser History found; grant recorded anyway",
        "aware.grant_ok": "[aware] Granted: {source}",
        "aware.ungrant_usage": "[aware] Usage: la aware ungrant <source>|all",
        "aware.ungrant_unknown": "[aware] Unknown source: {source}",
        "aware.ungrant_ok": (
            "[aware] Revoked: {source} · re-grant with la aware grant {source}"
        ),
        "aware.paths_list": "[aware] fs watch paths:",
        "aware.paths_not_dir": "[aware] Not a directory: {path}",
        "aware.paths_hint_grant": (
            "[aware] Note: fs not granted yet; run la aware grant fs"
        ),
        "aware.paths_added": "[aware] Added: {path}",
        "aware.paths_removed": "[aware] Removed: {path}",
        "aware.paths_usage": "[aware] paths subcommands: list | add | rm",
        "aware.schedule_status": (
            "[aware] schedule: {state} backend={backend} every={minutes}m · {detail}"
        ),
        "aware.schedule_on_fail": "[aware] schedule on failed: {exc}",
        "aware.schedule_on_ok": "[aware] schedule on · {backend} · {detail}",
        "aware.schedule_off_ok": "[aware] schedule off · {detail}",
        "aware.schedule_usage": "[aware] schedule subcommands: on | off | status",
        "aware.tick_skipped": "[aware] tick skipped: {reason}",
        "aware.tick_auto": "  auto · {line}",
        "aware.tick_sug_new": "  suggestion added · {n} (la aware suggestion)",
        "aware.tick_error": "  ! {err}",
        "aware.sug_usage": "[aware] suggestion subcommands: list | approve | reject",
        "aware.sug_empty": "[aware] suggestion is empty",
        "aware.sug_list_header": "[aware] suggestion ({n}):",
        "aware.sug_help": (
            "Approve: la aware suggestion approve <id>|all\n"
            "Reject: la aware suggestion reject <id>|all"
        ),
        "aware.sug_not_found": "[aware] Not found: {target}",
        "aware.sug_deny_cmd": "[aware] Refusing non-allowlisted command: {cmd}",
        "aware.sug_acked": "[aware] Acknowledged {kind} · {title}",
        "aware.sug_exec": "[aware] Running: {cmd}",
        "aware.sug_exit_code": "[aware] Command exit code {code}",
        "aware.sug_approved": "[aware] Approved {ok}/{total}",
        "aware.sug_rejected": "[aware] Rejected {n}",
        "aware.events_none": "[aware] No events",
        "aware.events_summary": "[aware] Last {hours}h event summary (--raw for detail)",
        "aware.events_total": "[aware] {n} total",
        "aware.repl_help_intro": (
            "This is awareness chat: dig into local Aware activity; "
            "for casual chat open la chat separately."
        ),
        "aware.repl_help_cmds": "Commands:",
        "aware.repl_help_overview": "  /overview, /o   Redisplay smart overview",
        "aware.repl_help_detail": "  /detail         Show per-source detail",
        "aware.repl_help_context": "  /context, /c    Show injected awareness context",
        "aware.repl_help_status": "  /status         Grants / suggestion / session",
        "aware.repl_help_help": "  /help, /h       Show this help",
        "aware.repl_help_provider": "  /provider, /p   Switch model path",
        "aware.repl_help_quit": "  /q, /quit, /exit End awareness chat",
        "aware.repl_help_example": (
            "Just type a question, e.g.: Which files did I change this afternoon?"
        ),
        "aware.repl_entered": "[aware] Entered awareness chat (session={session})",
        "aware.repl_hint": (
            "[aware] Ask about local activity; /help for commands, /exit to leave."
        ),
        "aware.repl_cancel_once": (
            "\n[aware] Cancelled; Ctrl+C again to exit, or keep asking"
        ),
        "aware.repl_ended": "[aware] Awareness chat ended (run la aware again anytime)",
        "aware.repl_status_session": "[aware] session: {session}",
        "aware.repl_status_last_tick": "[aware] Last tick · {when}",
        "aware.repl_status_counts": (
            "[aware] Today's events {events} · suggestion {sug}"
        ),
        "aware.repl_answering": "Answering from awareness context…",
        "aware.repl_request_cancelled": "\n[aware] Request cancelled",
        "aware.repl_error": "[error] {exc}",
        "aware.repl_empty_response": "[error] Model returned empty content; retry.",
        "aware.repl_ollama_failover": (
            "[aware] Local Ollama was slow; switched to {provider}"
        ),
        "aware.tick_skip_busy": "another tick is already running",
        "aware.tick_skip_no_sensors": (
            "No granted implemented sensors; run la aware grant fs git terminal browser apps"
        ),
        "aware.sched_launchd_missing": "LaunchAgent not installed",
        "aware.sched_schtasks_missing": "Scheduled task not registered",
        "aware.sched_cron_on": "crontab includes aware tick",
        "aware.sched_cron_off": "crontab not configured",
        "aware.sched_no_crontab": "No crontab on this machine",
        "aware.sched_launchctl_manual": "load manually",
        "aware.sched_launchctl_suffix": " (launchctl: {msg})",
        "aware.sched_schtasks_fail": "schtasks create failed",
        "aware.sched_schtasks_hint": "; run manually: la aware tick",
        "aware.sched_cron_write_fail": "crontab write failed",
        "aware.sched_cron_written": "Wrote user crontab",
        "aware.sched_launchd_unloaded": "Unloaded LaunchAgent",
        "aware.sched_schtasks_deleted": "Deleted scheduled task",
        "aware.sched_cron_removed": "Removed from crontab",
        "aware.sensor_apps_front": "Frontmost app name / window title (System Events)",
        "aware.sensor_apps_media": "Now Playing track (Music / Spotify, if playing)",
        "aware.sensor_apps_idle": (
            "Estimate input-active time from system idle (bucketed by frontmost app)"
        ),
        "aware.sensor_apps_note": (
            "Note: keystrokes are not recorded; macOS may need Accessibility / Automation."
        ),
        "aware.sensor_apps_macos_only": "apps sensor currently supports macOS only",
        "aware.sensor_apps_osascript_fail": "osascript failed: {exc}",
        "aware.sensor_apps_unknown_err": "unknown error",
        "aware.sensor_apps_no_front": "Could not read frontmost app",
        "aware.sensor_apps_parse_fail": "Failed to parse frontmost app",
        "aware.sensor_apps_format_bad": "Unexpected frontmost app format",
        "aware.sensor_browser_none": "(No browser History database found)",
        "aware.sensor_browser_note": (
            "Note: read-only copy then query; no cookies/passwords. "
            "macOS Safari may need Full Disk Access."
        ),
        "aware.sensor_git_workspace": "Workspace (if a git repo): {path}",
        "aware.sensor_terminal_none": "(No shell history file found)",
        "aware.tabs_unsupported": (
            "Reading open tabs is not supported on this platform (macOS only); "
            "use la aware --since for recent visits"
        ),
        "aware.tabs_osascript_fail": "osascript failed: {exc}",
        "aware.tabs_unknown_err": "unknown error",
        "aware.tabs_permission_hint": (
            "Allow Terminal/LA to control the browser in "
            "System Settings → Privacy & Security → Automation; "
            "Chrome may need View → Developer → Allow JavaScript from Apple Events."
        ),
        "aware.tabs_error_with_hint": "{err}. {hint}",
        "aware.tabs_no_browser": (
            "No running browser window detected (or missing Automation permission)"
        ),
        "aware.tabs_parse_fail": "Failed to parse browser tabs",
        # --- news ---
        "news.need_action": (
            "[news] Specify a subcommand: sync | brief | skim | read | mark | schedule | interests | status"
        ),
        "news.unknown_action": "[news] Unknown subcommand: {action}",
        "news.sync_fail": "[news] sync failed: {error}",
        "news.sync_done": (
            "[news] sync done: fetched {fetched} "
            "(inserted {inserted}, updated {updated})"
        ),
        "news.source": "[news] Source: {url}",
        "news.view_brief": "[news] View: la news brief",
        "news.not_found": "[news] Not found: {target}",
        "news.read_fail": "[news] read failed: {error}",
        "news.msg_prefix": "[news] {msg}",
        "news.sched_enabled": "enabled",
        "news.sched_disabled": "disabled",
        "news.sched_status": "[news] Scheduled sync: {state} ({backend})",
        "news.sched_time": "[news] Time: daily {hour:02d}:{minute:02d}",
        "news.sched_detail": "[news] Detail: {detail}",
        "news.auto_sync": "[news] LA_NEWS_AUTO_SYNC={value}",
        "news.sched_error": "[news] {exc}",
        "news.sched_on_ok": (
            "[news] Scheduled sync enabled: daily {hour:02d}:{minute:02d} ({backend})"
        ),
        "news.sched_off_ok": "[news] Scheduled sync disabled ({backend})",
        "news.sched_unknown": "[news] Unknown schedule action: {sub} (on|off|status)",
        "news.interests_updated": "[news] Updated interests: {interests}",
        "news.interests_list": "[news] interests: {interests}",
        "news.mute_keywords": "[news] mute_keywords: {keywords}",
        "news.empty_parens": "(empty)",
        "news.interests_line": "[news] interests: {value}",
        "news.boost_line": "[news] boost: {value}",
        "news.mute_line": "[news] mute: {value}",
        "news.brief_size": "[news] brief_size: {n}",
        "news.status_rss": "[news] RSS: {url}",
        "news.status_dir": "[news] Data dir: {path}",
        "news.status_last_sync": "[news] Last sync: {when}",
        "news.status_never": "never",
        "news.status_last_count": "[news] Last count: {n}",
        "news.status_last_error": "[news] Last error: {error}",
        "news.status_schedule": "[news] Schedule: {state} {hour:02d}:{minute:02d} ({backend})",
        "news.status_sched_on": "on",
        "news.status_sched_off": "off",
        "news.status_interests": "[news] Interests: {interests}",
        "news.sources_default": "[news] Default source (BestBlogs RSS):",
        "news.sources_filter_hint": (
            "[news] Filter examples: category=ai&minScore=85&featured=y&timeFilter=1d"
        ),
        "news.sources_override": (
            "[news] Override: env LA_NEWS_RSS_URL or la news sync --url …"
        ),
        "news.prefix_current": "[Current] ",
        "news.prefix_skim": "[Skim] ",
        "news.no_summary": "(no summary yet)",
        "news.section_detail": "Detailed summary",
        "news.section_viewpoints": "Key points",
        "news.section_quotes": "Quotes",
        "news.meta_selected": "Picked  {reasons}",
        "news.meta_candidate": "candidate",
        "news.meta_ai_score": "AI score {score}",
        "news.meta_mins": "{n} min",
        "news.meta_published": "Published  {bits}",
        "news.meta_id": "ID  {id}",
        "news.meta_url": "Source  {url}",
        "news.brief_title": "# Daily news brief · {day}",
        "news.brief_count": (
            "{n} items · `la news read <id>` to deep-read · click title or URL to open"
        ),
        "news.brief_empty": "_No items yet. Run `la news sync` first._",
        "news.brief_one_liner": "- One-liner: {summary}",
        "news.brief_why": "- Why picked: {reason}",
        "news.brief_published": "- Published: {day}",
        "news.brief_url": "- Source: {url}",
        "news.brief_tip": (
            "Tip: `la news skim <id>` to skim · `la news mark <id> bookmark|skip`"
        ),
        "news.browser_today": "today",
        "news.browser_header": "Brief · {day} · {pos}",
        "news.browser_empty": "(no items)",
        "news.browser_help": (
            "Keys: ↑↓/jk switch  PgUp/PgDn/Space scroll  o/Enter open browser\n"
            "      s skim  r deep-read+chat  b bookmark  x skip  c copy link  ? help  q/Esc quit"
        ),
        "news.browser_opened": "Opened in browser",
        "news.browser_open_fail": "Failed to open browser; press c to copy link",
        "news.browser_skim_shown": "Showing skim card · press ↑↓ to return to summary",
        "news.browser_copied": "Copied source URL to clipboard",
        "news.browser_copy_fail": "Copy failed: {url}",
        "news.browser_no_items": "[news] No items yet. Run `la news sync` first.",
        "news.browser_enter": (
            "[news] Interactive brief (↑↓ switch · PgDn/Space scroll · o open · r deep-read · q quit)"
        ),
        "news.browser_list_empty": "[news] List is empty.",
        "news.browser_quit": "[news] Left brief browser",
        "news.browser_reading": "[news] Deep-read: {title}",
        "news.browser_read_fail": "Deep-read failed: {error}",
        "news.browser_back": "[news] Back to brief browser",
        "news.browser_chat_done": "Chat ended · continue with ↑↓",
        "news.browser_fetching": "Fetching and summarizing article…",
        # --- memory ---
        "memory.pending_empty": "[memory pending] Queue is empty",
        "memory.pending_count": "[memory pending] {shown}/{total} awaiting confirmation:",
        "memory.pending_more": "  … {n} more; omit --limit to see all",
        "memory.pending_approve_hint": "  Approve: LA memory approve <id>|--all",
        "memory.pending_reject_hint": "  Reject: LA memory reject <id>|--all",
        "memory.approve_need_id": "[memory approve] Specify id or --all",
        "memory.approve_done": (
            "[memory approve] Wrote {n} to Warm; {pending} still pending"
        ),
        "memory.reject_need_id": "[memory reject] Specify id or --all",
        "memory.reject_done": (
            "[memory reject] Discarded {n}; {pending} still pending"
        ),
        "memory.search_forget_hint": "→ LA memory forget <id>  delete a memory",
        "memory.status_title": "[memory status] Warm memory engine diagnostics",
        "memory.status_backend": "  Active backend: {backend} ({cls})",
        "memory.status_preference": "  Preference:     {preference} (LA_MEMORY_BACKEND)",
        "memory.status_python": "  Python:         {version}",
        "memory.status_mem0": "  Mem0:           {state}",
        "memory.installed": "installed",
        "memory.not_installed": "not installed",
        "memory.on": "on",
        "memory.off": "off",
        "memory.status_infer": "  Infer:          {state} (LA_MEM0_INFER)",
        "memory.status_llm": "  LLM:            {provider}/{model}",
        "memory.status_embedder": (
            "  Embedder:       {provider}/{model} (dims={dims})"
        ),
        "memory.status_retain_fallback": (
            "  Retain fallback:{state} (LA_MEM0_RETAIN_JSON_FALLBACK)"
        ),
        "memory.status_mem0_dir": "  Mem0 data:      {path}",
        "memory.status_count": "  Memory count:   {n}",
        "memory.status_unindexed": (
            "  Unindexed:      {n} (in JSON but not Mem0/Qdrant; try LA memory reindex)"
        ),
        "memory.status_sources": (
            "  Sources:        chat={chat}  chatgpt={chatgpt}  file={file}  other={other}"
        ),
        "memory.status_chat_sessions": (
            "  LA chat archive:{sessions} sessions (ingested index {ingested})"
        ),
        "memory.status_chatgpt": "  ChatGPT import: {n} processed",
        "memory.status_cold": (
            "  Cold chat chunks: chat={chat}  chatgpt={chatgpt}  (searchable via LA rag search)"
        ),
        "memory.status_hot_profile": "  Hot profile:    {state} ({path})",
        "memory.configured": "configured",
        "memory.not_configured": "not configured",
        "memory.status_graph": (
            "  Graph:          {state} (LA_MEMORY_GRAPH; LA memory graph stats)"
        ),
        "memory.status_profile_pin": "  Profile pin:    {mode} (LA_PROFILE_PIN_LLM)",
        "memory.pin_llm": "LLM",
        "memory.pin_regex": "regex",
        "memory.status_bank": "  Bank ID:        {bank_id}",
        "memory.status_store": "  Local index:    {path}",
        "memory.status_error": "  Error:          {error}",
        "memory.status_json_fallback_hint": (
            "\nTip: Mem0 init failure falls back to JSON. "
            "Check Ollama embedding model or LA_MEM0_EMBEDDER_*."
        ),
        "memory.status_unindexed_hint": (
            "Tip: Some memories are not vector-indexed; semantic recall may be incomplete."
        ),
        "memory.status_next": "\nNext:",
        "memory.status_next_query": "  LA memory query              browse recent memories",
        "memory.status_next_search": "  LA memory search <q>         semantic search",
        "memory.status_next_ingest": "  LA ingest chat|chatgpt|text  persist memories (write path)",
        "memory.type_preference": "preference",
        "memory.type_fact": "fact",
        "memory.type_plan": "plan",
        "memory.type_experience": "experience",
        "memory.type_observation": "observation",
        "memory.type_world": "world knowledge",
        "memory.unknown_time": "unknown time",
        "memory.untitled": "untitled memory",
        "memory.unknown_source": "unknown source",
        "memory.relevance": "relevance {score:.2f}",
        "memory.source_label": "source: {source}",
        "memory.time_anchor": "time anchor: {anchor}",
        "memory.semantic_temporal": "semantic {semantic:.2f} · temporal {temporal:.2f}",
        "memory.char_count": "raw length: {n} chars",
        "memory.found_n": "Found {n} related memories",
        "memory.found_query": "(query: {query})",
        "workspace.purged": "[workspace] Purged {removed} terminal task(s)",
        "workspace.no_tasks": "[workspace] No task records ({root})",
        "workspace.all_tasks": "[workspace] All tasks ({root}) · {n} item(s)",
        "workspace.rejected": "[workspace] Not created: {exc}",
        "workspace.added": "[workspace] Added [{id}] {title}",
        "workspace.why": "  Why: {rationale}",
        "workspace.done_hint": "  → la workspace done {id}",
        "workspace.not_found": "[workspace] Task not found",
        "workspace.done": "[workspace] Done [{id}] {title}",
        "workspace.dismissed": "[workspace] Dismissed [{id}] {title}",
        "workspace.snoozed": "[workspace] Snoozed [{id}] {title} → {until}",
        "workspace.reject_title": "title must be at least {n} characters",
        "workspace.reject_rationale": (
            "rationale (--why) must be at least {n} characters — why it deserves attention"
        ),
        "workspace.reject_source": "invalid source: {source}",
        "workspace.reject_dup": "duplicate open task [{id}]: {title}",
        "workspace.reject_recent": (
            "same task proposed within 7 days [{id}]: {title}"
        ),
        "workspace.reject_daily": "agent daily enqueue limit reached ({limit})",
        "workspace.line_expires": "  ·due {exp}",
        "workspace.line_why": "    Why: {rationale}",
        "workspace.line_hint": "    Done when: {hint}",
        "workspace.line_evidence": "    Evidence: {evidence}",
        "workspace.line_actions": (
            "    → la workspace done {id}  |  dismiss {id}  |  snooze {id}"
        ),
        "workspace.open_empty": (
            "Managed workspace tasks: none ({root})\n"
            "Tip: la workspace add \"…\" --why \"…\""
        ),
        "workspace.open_header": (
            "Managed workspace tasks ({count} open, showing {shown}):"
        ),
        "workspace.summary_empty": (
            "Managed tasks: none\nTip: la workspace add \"title\" --why \"reason\""
        ),
        "workspace.summary_header": (
            "Managed tasks ({count} open, showing {shown}):"
        ),
        "workspace.summary_more": (
            "  … {count} total; la workspace tasks / done <id>"
        ),
        "workspace.summary_actions": (
            "  Done: la workspace done <id>  |  snooze <id>  |  dismiss <id>"
        ),
        "workspace.git_error": "Git: {error}",
        "workspace.git_not_repo": "Git: not a git repository",
        "workspace.git_branch": "Git branch: {branch}",
        "workspace.git_clean": "Working tree: clean (no uncommitted changes)",
        "workspace.git_staged": "staged {n}",
        "workspace.git_unstaged": "unstaged {n}",
        "workspace.git_untracked": "untracked {n}",
        "workspace.git_dirty": "Working tree: {parts}",
        "workspace.git_recent": "Recent commits:",
        "workspace.diag_header": "[workspace] Diagnostic scan (not enqueued) ({root})",
        "workspace.diag_note": (
            "Note: code TODO/checkbox is informational; "
            "use la workspace tasks / add for real tasks"
        ),
        "workspace.diag_empty": "  No readable TODO/FIXME or unchecked checkbox found",
        "workspace.diag_hits": "[workspace] Diagnostic hits: {n} (not enqueued)",
        "workspace.root": "Workspace: {root}",
        "workspace.recent_files": "Files modified in the last {days} day(s):",
        "workspace.no_recent": "  (no recent changes, or directory inaccessible)",
        "workspace.files_more": "  … {n} file(s) total",
        "workspace.diag_summary_hits": (
            "Diagnostic scan hits {n} (not enqueued, showing first 5):"
        ),
        "workspace.diag_summary_empty": "Diagnostic scan: no hits (not enqueued)",
        "summarize.no_sessions": "[summarize] No document-chat sessions yet",
        "summarize.resume_hint": (
            "[summarize] Resume: la summarize <path> --resume  or  la summarize --id <id>"
        ),
        "summarize.session_not_found": "[summarize] error: session not found {id}",
        "summarize.session_file_missing": (
            "[summarize] error: session file missing: {path}"
        ),
        "summarize.need_path": (
            "[summarize] error: provide a file path, or use --list / --id"
        ),
        "summarize.multi_no_chat": (
            "[summarize] error: multi-file only supports brief mode; add --no-chat"
        ),
        "summarize.no_existing": (
            "[summarize] No existing session; starting a new document chat"
        ),
        "summarize.file": "[summarize] File: {path}",
        "summarize.interrupted": "\n[summarize] Interrupted",
        "summarize.error": "[summarize] error: {exc}",
        "summarize.chars": "{n} chars",
        "summarize.pages": "{n} pages",
        "summarize.ocr": "OCR",
        "summarize.ocr_pages": "{n} OCR pages",
        "summarize.ocr_conf": "avg_conf={conf}",
        "summarize.llm": "LLM",
        "summarize.heuristic": "heuristic",
        "ocr.usage": "[ocr] Usage: la ocr <path> [--out FILE] [--keep] [--json]",
        "ocr.error": "[ocr] error: {exc}",
        "ocr.interrupted": "\n[ocr] Interrupted",
        "ocr.wrote": "[ocr] Wrote: {path}",
        "ocr.meta_prefix": "[ocr] {meta}",
        "ocr.meta_file": "{filename}",
        "ocr.meta_conf": "avg_conf={conf}",
        "ocr.meta_lines": "{n} lines",
        "ocr.meta_pages": "{n} pages",
        "ocr.warning": "[ocr] Note: {warning}",
        "ocr.kept": "[ocr] Kept in knowledge base: {target}",
        "summarize.warning": "[summarize] Note: {warning}",
        "summarize.kept": "[summarize] Kept in knowledge base: {target}",
        "summarize.not_kept": "[summarize] Not kept (default). {hint}",
        "summarize.keep_hint": (
            "Not ingested by default (ephemeral brief). To keep in the knowledge base: "
            "type /keep in document chat, or pass --keep / "
            "`la summarize <path> --no-chat --keep`."
        ),
        "summarize.wrote": "[summarize] Wrote: {path}",
        "summarize.file_updated": "[summarize] File changed; regenerating brief…",
        "summarize.resume_session": "[summarize] Resuming session {id} · {filename}",
        "summarize.not_kept_resume": (
            "[summarize] Not kept (default). Type /keep in-session to save to knowledge base."
        ),
        "summarize.help_intro": (
            "This is document chat: scoped to the open file; "
            "for general chat use la chat."
        ),
        "summarize.help_commands": "Commands:",
        "summarize.help_summary": "  /summary, /s     Show the brief card again",
        "summarize.help_keep": (
            "  /keep            Keep current document in knowledge base (off by default)"
        ),
        "summarize.help_keep_again": (
            "                   (already kept; running again shows the path)"
        ),
        "summarize.help_status": "  /status          Show path / kept / session",
        "summarize.help_help": "  /help, /h        Show this help",
        "summarize.help_provider": "  /provider, /p    Switch model path",
        "summarize.help_quit": (
            "  /q, /quit, /exit End document chat "
            "(resume with la summarize <path> --resume)"
        ),
        "summarize.help_ask": "Type a question to dig into this document.",
        "summarize.entered": (
            "[summarize] Entered document chat: {filename}{pages}"
            " (session={session})"
        ),
        "summarize.pages_suffix": " · {n} pages",
        "summarize.enter_hint": (
            "[summarize] Ask follow-ups about this file; /help for commands, /exit to leave."
        ),
        "summarize.retrieval_mode": (
            "[summarize] Long-doc mode: retrieve passages by question (index={index})"
        ),
        "summarize.not_kept_repl": (
            "[summarize] Not kept. Type /keep in-session to save to knowledge base."
        ),
        "summarize.kept_path": "[summarize] Kept: {target}",
        "summarize.cancel_once": (
            "\n[summarize] Cancelled; Ctrl+C again to quit, or keep asking"
        ),
        "summarize.ended": (
            "[summarize] Document chat ended "
            "(resume with la summarize <path> --resume)"
        ),
        "summarize.status_kept": "Kept → {target}",
        "summarize.status_not_kept": "Not kept (default; /keep saves to knowledge base)",
        "summarize.status_file": "[summarize] File: {path}",
        "summarize.status_kept_label": "[summarize] Kept: {kept}",
        "summarize.status_session": "[summarize] session: {session}",
        "summarize.status_archive": "[summarize] Conversation archive: {session}",
        "summarize.status_chars": "[summarize] Characters: {n}",
        "summarize.status_pages": "[summarize] Pages: {n}",
        "summarize.keep_fail": "[summarize] Keep failed: {exc}",
        "summarize.answering": "Answering about the document…",
        "summarize.request_cancelled": "\n[summarize] Request cancelled",
        "summarize.ollama_failover": (
            "[summarize] Local Ollama was slow; auto-switched to {provider}"
        ),
        "summarize.read_fail": "Cannot read file: {path}",
        "polish.scene": "scene={label}",
        "polish.audience": "audience={audience}",
        "polish.attitude": "tone={attitude}",
        "polish.risks": "risks={risks}",
        "polish.style": "style={note}",
        "polish.low_conf": "low confidence · using default scene",
        "polish.tag_detect": "[Detected]",
        "polish.tag_primary": "[Primary]",
        "polish.tag_alt": "[Alt·{label}]",
        "polish.tag_changes": "[Changes]",
        "polish.default_changes": "Minor wording and tone tweaks",
        "polish.unspecified": "unspecified",
        "polish.status_model": "Calling model…",
        "polish.status_detect": "Detecting scene and tone…",
        "polish.status_rewrite": "Rewriting…",
        "polish.empty_draft": "Draft is empty",
        "polish.no_rewrite": (
            "Model returned no usable rewrite; retry later or switch /provider"
        ),
        "polish.no_primary": "Model did not return a primary rewrite",
        "polish.label_primary": "Primary",
        "polish.label_alt": "Alt·{label}",
        "polish.copied_primary_interactive": (
            "✓ Copied [Primary] to clipboard · press 2={soft} / "
            "3={firm} to swap · 1=recopy primary · Enter/n to finish"
        ),
        "polish.copied_primary": "✓ Copied [Primary] to clipboard",
        "polish.clipboard_unavailable": (
            "Clipboard unavailable; copy the [Primary] block manually"
        ),
        "polish.copy_prompt": "copy> ",
        "polish.copy_ended": "Copy session ended",
        "polish.invalid_choice": (
            "Invalid choice: {choice!r} (1=primary / 2={soft} / 3={firm} / n)"
        ),
        "polish.copied_label": "✓ Copied [{label}] to clipboard",
        "polish.copy_failed": "Failed to copy [{label}]; copy manually",
        "polish.usage": (
            "[polish] Usage: la polish [--scene email|moments|resume|biz] "
            "[--tone …] [--no-copy] [--file path] <draft>\n"
            "       echo \"draft\" | la polish\n"
            "In-session: /polish <draft>"
        ),
        "polish.unknown_scene": (
            "[polish] error: unknown scene {scene!r} (choices: {scenes})"
        ),
        "polish.status_working": "Detecting scene and rewriting…",
        "polish.interrupted": "\n[polish] Interrupted",
        "polish.error": "[polish] error: {exc}",
        "polish.file_missing": "File not found: {path}",
        "audit.summary_title": "[audit] Summary{range}",
        "audit.calls_line": "  Calls: {calls}  Tokens: {tokens}  Est. cost: ${cost:.4f}",
        "audit.provider_line": "    {name}: {calls} calls, {tokens} tokens, ${cost:.4f}",
        "audit.behavior_line": (
            "Behavior: shell={shell}  write={write}  web={web}  guardrails={guard}"
        ),
        "audit.blocked_denied": "  Blocked={blocked}  Denied={denied}",
        "audit.memory_health_line": (
            "Memory health: facts={facts} · kb={kb} · indexed={indexed}"
        ),
        "audit.workspace_header": "Workspace (summary):",
        "audit.export_hint": (
            "→ LA audit --report report.md  export Markdown; --report report.html for HTML"
        ),
        "audit.report_written": "[audit] Report written to {path}",
        "audit.md_title": "# LocalAgent Audit Report",
        "audit.md_generated": "Generated: {when}",
        "audit.md_range": "Range: {range}",
        "audit.md_range_since": "(since {since})",
        "audit.md_range_all": "(all records)",
        "audit.md_workspace": "Workspace: `{workspace}`",
        "audit.md_usage": "## Tokens & service spend",
        "audit.md_calls": "- Calls: {n}",
        "audit.md_tokens": "- Total tokens: {n}",
        "audit.md_cost": "- Est. cost (USD): ${cost:.4f}",
        "audit.md_by_provider": "### By provider",
        "audit.md_table_provider": "| Provider | Calls | Tokens | Est. cost (USD) |",
        "audit.md_by_command": "### By command",
        "audit.md_cmd_count": "- `{cmd}`: {n} calls",
        "audit.md_by_model": "### By model",
        "audit.md_table_model": "| Model | Calls | Tokens | Est. cost (USD) |",
        "audit.md_security": "## File safety",
        "audit.md_security_none": "No high-risk findings.",
        "audit.md_security_count": "{n} finding(s) (high: {high})",
        "audit.md_table_security": "| Level | Path | Detail | Fix |",
        "audit.md_behavior": "## Agent behavior & guardrails",
        "audit.md_shell": "- Local `run_shell`: {n}",
        "audit.md_write": "- File `write_file`: {n}",
        "audit.md_web": "- Web `web_search`: {n}",
        "audit.md_guard": "- Guardrail triggers: {n}",
        "audit.md_outcomes": "### Tool decision outcomes",
        "audit.md_blocked": "### Blocked this period",
        "audit.md_denied": "### User denials",
        "audit.md_no_behavior": "No behavior events recorded.",
        "audit.md_memory": "## Memory health",
        "audit.md_ws_snap": "## Workspace snapshot",
        "audit.md_footer": (
            "*Costs are estimates from default unit prices; override with LA_COST_* in .env.*"
        ),
        "audit.html_title": "LocalAgent Audit Report",
        "audit.sec_ok": "File safety: no high-risk findings",
        "audit.sec_header": "File safety: {n} finding(s) (high: {high})",
        "audit.sec_more": "  … {n} total",
        "audit.sec_world_readable": "File is readable by other users",
        "audit.sec_world_fix": "Consider chmod 600 or move out of the index directory",
        "audit.sec_aws_key": "Possible AWS Access Key",
        "audit.sec_openai_key": "Possible OpenAI/API sk- key",
        "audit.sec_private_key": "Private key material",
        "audit.sec_secret_fix": "Remove from kb/, rotate leaked keys, check git history",
        "audit.sec_symlink_bad": "Symlink target cannot be resolved",
        "audit.sec_symlink_fix": "Check whether the LA add-file source path is valid",
        "audit.sec_sensitive_name": "Sensitive filename indexed (.env, keys, etc.)",
        "audit.sec_sensitive_fix": (
            "After LA reset-memory, remove kb/ symlinks; do not index secret files"
        ),
        "audit.sec_env_indexed": "Workspace .env was indexed into kb/",
        "audit.sec_env_fix": "Delete kb/.env symlink and related reset-memory entries",
        "audit.sec_path_blocked": "Sensitive path blocked from index/read: {name}",
        "audit.health_facts": "Memory facts: {n}",
        "audit.health_kb": "kb/ files: {kb}, indexed: {indexed}",
        "audit.health_failed": "Failed background index tasks: {n}",
        "audit.health_orphan": "sync_index orphan entries: {n}",
        "audit.health_missing": "kb/ files not indexed: {n}",
        "audit.health_note_ingest": "Some kb/ files are not indexed; run LA rag ingest",
        "prompt.reply_lang": "Reply in clear, complete English.",

        "prompt.retry_incomplete": (
            "Your previous reply was incomplete or truncated. "
            "Using the tool results you already have, give a clear complete final answer "
            "in English. Do not call tools again."
        ),
        "prompt.aware_summary": (
            "From the local awareness fact cards below, write 3–6 lines of activity "
            "in English (no title). Time range: {window}; cover that full window, "
            "organized by date/period.\n"
        ),
        "prompt.tone_evening_chat": (
            "### Late-night closing (local time is late)\n"
            "After the main answer is complete, if this turn is the final natural-language "
            "reply to the user, you may add one short closing line after a blank line. "
            "Prefer: \"It's late — get some rest.\"\n"
            "Rules:\n"
            "- Finish the task first; never insert the closing inside prose, code, or lists\n"
            "- Skip when the user wants only a product/JSON/patch, during tool confirmation, "
            "or while they are mid debug follow-ups\n"
            "- If this session already had a rest reminder: do not add another\n"
            "- No emotion diagnosis, no long health lectures, no companion persona\n"
        ),
        "prompt.tone_evening_aware": (
            "Late-night closing: after the activity lines, you may add one last line "
            "\"It's late — wrapping up for rest is fine too.\" "
            "Do not insert it mid-facts; no emotion diagnosis or pep talk.\n"
        ),
        "prompt.memory_summarize": (
            "Summarize the following in concise English (or the source language), "
            "keeping key facts, names, times, and conclusions."
        ),
        "prompt.reflect_answer": (
            "Question: {query}\n\nEvidence:\n{evidence}\n\nAnswer concisely in English:"
        ),
        "prompt.polish_system": (
            "You are a senior English writing editor. Rewrite the draft for the occasion "
            "and tone; keep meaning and facts.\n"
        ),
        "prompt.deep_report": (
            "Based on the multi-round search results below, write a structured deep research "
            "report in English about 「{topic}」:\n\n"
        ),
    },
}


def t(key: str, **kwargs: object) -> str:
    """Translate a UI/prompt key for the active language."""
    lang = resolve_lang()
    catalog = _MESSAGES.get(lang) or _MESSAGES["en"]
    template = catalog.get(key) or _MESSAGES["en"].get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template
    return template


def H(zh: str, en: str) -> str:
    """Inline bilingual helper for argparse help / one-off UI strings."""
    return en if resolve_lang() == "en" else zh
