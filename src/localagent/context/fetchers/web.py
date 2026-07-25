"""Web search prefetch for time-sensitive questions."""

from __future__ import annotations

from localagent.context.compress import compress_observation
from localagent.context.router import PrefetchRoute, prefetch_header


def prefetch_web_context(
    user_message: str,
    *,
    route: PrefetchRoute | None = None,
) -> str:
    """Run web search upfront for time-sensitive questions (avoids relying on small models)."""
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
        header = prefetch_header(
            route,
            "web",
            strong=(
                "[联网搜索结果（已预加载，直接回答，勿再调用 web_search）]"
                "回答末尾必须列出所依据条目的标题与完整链接，便于用户核实。"
            ),
            soft=(
                "[联网搜索结果（已预加载，可优先据此回答；不足时再调用 web_search）]"
                "回答末尾必须列出所依据条目的标题与完整链接，便于用户核实。"
            ),
        )
    return f"{header}\n{result}"
