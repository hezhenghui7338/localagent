"""CLI handlers for `la news …`."""

from __future__ import annotations

import argparse
from datetime import date

from localagent import config
from localagent.i18n import t
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
        print(t("news.need_action"))
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
        print(t("news.unknown_action", action=action))
        return 1
    return fn(args)


def _open_brief(args: argparse.Namespace, *, no_ui: bool | None = None) -> int:
    """Build today's brief and enter the interactive browser when on a TTY."""
    import sys

    from localagent.news.browser import run_news_browser, should_enter_news_browser

    day = getattr(args, "date", None) or date.today().isoformat()
    limit = getattr(args, "limit", None)
    plain = bool(getattr(args, "plain", False))
    if no_ui is None:
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


def _cmd_sync(args: argparse.Namespace) -> int:
    url = getattr(args, "url", None) or None
    result = sync_news(rss_url=url)
    if not result.ok:
        print(t("news.sync_fail", error=result.error))
        return 1
    print(
        t(
            "news.sync_done",
            fetched=result.fetched,
            inserted=result.inserted,
            updated=result.updated,
        )
    )
    print(t("news.source", url=result.source_url))

    # TTY（含会话内 /news sync）：同步后直接进简报，避免操作链路断开。
    # 定时任务 / 管道等非 TTY 仍只打印结果；--no-ui 可显式跳过交互。
    from localagent.news.browser import should_enter_news_browser

    no_ui = bool(getattr(args, "no_ui", False))
    if should_enter_news_browser(no_ui=no_ui):
        return _open_brief(args, no_ui=False)

    print(t("news.view_brief"))
    return 0


def _cmd_brief(args: argparse.Namespace) -> int:
    return _open_brief(args)


def _cmd_skim(args: argparse.Namespace) -> int:
    target = getattr(args, "target", "") or ""
    store = NewsStore()
    art = store.resolve(target)
    if not art:
        print(t("news.not_found", target=target))
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
        print(t("news.read_fail", error=result.error))
        return 1
    print(result.markdown, end="" if result.markdown.endswith("\n") else "\n")
    return 0


def _cmd_mark(args: argparse.Namespace) -> int:
    target = getattr(args, "target", "") or ""
    action = getattr(args, "mark_action", "") or ""
    _art, msg = mark_article(target, action)
    print(t("news.msg_prefix", msg=msg))
    return 0 if _art else 1


def _cmd_schedule(args: argparse.Namespace) -> int:
    sub = getattr(args, "schedule_action", "status") or "status"
    if sub == "status":
        st = schedule_status()
        state = t("news.sched_enabled") if st.enabled else t("news.sched_disabled")
        print(t("news.sched_status", state=state, backend=st.backend))
        print(t("news.sched_time", hour=st.hour, minute=st.minute))
        print(t("news.sched_detail", detail=st.detail))
        print(t("news.auto_sync", value=int(config.NEWS_AUTO_SYNC)))
        return 0
    if sub in ("on", "enable"):
        try:
            st = enable_schedule(
                hour=getattr(args, "hour", None),
                minute=getattr(args, "minute", None),
            )
        except RuntimeError as exc:
            print(t("news.sched_error", exc=exc))
            return 1
        print(t("news.sched_on_ok", hour=st.hour, minute=st.minute, backend=st.backend))
        print(t("news.sched_detail", detail=st.detail))
        return 0
    if sub in ("off", "disable"):
        st = disable_schedule()
        print(t("news.sched_off_ok", backend=st.backend))
        print(t("news.sched_detail", detail=st.detail))
        return 0
    print(t("news.sched_unknown", sub=sub))
    return 1


def _cmd_interests(args: argparse.Namespace) -> int:
    profile = load_news_profile()
    set_interests = getattr(args, "set_interests", None)
    add = getattr(args, "add", None)
    mute = getattr(args, "mute", None)
    if set_interests:
        profile.interests = [s.strip() for s in set_interests.split(",") if s.strip()]
        save_news_profile(profile)
        print(t("news.interests_updated", interests=profile.interests))
        return 0
    if add:
        if add not in profile.interests:
            profile.interests.append(add)
            save_news_profile(profile)
        print(t("news.interests_list", interests=profile.interests))
        return 0
    if mute:
        if mute not in profile.mute_keywords:
            profile.mute_keywords.append(mute)
            save_news_profile(profile)
        print(t("news.mute_keywords", keywords=profile.mute_keywords))
        return 0
    empty = t("news.empty_parens")
    print(t("news.interests_line", value=", ".join(profile.interests) or empty))
    print(t("news.boost_line", value=", ".join(profile.boost_keywords) or empty))
    print(t("news.mute_line", value=", ".join(profile.mute_keywords) or empty))
    print(t("news.brief_size", n=profile.daily_brief_size))
    return 0


def _cmd_status(_args: argparse.Namespace) -> int:
    state = load_sync_state()
    profile = load_news_profile()
    st = schedule_status()
    print(t("news.status_rss", url=config.NEWS_RSS_URL))
    print(t("news.status_dir", path=config.NEWS_DIR))
    print(
        t(
            "news.status_last_sync",
            when=state.get("last_sync_at") or t("news.status_never"),
        )
    )
    print(t("news.status_last_count", n=state.get("last_sync_count", 0)))
    if state.get("last_error"):
        print(t("news.status_last_error", error=state.get("last_error")))
    print(
        t(
            "news.status_schedule",
            state=t("news.status_sched_on") if st.enabled else t("news.status_sched_off"),
            hour=st.hour,
            minute=st.minute,
            backend=st.backend,
        )
    )
    print(t("news.status_interests", interests=", ".join(profile.interests)))
    return 0


def _cmd_sources(_args: argparse.Namespace) -> int:
    print(t("news.sources_default"))
    print(f"  {config.NEWS_RSS_URL}")
    print(t("news.sources_filter_hint"))
    print(t("news.sources_override"))
    return 0
