"""web_search result validation (wraps existing freshness markers)."""

from __future__ import annotations

from localagent.agent.validation.types import ValidationContext, ValidationResult
from localagent.tools.web_search import search_output_has_freshness_warning


def validate_web_search(ctx: ValidationContext) -> ValidationResult:
    raw = ctx.raw or ""
    if "【核对失败】" in raw:
        return ValidationResult.fail(
            "联网搜索结果未通过核对（时效/地点/相关性）。",
            retry_hint=(
                "换查询重试 web_search（天气用「城市 今天 天气预报」；"
                "新闻用「城市 新闻」；勿写完整年份）。"
            ),
            freshness_failed=True,
        )
    if search_output_has_freshness_warning(raw) or "【相关性】" in raw:
        return ValidationResult.warn(
            "联网搜索结果有时效或相关性警告，请核对后再作答。",
            retry_hint="若证据不足，换查询重试 web_search。",
            freshness_warning=True,
        )
    return ValidationResult.ok()
