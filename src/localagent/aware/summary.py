"""Smart overview for `la aware`: fact card → LLM (or heuristic) + daily status."""

from __future__ import annotations

import re

from localagent.aware.profile import load_profile
from localagent.aware.timewin import label_since
from localagent.aware.types import AwareEvent, IMPLEMENTED_SOURCES
from localagent.status.daily import format_daily_actions_lines

# apps first: true frontmost attention leads the fact card / current-state block.
_SOURCE_ORDER = ("apps", "browser", "git", "terminal", "fs")
_FACT_CHAR_LIMIT = 6000
_NOW_ACTIVITY_SINCE = "3h"
_NOW_EPISODE_HOURS = 3
_NOW_EPISODE_LIMIT = 5

_LEAK_LINE_RE = re.compile(
    r"(未授权|不要编造|事实卡|要求[:：]|每行一句|一笔带过|禁止把|摘要助手|"
    r"根据下面|用中文写|不要标题)",
    re.I,
)


def _format_source_lines(name: str, body: list[str]) -> list[str]:
    out: list[str] = []
    for ln in body:
        out.append(f"{name}:{ln}" if ln.startswith("  ") else f"{name}: {ln}")
    return out


def render_current_state_block(*, source: str | None = None) -> list[str]:
    """Live compact snapshots for the overview「当前状态」section (no LLM)."""
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
            text = ln.strip()
            if text.startswith("当前:"):
                text = text[len("当前:") :].strip()
            lines.append(f"  · {name} · {text}")
    if not lines:
        return ["  · 无实时快照（可先 la aware grant / 打开浏览器）"]
    return lines


def build_fact_card(
    *,
    mode: str,
    since: str | None = None,
    source: str | None = None,
    delta_events: list[AwareEvent] | None = None,
) -> str:
    """Structured facts for LLM / heuristic summary (not the full detail dump)."""
    from localagent.aware import digest as dig

    profile = load_profile()
    sources = [source] if source else list(_SOURCE_ORDER)
    sources = [s for s in sources if s in IMPLEMENTED_SOURCES]

    if mode == "now":
        window_label = label_since(_NOW_ACTIVITY_SINCE)
        lines = [f"模式: 当前概览（当前状态 + 活动窗 {window_label}）"]
    elif mode == "delta":
        lines = ["模式: 自上次探测"]
        window_label = "自上次探测"
    else:
        window_label = label_since(since or "1w")
        lines = [f"模式: 时间窗 · {window_label}"]

    for name in sources:
        if not profile.is_granted(name):
            lines.append(f"{name}: 未授权")
            continue
        if mode == "delta":
            body = dig._render_events(
                name, delta_events or [], empty="相较上次无新变化"
            )
        elif mode == "window":
            body = dig._render_window(name, since or "1w")
        else:
            # now → live snapshot first, then last-3h events
            live = dig._render_now_compact(name)
            hist = dig._render_window(name, _NOW_ACTIVITY_SINCE)
            body = [*(live or []), *hist]
        lines.extend(_format_source_lines(name, body))

    if profile.is_granted("apps"):
        try:
            from localagent.aware.input_activity import format_input_activity_line

            activity = format_input_activity_line()
            if activity:
                lines.append(f"apps: {activity}")
        except Exception:
            pass

    return "\n".join(lines)


def _is_background_selected_line(text: str) -> bool:
    return "后台选中" in text or "非正在看" in text


def _is_viewing_line(text: str) -> bool:
    return "正在看" in text and not _is_background_selected_line(text)


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
        if not line or line.startswith("模式:"):
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
        if any(
            tag in rest
            for tag in ("清晨", "上午", "下午", "傍晚", "晚上", "深夜", "白天")
        ) or ("–" in rest and any(ch.isdigit() for ch in rest)):
            if text not in timed:
                timed.append(text)
        is_current = "当前:" in rest or rest.startswith("当前")
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
        bullets.append(ln.split(" · ", 1)[-1].removeprefix("当前:").strip())
    if apps_now and len(bullets) < 4:
        bullets.append(
            "主要：" + apps_now[0].removeprefix("apps · ").removeprefix("当前:").strip()
        )
    elif browser_viewing and len(bullets) < 4:
        bullets.append(
            "主要："
            + browser_viewing[0].removeprefix("browser · ").removeprefix("当前:").strip()
        )
    if browser_viewing and apps_now and len(bullets) < 5:
        bullets.append(
            "其次："
            + browser_viewing[0].removeprefix("browser · ").removeprefix("当前:").strip()
        )
    for ln in other_now[:2]:
        if len(bullets) >= 5:
            break
        bullets.append("其次：" + ln.split(" · ", 1)[-1].removeprefix("当前:").strip())
    if browser_bg:
        bullets.append("几乎没有：后台选中标签（未浏览）")
    for ln in history:
        if len(bullets) >= 6:
            break
        # Skip raw visit dumps that repeat background noise.
        if "后台选中" in ln or "前台停留" in ln or "前台页" in ln:
            continue
        if ln in timed:
            continue
        bullets.append(ln)
    if not bullets:
        return ["近期无已记录的感知活动（可先 la aware grant / tick）"]
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


def llm_summarize_facts(card: str) -> str | None:
    """Ask the model for a short Chinese activity summary; None on any failure."""
    try:
        from localagent.models.router import ChatMessage, get_model_router
    except Exception:
        return None
    clipped = card[:_FACT_CHAR_LIMIT]
    prompt = (
        "根据本机感知事实卡，用中文写 3～6 行近期动态（不要标题）。\n"
        "发生时刻/时段是最重要元数据：优先写白天/晚上/具体钟面"
        "（如「晚上 22 点左右看视频」「上午在 Cursor 写代码」），"
        "不要只写「最近累计超 X 小时」这类总时长聚合。\n"
        "按注意力主次写：主要 / 其次 / 几乎没有。\n"
        "「当前应用」与标注「正在看」的浏览器优先；"
        "「后台选中」不是浏览，不要写成关注或停留；"
        "访问摘要不等于停留时长；勿复述本段说明。\n\n"
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


def summarize_activity(card: str, *, use_llm: bool = True) -> list[str]:
    if use_llm:
        text = llm_summarize_facts(card)
        if text:
            return [ln for ln in text.splitlines() if ln.strip()]
    return heuristic_summarize_facts(card)


def format_status_block() -> list[str]:
    """User-facing system status (daily actions + aware meta)."""
    profile = load_profile()
    lines = list(format_daily_actions_lines())
    lines.append(f"上次 tick · {profile.last_tick_at or '尚未运行'}")
    granted = [n for n in _SOURCE_ORDER if profile.is_granted(n)]
    lines.append(
        "已授权 · " + (", ".join(granted) if granted else "无（la aware grant …）")
    )
    if profile.is_granted("apps"):
        try:
            from localagent.aware.input_activity import format_input_activity_line

            activity = format_input_activity_line()
            if activity:
                lines.append(activity)
        except Exception:
            pass
    return lines


def _primary_attention_line(state_lines: list[str], episodes: list) -> str | None:
    """One-line lead focus from apps current state or top attention episode."""
    for ln in state_lines:
        if " · apps · " in ln:
            return ln.split(" · apps · ", 1)[-1].strip() or None
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
        if " · browser · " in ln and "正在看=" in ln and "非正在看" not in ln:
            return ln.split(" · browser · ", 1)[-1].strip() or None
    return None


def render_summary_view(
    *,
    mode: str,
    since: str | None = None,
    source: str | None = None,
    delta_events: list[AwareEvent] | None = None,
    use_llm: bool = True,
) -> str:
    if mode == "now":
        title = "LocalAgent · Aware · 概览"
    elif mode == "delta":
        title = "LocalAgent · Aware · 自上次探测 · 概览"
    else:
        title = f"LocalAgent · Aware · {label_since(since)} · 概览"

    card = build_fact_card(
        mode=mode, since=since, source=source, delta_events=delta_events
    )
    activity = summarize_activity(card, use_llm=use_llm)

    from datetime import datetime, timedelta, timezone

    from localagent.aware.episode import (
        format_episode_cards,
        load_episodes,
        maybe_rebuild_stale_episodes,
        rank_episodes_by_attention,
    )

    # Opportunistic cleanup when opening overview (even without a new tick).
    try:
        maybe_rebuild_stale_episodes(since_hours=24)
    except Exception:
        pass

    eps: list = []
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
        eps = load_episodes(since=since_dt, limit=max(ep_limit * 4, 40))
        eps = rank_episodes_by_attention(eps, limit=ep_limit)
    except Exception:
        eps = []
        ep_limit = _NOW_EPISODE_LIMIT

    lines = [title, ""]
    state_lines = render_current_state_block(source=source) if mode == "now" else []

    if mode == "now":
        primary = _primary_attention_line(state_lines, eps)
        lines.append("主注意力")
        lines.append(f"  {primary}" if primary else "  （暂无清晰前台焦点）")
        lines.append("")
        lines.append("当前状态")
        lines.extend(state_lines)
        if load_profile().is_granted("apps"):
            try:
                from localagent.aware.input_activity import format_input_activity_line

                input_line = format_input_activity_line()
                if input_line:
                    lines.append(f"  · {input_line}")
            except Exception:
                pass
        lines.append("")
        lines.append(f"{label_since(_NOW_ACTIVITY_SINCE)}（按注意力）")
    else:
        lines.append("感知动态")
    for ln in activity:
        lines.append(f"  · {ln}" if not ln.startswith("  ") else ln)

    if eps:
        lines.append("")
        lines.append("近期 Episode（按注意力）")
        for ln in format_episode_cards(eps, limit=ep_limit, by_attention=True).splitlines():
            lines.append(
                f"  {ln.lstrip('- ').strip()}" if ln.startswith("- ") else f"  {ln}"
            )

    lines.append("")
    lines.append("系统")
    for ln in format_status_block():
        lines.append(f"  {ln}")
    lines.append("")
    lines.append(
        "提示: 直接提问进入 aware> · --no-chat 只打印 · --detail 分源明细 · tick"
    )
    return "\n".join(lines).rstrip() + "\n"
