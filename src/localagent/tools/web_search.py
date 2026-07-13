"""Web search providers: Tavily, ddgs (default free), and optional SearXNG."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Literal
from urllib.parse import urljoin

import httpx

from localagent import config
from localagent.audit.usage import log_usage

WEB_SEARCH_PROVIDERS = frozenset({"auto", "ddgs", "tavily", "searxng"})

Freshness = Literal["fresh", "stale", "unknown"]
RecencyMode = Literal["day", "week", "month"]

_TODAY_MARKERS = ("今天", "今日", "today", "刚刚")
_TOMORROW_MARKERS = ("明天", "明日", "tomorrow")
_RECENT_MARKERS = ("最近", "最新", "昨天", "本周", "近期", "当下", "现在", "latest", "recent")
_NEWS_MARKERS = ("新闻", "时事", "头条", "热点", "快讯", "news", "breaking")
_TIME_MARKERS = ("几点", "当前时间", "现在时间", "今天几号", "今天日期", "what time", "current time")
_WEATHER_MARKERS = ("天气", "气温", "降雨", "预报", "weather", "forecast", "temperature")

_YMD = re.compile(r"(20\d{2})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?")
_CN_YMD = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?")
_EN_MONTHS = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}
_EN_MDY = re.compile(
    r"\b("
    + "|".join(_EN_MONTHS)
    + r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(20\d{2}))?\b",
    re.IGNORECASE,
)
_EN_Y_MON = re.compile(
    r"\b(20\d{2})\s+(" + "|".join(_EN_MONTHS) + r")\b",
    re.IGNORECASE,
)


def normalize_web_search_provider(value: str | None) -> str:
    """Return a valid provider name; invalid values fall back to auto."""
    raw = (value or "auto").strip().lower() or "auto"
    if raw in WEB_SEARCH_PROVIDERS:
        return raw
    return "auto"


def resolve_web_search_provider() -> str:
    """Resolve auto → tavily (if key) → searxng (if URL) → ddgs."""
    choice = normalize_web_search_provider(getattr(config, "WEB_SEARCH_PROVIDER", "auto"))
    if choice != "auto":
        return choice
    if config.TAVILY_API_KEY:
        return "tavily"
    if getattr(config, "SEARXNG_URL", ""):
        return "searxng"
    return "ddgs"


def _has_any(query: str, markers: tuple[str, ...]) -> bool:
    q = query.lower()
    return any(marker in query or marker in q for marker in markers)


def query_recency_mode(query: str) -> RecencyMode | None:
    """Infer how fresh results must be for this query."""
    if (
        _has_any(query, _TIME_MARKERS)
        or _has_any(query, _TODAY_MARKERS)
        or _has_any(query, _TOMORROW_MARKERS)
    ):
        return "day"
    if _has_any(query, _WEATHER_MARKERS):
        return "day"
    if _has_any(query, _NEWS_MARKERS) or _has_any(query, _RECENT_MARKERS):
        return "week"
    return None


def today_label(today: date | None = None) -> str:
    """Human-readable today stamp used in prompts and search output."""
    d = today or date.today()
    return f"{d.year}年{d.month}月{d.day}日"


def query_target_date(query: str, *, today: date | None = None) -> date:
    """Calendar day the user is asking about (today, or tomorrow when markers match)."""
    d = today or date.today()
    if _has_any(query, _TOMORROW_MARKERS):
        return d + timedelta(days=1)
    return d


def augment_web_query(query: str, *, today: date | None = None) -> str:
    """Add a current-date hint when the query lacks an explicit year."""
    q = query.strip()
    if not q:
        return q
    d = today or date.today()
    if re.search(r"20\d{2}", q):
        return q
    mode = query_recency_mode(q)
    target = query_target_date(q, today=d)
    if mode == "day":
        return f"{q} {today_label(target)}"
    return f"{q} {target.year}年{target.month:02d}月"


def derive_search_params(query: str) -> dict[str, Any]:
    """Derive recency/topic options from query text (Tavily-oriented; reused by others)."""
    opts: dict[str, Any] = {"search_depth": "basic", "include_answer": True}

    is_news = _has_any(query, _NEWS_MARKERS)
    is_recent = _has_any(query, _RECENT_MARKERS)
    is_today = _has_any(query, _TODAY_MARKERS)
    is_tomorrow = _has_any(query, _TOMORROW_MARKERS)
    is_time = _has_any(query, _TIME_MARKERS)
    is_weather = _has_any(query, _WEATHER_MARKERS)

    if is_news:
        opts["topic"] = "news"
        opts["days"] = 1 if (is_today or is_tomorrow) else 7
    elif is_time or is_today or is_tomorrow or is_weather:
        opts["time_range"] = "day"
    elif is_recent:
        opts["time_range"] = "week"
    return opts


def _timelimit_from_params(params: dict[str, Any]) -> str | None:
    """Map derive_search_params → ddgs timelimit (d/w/m/y)."""
    if params.get("topic") == "news":
        return "d" if params.get("days") == 1 else "w"
    time_range = params.get("time_range")
    if time_range == "day":
        return "d"
    if time_range == "week":
        return "w"
    if time_range == "month":
        return "m"
    if time_range == "year":
        return "y"
    return None


def _searxng_time_range(params: dict[str, Any]) -> str | None:
    if params.get("topic") == "news":
        return "day" if params.get("days") == 1 else "week"
    time_range = params.get("time_range")
    if time_range in ("day", "week", "month", "year"):
        return time_range
    return None


def _safe_date(year: int, month: int, day: int | None = None) -> date | None:
    try:
        if day is None:
            return date(year, month, 1)
        return date(year, month, day)
    except ValueError:
        return None


def extract_dates_from_text(text: str) -> list[date]:
    """Pull calendar dates from titles/snippets/published fields."""
    if not text:
        return []
    found: list[date] = []
    seen: set[date] = set()

    def _add(parsed: date | None) -> None:
        if parsed is None or parsed in seen:
            return
        seen.add(parsed)
        found.append(parsed)

    for match in _CN_YMD.finditer(text):
        day = int(match.group(3)) if match.group(3) else None
        _add(_safe_date(int(match.group(1)), int(match.group(2)), day))
    for match in _YMD.finditer(text):
        day = int(match.group(3)) if match.group(3) else None
        _add(_safe_date(int(match.group(1)), int(match.group(2)), day))
    for match in _EN_MDY.finditer(text):
        month = _EN_MONTHS[match.group(1).lower()]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else date.today().year
        _add(_safe_date(year, month, day))
    for match in _EN_Y_MON.finditer(text):
        month = _EN_MONTHS[match.group(2).lower()]
        _add(_safe_date(int(match.group(1)), month))
    return found


def _freshness_window(mode: RecencyMode, today: date) -> date:
    if mode == "day":
        return today - timedelta(days=2)
    if mode == "week":
        return today - timedelta(days=7)
    return today - timedelta(days=31)


def classify_result_freshness(
    item: dict[str, Any],
    *,
    today: date,
    mode: RecencyMode | None,
) -> tuple[Freshness, date | None]:
    """Classify one hit; return (label, best date found)."""
    if mode is None:
        return "unknown", None

    blob = " ".join(
        str(item.get(key) or "")
        for key in ("published_date", "title", "content", "url")
    )
    dates = extract_dates_from_text(blob)
    if not dates:
        return "unknown", None

    # Prefer the most recent explicit date in the snippet.
    best = max(dates)
    earliest_ok = _freshness_window(mode, today)
    # Future dates more than a day ahead are usually page template junk.
    if best > today + timedelta(days=1):
        return "stale", best
    if best < earliest_ok:
        # Year-month only (day=1) still counts as that month for mismatch.
        if best.year != today.year or best.month != today.month:
            return "stale", best
        if mode == "day" and best.day != 1 and best < earliest_ok:
            return "stale", best
        if mode == "day" and best.day == 1 and today.day > 3:
            # Bare "2026年7月" without a day is weak evidence for "今天".
            return "unknown", best
    return "fresh", best


def search_output_has_freshness_warning(text: str) -> bool:
    """True when formatted output tells the model not to trust results as current."""
    return "【时效警告】" in text or "【核对失败】" in text


def format_search_output(
    *,
    answer: str = "",
    results: list[dict[str, Any]],
    query: str = "",
    today: date | None = None,
) -> str:
    """Normalize provider payloads into the agent-facing text block with freshness audit."""
    as_of = today or date.today()
    # Freshness is judged against the day the user asked about (e.g. 明天 → tomorrow).
    target = query_target_date(query, today=as_of) if query else as_of
    mode = query_recency_mode(query) if query else None
    lines: list[str] = [
        f"【检索基准日】{today_label(target)}（{target.isoformat()}）",
    ]
    if target != as_of:
        lines.append(f"【日历今天】{today_label(as_of)}（{as_of.isoformat()}）")
    if mode:
        if _has_any(query, _TOMORROW_MARKERS):
            need = "明天/次日"
        else:
            need = {"day": "今天/当日", "week": "近一周", "month": "近一月"}[mode]
        lines.append(f"【时效要求】用户问题需要匹配「{need}」的信息")

    audited: list[tuple[Freshness, date | None, dict[str, Any]]] = []
    for item in results:
        label, hit_date = classify_result_freshness(item, today=target, mode=mode)
        audited.append((label, hit_date, item))

    fresh_n = sum(1 for label, _, _ in audited if label == "fresh")
    stale_n = sum(1 for label, _, _ in audited if label == "stale")
    unknown_n = sum(1 for label, _, _ in audited if label == "unknown")

    if mode and results:
        lines.append(
            f"【时效核对】匹配 {fresh_n} 条 / 过期 {stale_n} 条 / 日期未知 {unknown_n} 条"
        )
        if fresh_n == 0 and stale_n > 0:
            lines.append(
                "【核对失败】没有与检索基准日相符的结果。"
                "禁止把过期结果当作当前事实（如今日天气/新闻）播报；"
                "应换用含完整日期与地点的查询重试，或明确告知用户证据不足。"
            )
        elif stale_n > 0 and fresh_n > 0:
            lines.append(
                "【时效警告】部分结果已过期；回答时只采信标注为「匹配」的条目，忽略「过期」条目。"
            )
        elif fresh_n == 0 and unknown_n > 0:
            lines.append(
                "【时效警告】结果未标明可靠日期；回答前须自行核对文中时间/地点是否与用户请求一致，"
                "不确定则说明证据不足，不要当作已核实的当前事实。"
            )

    usable = [item for label, _, item in audited if label != "stale"]
    stale_items = [(hit_date, item) for label, hit_date, item in audited if label == "stale"]

    # Tavily-style answers are often derived from mixed/stale hits — drop when no fresh evidence.
    if answer and not (mode and fresh_n == 0 and stale_n > 0):
        if mode and fresh_n == 0 and unknown_n > 0:
            lines.append(f"摘要（日期未核实，慎用）: {answer}")
        else:
            lines.append(f"摘要: {answer}")

    if not results:
        return "\n".join(lines + [answer or "未找到联网结果。"])

    label_zh = {"fresh": "匹配", "stale": "过期", "unknown": "日期未知"}

    def _append_item(label: Freshness, hit_date: date | None, item: dict[str, Any]) -> None:
        published = item.get("published_date") or ""
        date_bits: list[str] = [label_zh[label]]
        if hit_date:
            date_bits.append(hit_date.isoformat())
        elif published:
            date_bits.append(str(published))
        title = item.get("title") or ""
        content = (item.get("content") or "")[:200]
        url = item.get("url") or ""
        lines.append(f"- [{'·'.join(date_bits)}] {title}: {content}")
        if url:
            source_name = title.strip() or url
            lines.append(f"  来源: {source_name}")
            lines.append(f"  链接: {url}")
        else:
            lines.append("  来源: （无链接）")

    if mode and fresh_n == 0 and stale_n > 0:
        lines.append("过期结果（仅供排查，不可当作当前事实）:")
        for hit_date, item in stale_items:
            _append_item("stale", hit_date, item)
        for label, hit_date, item in audited:
            if label == "unknown":
                _append_item(label, hit_date, item)
    else:
        for label, hit_date, item in audited:
            if label == "stale":
                continue
            _append_item(label, hit_date, item)
        if stale_items:
            lines.append("已过滤的过期结果:")
            for hit_date, item in stale_items:
                _append_item("stale", hit_date, item)

    if mode and not usable and not answer:
        lines.append("未找到与用户时间要求相符的联网结果。")
    lines.append(
        "【引用要求】回答用户时必须列出所依据条目的标题与完整链接（链接: …），"
        "便于用户核实；禁止只写「根据联网信息/预加载结果」而不给来源。"
    )
    return "\n".join(lines)


def _log_search_usage(provider: str) -> None:
    try:
        log_usage(provider, "search", command="web_search", per_call=True)
    except Exception:
        pass


def _search_tavily(query: str, *, max_results: int) -> str:
    if not config.TAVILY_API_KEY:
        return (
            "联网搜索未配置（provider=tavily，请设置 TAVILY_API_KEY；"
            "或改用 LA_WEB_SEARCH_PROVIDER=ddgs / searxng）。"
        )
    search_query = augment_web_query(query)
    payload = {
        "api_key": config.TAVILY_API_KEY,
        "query": search_query,
        "max_results": max_results,
        **derive_search_params(query),
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return f"联网搜索失败: {exc}"

    _log_search_usage("tavily")
    results = [
        {
            "title": r.get("title", ""),
            "content": r.get("content", ""),
            "url": r.get("url", ""),
            "published_date": r.get("published_date", ""),
        }
        for r in data.get("results") or []
    ]
    return format_search_output(
        answer=data.get("answer") or "",
        results=results,
        query=query,
    )


def _search_ddgs(query: str, *, max_results: int) -> str:
    try:
        from ddgs import DDGS
    except ImportError:
        return "联网搜索失败: 未安装 ddgs，请执行 pip install ddgs（或 pip install -e .）。"

    search_query = augment_web_query(query)
    params = derive_search_params(query)
    timelimit = _timelimit_from_params(params)
    use_news = params.get("topic") == "news"

    try:
        with DDGS() as ddgs:
            if use_news:
                kwargs: dict[str, Any] = {"max_results": max_results}
                if timelimit:
                    kwargs["timelimit"] = timelimit
                raw = list(ddgs.news(search_query, **kwargs))
            else:
                kwargs = {"max_results": max_results}
                if timelimit:
                    kwargs["timelimit"] = timelimit
                raw = list(ddgs.text(search_query, **kwargs))
    except Exception as exc:
        return f"联网搜索失败: {exc}"

    _log_search_usage("ddgs")
    results: list[dict[str, Any]] = []
    for item in raw:
        if use_news:
            results.append(
                {
                    "title": item.get("title") or "",
                    "content": item.get("body") or "",
                    "url": item.get("url") or "",
                    "published_date": item.get("date") or "",
                }
            )
        else:
            results.append(
                {
                    "title": item.get("title") or "",
                    "content": item.get("body") or "",
                    "url": item.get("href") or item.get("url") or "",
                    "published_date": "",
                }
            )
    return format_search_output(results=results, query=query)


def _search_searxng(query: str, *, max_results: int) -> str:
    base = (getattr(config, "SEARXNG_URL", "") or "").rstrip("/")
    if not base:
        return (
            "联网搜索未配置（provider=searxng，请设置 LA_SEARXNG_URL；"
            "或改用 LA_WEB_SEARCH_PROVIDER=ddgs）。"
        )

    search_query = augment_web_query(query)
    params = derive_search_params(query)
    request_params: dict[str, Any] = {
        "q": search_query,
        "format": "json",
        "language": "auto",
    }
    if params.get("topic") == "news":
        request_params["categories"] = "news"
    time_range = _searxng_time_range(params)
    if time_range:
        request_params["time_range"] = time_range

    url = urljoin(base + "/", "search")
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(url, params=request_params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return f"联网搜索失败: {exc}"

    _log_search_usage("searxng")
    raw_results = data.get("results") or []
    results: list[dict[str, Any]] = []
    for item in raw_results[:max_results]:
        results.append(
            {
                "title": item.get("title") or "",
                "content": item.get("content") or item.get("snippet") or "",
                "url": item.get("url") or item.get("href") or "",
                "published_date": item.get("publishedDate") or item.get("published_date") or "",
            }
        )
    return format_search_output(results=results, query=query)


def web_search(query: str, *, max_results: int = 5) -> str:
    """Search the web via the configured provider (auto / ddgs / tavily / searxng)."""
    provider = resolve_web_search_provider()
    if provider == "tavily":
        return _search_tavily(query, max_results=max_results)
    if provider == "searxng":
        return _search_searxng(query, max_results=max_results)
    return _search_ddgs(query, max_results=max_results)
