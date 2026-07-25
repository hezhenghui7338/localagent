"""Optional LLM semantic validation for ambiguous tool results."""

from __future__ import annotations

import json
import logging
import re

from localagent import config
from localagent.agent.validation.types import ValidationContext, ValidationResult
from localagent.models.router import ChatMessage

logger = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{[^{}]*\"severity\"[^{}]*\}", re.DOTALL)


def _llm_enabled() -> bool:
    return getattr(config, "VALIDATION_LLM", False)


def _llm_max_calls() -> int:
    return max(0, int(getattr(config, "VALIDATION_LLM_MAX", 1)))


def _should_run_semantic(ctx: ValidationContext, programmatic: ValidationResult) -> bool:
    if not _llm_enabled():
        return False
    if ctx.router is None:
        return False
    if ctx.semantic_calls >= _llm_max_calls():
        return False
    # Never override hard programmatic failures.
    if programmatic.severity == "fail":
        if programmatic.evidence.get("tool_error"):
            return False
        exit_code = programmatic.evidence.get("exit_code")
        if exit_code is not None and exit_code != 0:
            return False
        if programmatic.evidence.get("readback_failed"):
            return False
        if programmatic.evidence.get("freshness_failed"):
            return False
        if programmatic.evidence.get("test_failed"):
            return False
    if programmatic.severity == "warn":
        return True
    # Borderline milestone: done_when keyword match count == 1
    done_when = (ctx.milestone_done_when or "").strip()
    if done_when and programmatic.severity == "ok":
        import re as _re

        keywords = [w for w in _re.split(r"[\s,，、/|]+", done_when.lower()) if len(w) >= 2]
        obs = (ctx.raw or "").lower()
        matches = sum(1 for k in keywords if k in obs)
        if keywords and matches == 1:
            return True
    return False


def _parse_llm_verdict(text: str) -> ValidationResult | None:
    match = _JSON_RE.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    severity = str(data.get("severity") or "ok").lower()
    reason = str(data.get("reason") or "").strip()
    if severity not in {"ok", "warn", "fail"}:
        return None
    if severity == "ok":
        return ValidationResult.ok(llm_verified=True)
    if severity == "warn":
        msg = reason or "语义校验建议核对后再继续。"
        return ValidationResult.warn(msg, llm_verified=True)
    msg = reason or "语义校验判定结果不可用。"
    return ValidationResult.fail(msg, retry_hint="根据观察结果修正操作后重试。", llm_verified=True)


def maybe_semantic_validate(
    ctx: ValidationContext,
    programmatic: ValidationResult,
) -> ValidationResult:
    """Run optional LLM verifier; fall back to programmatic on any error."""
    if not _should_run_semantic(ctx, programmatic):
        return programmatic

    observation = (ctx.raw or "")[:800]
    prompt = (
        "你是工具结果校验器。根据用户问题、完成条件与工具观察，"
        "判断结果是否足以继续或已完成当前步骤。\n"
        f"工具: {ctx.tool_name}\n"
        f"用户问题: {ctx.user_query[:300]}\n"
    )
    if ctx.milestone_done_when:
        prompt += f"完成条件: {ctx.milestone_done_when}\n"
    prompt += (
        f"工具观察（截断）:\n{observation}\n\n"
        "只输出 JSON：{\"severity\": \"ok|warn|fail\", \"reason\": \"简短中文理由\"}"
    )

    try:
        reply = ctx.router.chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.0,
            usage_command="validation",
        )
        parsed = _parse_llm_verdict(reply if isinstance(reply, str) else str(reply))
        if parsed is None:
            return programmatic
        # Merge evidence from programmatic layer.
        merged_evidence = {**programmatic.evidence, **parsed.evidence}
        parsed.evidence = merged_evidence
        if parsed.severity == "ok" and programmatic.severity == "warn":
            # LLM says ok but we had warn — keep warn markers unless LLM upgraded to fail
            return programmatic
        return parsed
    except Exception as exc:
        logger.debug("semantic validation failed: %s", exc)
        return programmatic
