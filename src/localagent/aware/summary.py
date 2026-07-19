"""Smart overview for `la aware`: fact card → LLM (or heuristic) + daily status."""

from __future__ import annotations

import re

from localagent.aware.profile import load_profile
from localagent.aware.timewin import label_since
from localagent.aware.types import AwareEvent, IMPLEMENTED_SOURCES
from localagent.i18n import t
from localagent.status.daily import format_daily_actions_lines

# apps first: true frontmost attention leads the fact card / current-state block.
_SOURCE_ORDER = ("apps", "browser", "git", "terminal", "fs")
_FACT_CHAR_LIMIT = 6000
_NOW_ACTIVITY_SINCE = "3h"
_NOW_EPISODE_HOURS = 3
_NOW_EPISODE_LIMIT = 5

_LEAK_LINE_RE = re.compile(
    r"(未授权|不要编造|事实卡|要求[:：]|每行一句|一笔带过|禁止把|摘要助手|"
    r"根据下面|用中文写|不要标题|"
    r"not granted|do not invent|fact card|one line|instructions)",
    re.I,
)

_CURRENT_PREFIXES = ("当前:", "Current:")
_PERIOD_TAGS = (
    "清晨",
    "上午",
    "下午",
    "傍晚",
    "晚上",
    "深夜",
    "白天",
    "early morning",
    "morning",
    "afternoon",
    "evening",
    "night",
    "late night",
    "daytime",
)


def _strip_current_prefix(text: str) -> str:
    s = text.strip()
    for prefix in _CURRENT_PREFIXES:
        if s.startswith(prefix):
            return s[len(prefix) :].strip()
    return s


def _format_source_lines(name: str, body: list[str]) -> list[str]:
    out: list[str] = []
    for ln in body:
        out.append(f"{name}:{ln}" if ln.startswith("  ") else f"{name}: {ln}")
    return out


def render_current_state_block(*, source: str | None = None) -> list[str]:
    """Live compact snapshots for the overview current-state section (no LLM)."""
    from localagent.aware import digest as dig

    profile = load_profile()
    sources = [source] if source else list(_SOURCE_ORDER)
    sources = [s for s in sources if s in IMPLEMENTED_SOURCES]

    lines: list[str] = []
    for name in sources:
        if not profile.is_granted(name):
            continue
        live = dig._render_now_compact(name)
        if not live:
            continue
        for ln in live:
            text = _strip_current_prefix(ln.strip())
            lines.append(f"  · {name} · {text}")
    if not lines:
        return [t("aware.no_snapshot")]
    return lines


def build_fact_card(
    *,
    mode: str,
    since: str | None = None,
    source: str | None = None,
    delta_events: list[AwareEvent] | None = None,
    episode_lines: list[str] | None = None,
) -> str:
    """Structured facts for LLM / heuristic summary (not the full detail dump)."""
    from localagent.aware import digest as dig

    profile = load_profile()
    sources = [source] if source else list(_SOURCE_ORDER)
    sources = [s for s in sources if s in IMPLEMENTED_SOURCES]

    input_since: str | None = None
    if mode == "now":
        window_label = label_since(_NOW_ACTIVITY_SINCE)
        lines = [t("aware.mode_now", window=window_label)]
        input_since = _NOW_ACTIVITY_SINCE
    elif mode == "delta":
        lines = [t("aware.mode_delta")]
    else:
        window_label = label_since(since or "1w")
        lines = [t("aware.mode_window", window=window_label)]
        input_since = since or "1w"

    for name in sources:
        if not profile.is_granted(name):
            lines.append(f"{name}: {t('aware.unauthorized')}")
            continue
        if mode == "delta":
            body = dig._render_events(
                name, delta_events or [], empty=t("aware.no_change")
            )
        elif mode == "window":
            body = dig._render_window_rollup(name, since or "1w")
        else:
            # now → live snapshot first, then rolled-up activity window
            live = dig._render_now_compact(name)
            hist = dig._render_window_rollup(name, _NOW_ACTIVITY_SINCE)
            body = [*(live or []), *hist]
        lines.extend(_format_source_lines(name, body))

    if episode_lines:
        lines.append("episodes:")
        for ln in episode_lines:
            text = ln.lstrip("- ").strip()
            if text:
                lines.append(f"episodes:  · {text}")

    if profile.is_granted("apps"):
        try:
            from localagent.aware.input_activity import format_input_activity_line

            activity = (
                format_input_activity_line(since=input_since)
                if input_since
                else format_input_activity_line()
            )
            if activity:
                lines.append(f"apps: {activity}")
        except Exception:
            pass

    return "\n".join(lines)


def _is_background_selected_line(text: str) -> bool:
    return (
        "后台选中" in text
        or "非正在看" in text
        or "bg-selected" in text
        or "not viewing" in text
    )


def _is_viewing_line(text: str) -> bool:
    if _is_background_selected_line(text):
        return False
    return "正在看" in text or "viewing" in text


def heuristic_summarize_facts(card: str) -> list[str]:
    """Compress fact-card lines into period-aware bullets (offline fallback)."""
    apps_now: list[str] = []
    browser_viewing: list[str] = []
    browser_bg: list[str] = []
    other_now: list[str] = []
    history: list[str] = []
    timed: list[str] = []

    for raw in card.splitlines():
        line = raw.strip()
        if not line or line.startswith("模式:") or line.startswith("Mode:"):
            continue
        if ":" not in line:
            continue
        src, rest = line.split(":", 1)
        rest = rest.strip()
        if not rest or rest.startswith("（近期") or rest.startswith("监视路径"):
            continue
        if rest.startswith("·") or rest.startswith("+") or rest.startswith("~") or rest.startswith("$"):
            text = f"{src} · {rest.lstrip('· ').strip()}"
        else:
            text = f"{src} · {rest}"
        # Prefer lines that already carry local clock / period metadata.
        if any(tag in rest for tag in _PERIOD_TAGS) or (
            "–" in rest and any(ch.isdigit() for ch in rest)
        ):
            if text not in timed:
                timed.append(text)
        is_current = any(p in rest for p in _CURRENT_PREFIXES) or rest.startswith(
            "当前"
        )
        if is_current:
            if src == "apps":
                apps_now.append(text)
            elif src == "browser" and _is_background_selected_line(rest):
                browser_bg.append(text)
            elif src == "browser" and _is_viewing_line(rest):
                browser_viewing.append(text)
            elif src == "browser":
                browser_bg.append(text)
            else:
                other_now.append(text)
        else:
            if text not in history:
                history.append(text)

    bullets: list[str] = []
    for ln in timed[:3]:
        bullets.append(_strip_current_prefix(ln.split(" · ", 1)[-1]))
    if apps_now and len(bullets) < 4:
        bullets.append(
            t(
                "aware.heuristic_primary",
                text=_strip_current_prefix(
                    apps_now[0].removeprefix("apps · ")
                ),
            )
        )
    elif browser_viewing and len(bullets) < 4:
        bullets.append(
            t(
                "aware.heuristic_primary",
                text=_strip_current_prefix(
                    browser_viewing[0].removeprefix("browser · ")
                ),
            )
        )
    if browser_viewing and apps_now and len(bullets) < 5:
        bullets.append(
            t(
                "aware.heuristic_secondary",
                text=_strip_current_prefix(
                    browser_viewing[0].removeprefix("browser · ")
                ),
            )
        )
    for ln in other_now[:2]:
        if len(bullets) >= 5:
            break
        bullets.append(
            t(
                "aware.heuristic_secondary",
                text=_strip_current_prefix(ln.split(" · ", 1)[-1]),
            )
        )
    if browser_bg:
        bullets.append(t("aware.heuristic_almost_none"))
    for ln in history:
        if len(bullets) >= 6:
            break
        # Skip raw visit dumps that repeat background noise.
        if (
            "后台选中" in ln
            or "非正在看" in ln
            or "bg-selected" in ln
            or "not viewing" in ln
            or "前台停留" in ln
            or "前台页" in ln
        ):
            continue
        if ln in timed:
            continue
        bullets.append(ln)
    if not bullets:
        return [t("aware.heuristic_empty")]
    return bullets[:8]


def _sanitize_summary_lines(text: str) -> list[str]:
    cleaned: list[str] = []
    for ln in text.splitlines():
        s = ln.strip().lstrip("#").strip()
        if s.startswith("```"):
            continue
        if s.startswith("- ") or s.startswith("* "):
            s = s[2:].strip()
        if not s:
            continue
        if _LEAK_LINE_RE.search(s):
            continue
        cleaned.append(s)
    return cleaned[:8]


def llm_summarize_facts(card: str, *, window_label: str = "") -> str | None:
    """Ask the model for a short activity summary; None on any failure."""
    try:
        from localagent.models.router import ChatMessage, get_model_router
    except Exception:
        return None
    from localagent.i18n import resolve_lang

    clipped = card[:_FACT_CHAR_LIMIT]
    window = window_label or ""
    from localagent.tone import evening_postscript_block

    evening = evening_postscript_block(surface="aware")
    evening_prefix = f"{evening}\n" if evening else ""
    if resolve_lang() == "en":
        prompt = (
            evening_prefix
            + t("prompt.aware_summary", window=window)
            + "Cover the entire time window on the fact card — organize by date/period; "
            "do not narrate only the last few hours when older buckets exist.\n"
            "Timestamps/time-of-day matter most: prefer daytime/evening/clock times "
            "(e.g. \"around 10pm watching video\", \"morning coding in Cursor\"), "
            "not only aggregate totals like \"over X hours recently\".\n"
            "Order by attention: primary / secondary / almost none.\n"
            "Long dwells in the fact card (e.g. WeChat, coding) must not be denied.\n"
            "Prefer \"current app\" and browser tabs marked \"watching\"; "
            "\"background selected\" is not browsing — do not call it focus or dwell; "
            "visit summaries are not dwell time; input activity ≠ foreground browsing; "
            "do not restate these instructions.\n\n"
            f"{clipped}"
        )
    else:
        prompt = (
            evening_prefix
            + t("prompt.aware_summary", window=window)
            + "必须覆盖事实卡上的整个时间窗，按日期/时段组织，禁止只写最近几小时。\n"
            "发生时刻/时段是最重要元数据：优先写白天/晚上/具体钟面"
            "（如「晚上 22 点左右看视频」「上午在 Cursor 写代码」），"
            "不要只写「最近累计超 X 小时」这类总时长聚合。\n"
            "按注意力主次写：主要 / 其次 / 几乎没有。\n"
            "事实卡中的长停留（如微信、编码）不得写成「几乎没有」。\n"
            "「当前应用」与标注「正在看」的浏览器优先；"
            "「后台选中」不是浏览，不要写成关注或停留；"
            "访问摘要不等于停留时长；输入活跃≠前台浏览；勿复述本段说明。\n\n"
            f"{clipped}"
        )
    try:
        reply = get_model_router().chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.2,
            usage_command="aware_digest",
        )
    except Exception:
        return None
    text = (reply or "").strip()
    if not text:
        return None
    cleaned = _sanitize_summary_lines(text)
    return "\n".join(cleaned) if cleaned else None


def summarize_activity(
    card: str, *, use_llm: bool = True, window_label: str = ""
) -> list[str]:
    if use_llm:
        text = llm_summarize_facts(card, window_label=window_label)
        if text:
            return [ln for ln in text.splitlines() if ln.strip()]
    return heuristic_summarize_facts(card)


def format_status_block(*, since: str | None = None) -> list[str]:
    """User-facing system status (daily actions + aware meta)."""
    profile = load_profile()
    lines = list(format_daily_actions_lines())
    lines.append(
        t(
            "aware.last_tick",
            when=profile.last_tick_at or t("aware.never_run"),
        )
    )
    granted = [n for n in _SOURCE_ORDER if profile.is_granted(n)]
    lines.append(
        t(
            "aware.granted",
            sources=", ".join(granted) if granted else t("aware.granted_none"),
        )
    )
    if profile.is_granted("apps"):
        try:
            from localagent.aware.input_activity import format_input_activity_line

            activity = (
                format_input_activity_line(since=since)
                if since
                else format_input_activity_line()
            )
            if activity:
                lines.append(activity)
        except Exception:
            pass
    return lines


def _primary_attention_line(state_lines: list[str], episodes: list) -> str | None:
    """Near-window sustained attention first; live apps frontmost is only a fallback."""
    if episodes:
        from localagent.aware.episode import rank_episodes_by_attention

        top = rank_episodes_by_attention(list(episodes), limit=1)
        if top:
            ep = top[0]
            eng = str(ep.signals.get("engagement") or "")
            bit = f"{ep.title}"
            if ep.scene or eng:
                bit = f"{ep.scene}" + (f"/{eng}" if eng else "") + f" · {ep.title}"
            if ep.duration_min >= 1:
                bit += f" · {ep.duration_min:.0f}min"
            return bit
    for ln in state_lines:
        if " · browser · " in ln and (
            "正在看=" in ln or "viewing=" in ln
        ) and "非正在看" not in ln and "not viewing" not in ln:
            return ln.split(" · browser · ", 1)[-1].strip() or None
    for ln in state_lines:
        if " · apps · " in ln:
            return ln.split(" · apps · ", 1)[-1].strip() or None
    return None


def render_summary_view(
    *,
    mode: str,
    since: str | None = None,
    source: str | None = None,
    delta_events: list[AwareEvent] | None = None,
    use_llm: bool = True,
) -> str:
    from datetime import datetime, timedelta, timezone

    from localagent.aware.episode import (
        format_episode_cards,
        load_episodes_for_overview,
        maybe_rebuild_stale_episodes,
    )

    if mode == "now":
        title = t("aware.title_overview")
        window_label = label_since(_NOW_ACTIVITY_SINCE)
    elif mode == "delta":
        title = t("aware.title_delta")
        window_label = ""
    else:
        window_label = label_since(since)
        title = t("aware.title_window", window=window_label)

    # Opportunistic cleanup when opening overview (even without a new tick).
    try:
        maybe_rebuild_stale_episodes(since_hours=24)
    except Exception:
        pass

    eps: list = []
    ep_limit = _NOW_EPISODE_LIMIT
    try:
        if mode == "window" and since:
            from localagent.aware.timewin import since_to_datetime

            since_dt = since_to_datetime(since)
            ep_limit = 8
        elif mode == "now":
            since_dt = datetime.now(timezone.utc) - timedelta(hours=_NOW_EPISODE_HOURS)
            ep_limit = _NOW_EPISODE_LIMIT
        else:
            since_dt = datetime.now(timezone.utc) - timedelta(hours=_NOW_EPISODE_HOURS)
            ep_limit = _NOW_EPISODE_LIMIT
        eps = load_episodes_for_overview(since=since_dt, limit=ep_limit)
    except Exception:
        eps = []
        ep_limit = _NOW_EPISODE_LIMIT

    ep_card_lines = (
        format_episode_cards(eps, limit=ep_limit, by_attention=True).splitlines()
        if eps
        else []
    )
    card = build_fact_card(
        mode=mode,
        since=since,
        source=source,
        delta_events=delta_events,
        episode_lines=ep_card_lines,
    )
    activity = summarize_activity(card, use_llm=use_llm, window_label=window_label)

    lines = [title, ""]
    state_lines = render_current_state_block(source=source) if mode == "now" else []

    if mode == "now":
        primary = _primary_attention_line(state_lines, eps)
        lines.append(t("aware.section_focus"))
        lines.append(f"  {primary}" if primary else t("aware.no_focus"))
        lines.append("")
        lines.append(t("aware.section_state"))
        lines.extend(state_lines)
        if load_profile().is_granted("apps"):
            try:
                from localagent.aware.input_activity import format_input_activity_line

                input_line = format_input_activity_line(since=_NOW_ACTIVITY_SINCE)
                if input_line:
                    lines.append(f"  · {input_line}")
            except Exception:
                pass
        lines.append("")
        lines.append(
            t(
                "aware.section_activity",
                window=label_since(_NOW_ACTIVITY_SINCE),
            )
        )
    else:
        lines.append(t("aware.section_dynamics"))
    for ln in activity:
        lines.append(f"  · {ln}" if not ln.startswith("  ") else ln)

    if eps:
        lines.append("")
        lines.append(t("aware.section_episodes"))
        for ln in ep_card_lines:
            lines.append(
                f"  {ln.lstrip('- ').strip()}" if ln.startswith("- ") else f"  {ln}"
            )

    lines.append("")
    lines.append(t("aware.section_system"))
    status_since = since if mode == "window" else None
    for ln in format_status_block(since=status_since):
        lines.append(f"  {ln}")
    lines.append("")
    lines.append(t("aware.tip_overview"))
    return "\n".join(lines).rstrip() + "\n"
