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

# Common CN cities + XX市/区/县 — used to detect an explicit place in the query.
_PLACE_IN_QUERY = re.compile(
    r"(?:"
    r"北京|上海|广州|深圳|杭州|南京|成都|重庆|武汉|西安|苏州|天津|长沙|郑州|"
    r"青岛|大连|厦门|福州|宁波|无锡|合肥|济南|昆明|贵阳|南宁|海口|三亚|"
    r"哈尔滨|长春|沈阳|石家庄|太原|兰州|南昌|台北|香港|澳门|"
    r"东莞|佛山|珠海|中山|惠州|温州|嘉兴|金华|绍兴|"
    r"[\u4e00-\u9fff]{2,10}(?:市|区|县|州|盟)"
    r")"
)
_LOCAL_PLACE_MARKERS = ("本地", "当地", "这儿", "这里", "我们这", "这边")
_USER_QUESTION_BLOCK = re.compile(
    r"\[用户问题\]\s*(.*?)\s*(?=\[执行假设|\Z)",
    re.DOTALL,
)
_ORIGINAL_QUESTION_BLOCK = re.compile(
    r"\[用户原始问题\]\s*(.*?)\s*(?=\[用户澄清补充\]|\Z)",
    re.DOTALL,
)
_CLARIFICATION_BLOCK = re.compile(
    r"\[用户澄清补充\]\s*(.*)\Z",
    re.DOTALL,
)

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


def is_weather_query(query: str) -> bool:
    """True when the user is asking about weather / forecast."""
    return _has_any(query, _WEATHER_MARKERS)


def extract_searchable_query(text: str) -> str:
    """Unwrap intent-assumption / clarification wrappers into a plain search query."""
    raw = (text or "").strip()
    if not raw:
        return raw
    assumed = _USER_QUESTION_BLOCK.search(raw)
    if assumed:
        return assumed.group(1).strip()
    original = _ORIGINAL_QUESTION_BLOCK.search(raw)
    if original:
        base = original.group(1).strip()
        clarification = _CLARIFICATION_BLOCK.search(raw)
        if clarification:
            extra = clarification.group(1).strip()
            return f"{base} {extra}".strip() if extra else base
        return base
    return raw


def query_has_explicit_place(query: str) -> bool:
    """True when the query already names a city/district (not just 本地/这儿)."""
    q = query.strip()
    if not q:
        return False
    if any(marker in q for marker in _LOCAL_PLACE_MARKERS):
        return False
    return bool(_PLACE_IN_QUERY.search(q))


def inject_home_location_for_weather(query: str) -> str:
    """For weather with no city, prepend resolved 居住地 (profile or memory)."""
    q = query.strip()
    if not q or not is_weather_query(q):
        return q
    if query_has_explicit_place(q):
        return q
    from localagent.memory.core_profile import resolve_home_location

    place = resolve_home_location()
    if not place:
        return q
    if place in q:
        return q
    # Drop vague local markers so the real city dominates the search.
    cleaned = q
    for marker in _LOCAL_PLACE_MARKERS:
        cleaned = cleaned.replace(marker, "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,")
    return f"{place} {cleaned}".strip()


def prepare_web_query(query: str, *, today: date | None = None) -> str:
    """Normalize wrappers, inject known home city for weather, then add date hints."""
    q = extract_searchable_query(query)
    q = inject_home_location_for_weather(q)
    return augment_web_query(q, today=today)


_CN_FULL_DATE = re.compile(r"20\d{2}\s*年\s*\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?")
_ISO_LIKE_DATE = re.compile(r"20\d{2}[-/.]\d{1,2}(?:[-/.]\d{1,2})?")


def _strip_calendar_dates(text: str) -> str:
    """Remove absolute calendar dates that lure search engines into archive pages."""
    cleaned = _CN_FULL_DATE.sub(" ", text)
    cleaned = _ISO_LIKE_DATE.sub(" ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" ，,")


def augment_web_query(query: str, *, today: date | None = None) -> str:
    """Add a current-date hint when the query lacks an explicit year.

    Weather queries are special: embedding「2026年7月14日」makes engines return
    historical/archive pages that fail freshness checks. Prefer 今天/明天 and
    rely on provider time_range=day instead.
    """
    q = query.strip()
    if not q:
        return q
    d = today or date.today()

    if is_weather_query(q):
        target = query_target_date(q, today=d)
        q = _strip_calendar_dates(q) or "天气"
        if target > d:
            if not _has_any(q, _TOMORROW_MARKERS):
                q = f"{q} 明天"
        elif not _has_any(q, _TODAY_MARKERS) and not _has_any(q, _TOMORROW_MARKERS):
            q = f"{q} 今天"
        return q.strip()

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
    effective = inject_home_location_for_weather(extract_searchable_query(query))
    search_query = prepare_web_query(query)
    payload = {
        "api_key": config.TAVILY_API_KEY,
        "query": search_query,
        "max_results": max_results,
        **derive_search_params(effective),
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
        query=effective,
    )


def _search_ddgs(query: str, *, max_results: int) -> str:
    try:
        from ddgs import DDGS
    except ImportError:
        return "联网搜索失败: 未安装 ddgs，请执行 pip install ddgs（或 pip install -e .）。"

    effective = inject_home_location_for_weather(extract_searchable_query(query))
    search_query = prepare_web_query(query)
    params = derive_search_params(effective)
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
    return format_search_output(results=results, query=effective)


def _search_searxng(query: str, *, max_results: int) -> str:
    base = (getattr(config, "SEARXNG_URL", "") or "").rstrip("/")
    if not base:
        return (
            "联网搜索未配置（provider=searxng，请设置 LA_SEARXNG_URL；"
            "或改用 LA_WEB_SEARCH_PROVIDER=ddgs）。"
        )

    effective = inject_home_location_for_weather(extract_searchable_query(query))
    search_query = prepare_web_query(query)
    params = derive_search_params(effective)
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
    return format_search_output(results=results, query=effective)


def web_search(query: str, *, max_results: int = 5) -> str:
    """Search the web via the configured provider (auto / ddgs / tavily / searxng).

    Weather queries that fail freshness or return junk (lyrics/PDF/lessons) are
    automatically retried with sharper queries before returning.
    """
    result = _web_search_once(query, max_results=max_results)
    if not is_weather_query(query) and not is_weather_query(extract_searchable_query(query)):
        return result
    if not weather_search_unusable(result):
        return result

    base = inject_home_location_for_weather(extract_searchable_query(query))
    for alt in weather_retry_queries(base):
        if alt.strip() == prepare_web_query(query).strip():
            continue
        retry = _web_search_once(alt, max_results=max_results)
        if not weather_search_unusable(retry):
            return retry
        # Prefer a less-bad retry (has any 匹配) over the original.
        if "[匹配" in retry and "[匹配" not in result:
            result = retry
    return result


def _web_search_once(query: str, *, max_results: int = 5) -> str:
    provider = resolve_web_search_provider()
    if provider == "tavily":
        return _search_tavily(query, max_results=max_results)
    if provider == "searxng":
        return _search_searxng(query, max_results=max_results)
    return _search_ddgs(query, max_results=max_results)


_WEATHER_JUNK = re.compile(
    r"歌词|wordwall|weebly|\.pdf|教案|课件|what'?s the weather like|"
    r"today.?s weather song|儿歌|教学资源",
    re.IGNORECASE,
)


def weather_search_unusable(output: str) -> bool:
    """True when weather results should be retried rather than shown as final."""
    if not output or output.startswith(("联网搜索未配置", "联网搜索失败")):
        return True
    if "【核对失败】" in output:
        return True
    junk = len(_WEATHER_JUNK.findall(output))
    has_match = "[匹配" in output
    if junk >= 1 and not has_match:
        return True
    if junk >= 2 and output.count("[匹配") <= junk:
        return True
    # Freshness warning with only unknown/junk and no 匹配 → retry
    if "【时效警告】" in output and not has_match and (
        junk >= 1 or "日期未知" in output
    ):
        # If summary looks like real weather numbers, keep it.
        if re.search(r"\d+\s*°\s*[CF]|气温|多云|晴|雨|雷阵雨", output):
            return False
        return True
    return False


def weather_retry_queries(base_query: str) -> list[str]:
    """Alternative weather search strings that avoid archive/junk hits."""
    q = inject_home_location_for_weather(extract_searchable_query(base_query))
    q = _strip_calendar_dates(q)
    place_match = _PLACE_IN_QUERY.search(q)
    place = place_match.group(0) if place_match else ""
    from localagent.memory.core_profile import resolve_home_location

    if not place:
        place = resolve_home_location()
    day = "明天" if _has_any(q, _TOMORROW_MARKERS) else "今天"
    alts: list[str] = []
    if place:
        alts.extend(
            [
                f"{place} {day} 天气预报",
                f"{place}天气 {day} 实时",
                f"{place} {day}天气 气象",
            ]
        )
    else:
        alts.extend([f"{day} 天气预报", f"本地 {day}天气"])
    # Deduplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for item in alts:
        key = item.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out
