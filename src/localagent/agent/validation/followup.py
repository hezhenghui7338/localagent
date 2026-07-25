"""Build post-tool follow-up messages from validation results."""

from __future__ import annotations

from localagent import config
from localagent.agent.validation.annotate import output_has_validation_failure
from localagent.agent.validation.types import WARN_MARKER, ValidationResult
from localagent.tools.web_search import today_label


def validation_requests_auto_retry(validation: ValidationResult | None) -> bool:
    """True when a high-confidence read-back failure should force a tool retry."""
    if not config.VALIDATION_AUTO_RETRY or validation is None:
        return False
    return (
        validation.severity == "fail"
        and bool(validation.evidence.get("readback_failed"))
    )


def _auto_retry_readback_followup(
    tool_name: str,
    result: str,
    validation: ValidationResult,
) -> str:
    hint = validation.retry_hint or "请修正参数后重试。"
    return (
        f"工具结果:\n{result}\n"
        "【校验未通过·必须重试】read-back 核对失败。"
        f"{hint}"
        f"你必须在本轮内再次调用 {tool_name}（相同或修正后的参数），"
        "禁止向用户声称文件已写入/已修改。"
    )


def _effective_severity(result: str, validation: ValidationResult | None) -> str:
    if validation is not None:
        return validation.severity
    if output_has_validation_failure(result):
        return "fail"
    if WARN_MARKER in result:
        return "warn"
    return "ok"


def build_tool_followup(
    tool_name: str,
    result: str,
    validation: ValidationResult | None = None,
) -> str:
    """Build the post-tool user message for the ReAct loop."""
    from localagent.tools.web_search import search_output_has_freshness_warning

    severity = _effective_severity(result, validation)
    retry_hint = validation.retry_hint if validation else None

    if validation_requests_auto_retry(validation):
        return _auto_retry_readback_followup(tool_name, result, validation)

    # web_search legacy path when no validation object passed
    if tool_name == "web_search" and (
        severity == "fail"
        or search_output_has_freshness_warning(result)
        or "【相关性】" in result
    ):
        return (
            f"工具结果:\n{result}\n"
            f"今天是 {today_label()}。"
            "请先核对结果中的时间与地点是否与用户问题一致。"
            "若全部过期、不符或明显是歌词/教案/无关页面：必须再调用一次 web_search "
            "（天气 query 用「城市 今天 天气预报」，不要写完整年份；"
            "其他查询可含完整目标日期与地点）；"
            "禁止在未重试的情况下直接告诉用户去看手机或放弃。"
            "若重试后仍无可用证据，才可明确告知无法确认当前情况。"
            "若依据部分可用结果作答，末尾必须列出标题与完整链接。"
        )

    if severity == "fail":
        hint = retry_hint or "请修正问题后重试相应工具，不要直接声称已完成。"
        return (
            f"工具结果:\n{result}\n"
            f"【校验未通过】{hint}"
            "禁止忽略校验标记直接给出最终成功结论。"
        )

    if severity == "warn":
        hint = retry_hint or "请先核对工具结果是否真正满足用户请求。"
        cite = ""
        if tool_name == "web_search":
            cite = (
                "回答末尾必须列出所依据条目的标题与完整链接（便于用户核实），"
                "禁止只写「根据联网信息」而不给来源。"
            )
        return (
            f"工具结果:\n{result}\n"
            f"【校验警告】{hint}"
            "若确认结果可用则给出完整简洁的最终回答；若明显不符，说明证据不可用。"
            f"{cite}"
        )

    cite = ""
    if tool_name == "web_search":
        cite = (
            "回答末尾必须列出所依据条目的标题与完整链接（便于用户核实），"
            "禁止只写「根据联网信息」而不给来源。"
        )
    return (
        f"工具结果:\n{result}\n"
        "请先快速核对结果中的时间/地点等基础信息是否与用户问题一致；"
        "一致则给出完整简洁的最终回答，不要再次调用工具。"
        "若明显不符，说明证据不可用，不要编造或硬套过期信息。"
        f"{cite}"
    )
