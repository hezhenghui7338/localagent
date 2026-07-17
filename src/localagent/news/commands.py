"""CLI handlers for `la news …`."""

from __future__ import annotations

import argparse
from datetime import date

from localagent import config
from localagent.news.brief import build_brief, format_skim_card
from localagent.news.mark import mark_article
from localagent.news.profile import load_news_profile, save_news_profile
from localagent.news.read import read_article
from localagent.news.schedule import disable_schedule, enable_schedule, schedule_status
from localagent.news.store import NewsStore, load_sync_state
from localagent.news.sync import sync_news


def cmd_news(args: argparse.Namespace) -> int:
    action = getattr(args, "news_action", None) or getattr(args, "action", None)
    if not action:
        print("[news] 请指定子命令：sync | brief | skim | read | mark | schedule | interests | status")
        return 1
    handlers = {
        "sync": _cmd_sync,
        "brief": _cmd_brief,
        "skim": _cmd_skim,
        "read": _cmd_read,
        "mark": _cmd_mark,
        "schedule": _cmd_schedule,
        "interests": _cmd_interests,
        "status": _cmd_status,
        "sources": _cmd_sources,
    }
    fn = handlers.get(action)
    if not fn:
        print(f"[news] 未知子命令: {action}")
        return 1
    return fn(args)


def _cmd_sync(args: argparse.Namespace) -> int:
    url = getattr(args, "url", None) or None
    result = sync_news(rss_url=url)
    if not result.ok:
        print(f"[news] sync 失败: {result.error}")
        return 1
    print(
        f"[news] sync 完成: 拉取 {result.fetched} 条"
        f"（新增 {result.inserted}，更新 {result.updated}）"
    )
    print(f"[news] 源: {result.source_url}")
    print("[news] 查看: la news brief")
    return 0


def _cmd_brief(args: argparse.Namespace) -> int:
    import sys

    from localagent.news.browser import run_news_browser, should_enter_news_browser

    day = getattr(args, "date", None) or date.today().isoformat()
    limit = getattr(args, "limit", None)
    plain = bool(getattr(args, "plain", False))
    no_ui = bool(getattr(args, "no_ui", False))
    text, ranked = build_brief(
        since_date=day,
        limit=limit,
        plain_links=plain or no_ui or not sys.stdout.isatty(),
    )
    if not ranked:
        print(text, end="" if text.endswith("\n") else "\n")
        return 0

    if should_enter_news_browser(no_ui=no_ui):
        provider = getattr(args, "provider", None) or "auto"
        return run_news_browser(ranked, day=day, provider=provider)

    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def _cmd_skim(args: argparse.Namespace) -> int:
    target = getattr(args, "target", "") or ""
    store = NewsStore()
    art = store.resolve(target)
    if not art:
        print(f"[news] 未找到: {target}")
        return 1
    store.set_status(art.id, "skimmed")
    art = store.get(art.id) or art
    print(format_skim_card(art, plain_links=bool(getattr(args, "plain", False))))
    return 0


def _cmd_read(args: argparse.Namespace) -> int:
    target = getattr(args, "target", "") or ""
    result = read_article(
        target,
        keep=bool(getattr(args, "keep", False)),
        use_llm=not bool(getattr(args, "heuristic", False)),
        plain_links=bool(getattr(args, "plain", False)),
    )
    if result.error:
        print(f"[news] read 失败: {result.error}")
        return 1
    print(result.markdown, end="" if result.markdown.endswith("\n") else "\n")
    return 0


def _cmd_mark(args: argparse.Namespace) -> int:
    target = getattr(args, "target", "") or ""
    action = getattr(args, "mark_action", "") or ""
    _art, msg = mark_article(target, action)
    print(f"[news] {msg}")
    return 0 if _art else 1


def _cmd_schedule(args: argparse.Namespace) -> int:
    sub = getattr(args, "schedule_action", "status") or "status"
    if sub == "status":
        st = schedule_status()
        state = "已启用" if st.enabled else "未启用"
        print(f"[news] 定时 sync: {state}（{st.backend}）")
        print(f"[news] 时间: 每天 {st.hour:02d}:{st.minute:02d}")
        print(f"[news] 详情: {st.detail}")
        print(f"[news] LA_NEWS_AUTO_SYNC={int(config.NEWS_AUTO_SYNC)}")
        return 0
    if sub in ("on", "enable"):
        try:
            st = enable_schedule(
                hour=getattr(args, "hour", None),
                minute=getattr(args, "minute", None),
            )
        except RuntimeError as exc:
            print(f"[news] {exc}")
            return 1
        print(f"[news] 已开启定时 sync：每天 {st.hour:02d}:{st.minute:02d}（{st.backend}）")
        print(f"[news] {st.detail}")
        return 0
    if sub in ("off", "disable"):
        st = disable_schedule()
        print(f"[news] 已关闭定时 sync（{st.backend}）")
        print(f"[news] {st.detail}")
        return 0
    print(f"[news] 未知 schedule 动作: {sub}（on|off|status）")
    return 1


def _cmd_interests(args: argparse.Namespace) -> int:
    profile = load_news_profile()
    set_interests = getattr(args, "set_interests", None)
    add = getattr(args, "add", None)
    mute = getattr(args, "mute", None)
    if set_interests:
        profile.interests = [s.strip() for s in set_interests.split(",") if s.strip()]
        save_news_profile(profile)
        print(f"[news] 已更新 interests: {profile.interests}")
        return 0
    if add:
        if add not in profile.interests:
            profile.interests.append(add)
            save_news_profile(profile)
        print(f"[news] interests: {profile.interests}")
        return 0
    if mute:
        if mute not in profile.mute_keywords:
            profile.mute_keywords.append(mute)
            save_news_profile(profile)
        print(f"[news] mute_keywords: {profile.mute_keywords}")
        return 0
    print("[news] interests:", ", ".join(profile.interests) or "（空）")
    print("[news] boost:", ", ".join(profile.boost_keywords) or "（空）")
    print("[news] mute:", ", ".join(profile.mute_keywords) or "（空）")
    print(f"[news] brief_size: {profile.daily_brief_size}")
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    state = load_sync_state()
    profile = load_news_profile()
    st = schedule_status()
    print(f"[news] RSS: {config.NEWS_RSS_URL}")
    print(f"[news] 数据目录: {config.NEWS_DIR}")
    print(f"[news] 上次 sync: {state.get('last_sync_at') or '从未'}")
    print(f"[news] 上次条数: {state.get('last_sync_count', 0)}")
    if state.get("last_error"):
        print(f"[news] 上次错误: {state.get('last_error')}")
    print(
        f"[news] 定时: {'开' if st.enabled else '关'} "
        f"{st.hour:02d}:{st.minute:02d} ({st.backend})"
    )
    print(f"[news] 兴趣: {', '.join(profile.interests)}")
    return 0


def _cmd_sources(_args: argparse.Namespace) -> int:
    print("[news] 默认源 (BestBlogs RSS):")
    print(f"  {config.NEWS_RSS_URL}")
    print("[news] 可用过滤参数示例: category=ai&minScore=85&featured=y&timeFilter=1d")
    print("[news] 覆盖: 环境变量 LA_NEWS_RSS_URL 或 la news sync --url …")
    return 0
