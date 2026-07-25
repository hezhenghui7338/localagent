"""Shared ReAct tool loop for simple and milestone execution paths."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from localagent.agent.validation import ValidationResult, build_tool_followup, validate_tool_result
from localagent.context.working_memory import ReactWorkingMemory
from localagent.agent.runtime import (
    _empty_reply_retry,
    _incomplete_reply_retry,
    _looks_incomplete_reply,
    _looks_like_tool_attempt,
    _make_answer_stream_gate,
    _needs_file_tool_retry,
    _parse_tool_call,
    _strip_tool_blocks,
    _TOOL_FORMAT_RETRY,
    _TOOL_LABELS,
    _EMPTY_RESPONSE_FALLBACK,
)
from localagent.audit.events import log_event
from localagent.i18n import resolve_lang, t
from localagent.models.router import ChatMessage
from localagent.tools.approval import ToolRisk

logger = logging.getLogger(__name__)


@dataclass
class ReactLoopResult:
    response: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    last_observation: str = ""
    last_tool_name: str = ""
    last_validation: ValidationResult | None = None
    semantic_calls: int = 0
    exhausted: bool = False
    repeat_breaker: bool = False


def _call_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    return json.dumps(
        {"name": tool_name, "arguments": arguments},
        sort_keys=True,
        ensure_ascii=False,
    )


def run_react_loop(
    *,
    messages: list[ChatMessage],
    user_message: str,
    router: Any,
    prefer: str | None,
    session_id: str | None,
    max_iterations: int,
    on_status: Callable[[str], None] | None,
    on_token: Callable[[str], None] | None,
    gated_execute: Callable[[str, dict[str, Any]], str],
    log_tool_decision: Callable[..., None] | None = None,
    skip_file_retry: bool = False,
    milestone_done_when: str = "",
    milestone_objective: str = "",
    rebuild_system: Callable[..., str] | None = None,
    goal: str = "",
    working_memory: ReactWorkingMemory | None = None,
) -> ReactLoopResult:
    """Run up to ``max_iterations`` tool rounds; return final or partial response."""
    tool_calls: list[dict[str, Any]] = []
    reply = ""
    last_observation = ""
    last_tool_name = ""
    last_validation: ValidationResult | None = None
    last_sig: str | None = None
    repeat_count = 0
    semantic_calls = 0
    max_iter = max(1, max_iterations)
    last_iter = max_iter - 1
    turn_goal = (goal or user_message or "").strip()
    wm = working_memory or ReactWorkingMemory(
        goal=turn_goal,
        user_query=user_message,
        prefer=prefer,
        router=router,
        rebuild_system=rebuild_system,
    )

    def _status(msg: str) -> None:
        if on_status is not None:
            on_status(msg)

    if wm.rebuild_system:
        wm.refresh_system(messages)

    for iteration in range(max_iter):
        if iteration == 0:
            if router.should_hint_ollama_cold_start(prefer):
                _status(t("chat.status_generate_cold"))
            else:
                _status(t("chat.status_generate"))
        else:
            _status(t("chat.status_synthesize", n=iteration + 1))

        reply = router.chat(
            messages,
            temperature=0.3,
            prefer=prefer,
            on_token=_make_answer_stream_gate(on_token),
            usage_command="chat",
            session_id=session_id,
        )
        if not isinstance(reply, str):
            reply = "" if reply is None else str(reply)

        if not reply.strip() and iteration < last_iter:
            logger.info("agent empty reply retry iteration=%s", iteration)
            messages.append(ChatMessage(role="assistant", content=reply or "(空)"))
            messages.append(ChatMessage(role="user", content=_empty_reply_retry()))
            continue

        call = _parse_tool_call(reply)
        if not call:
            clean = _strip_tool_blocks(reply)
            if not clean and _looks_like_tool_attempt(reply) and iteration < last_iter:
                logger.info("agent tool-format retry iteration=%s", iteration)
                messages.append(ChatMessage(role="assistant", content=reply))
                messages.append(ChatMessage(role="user", content=_TOOL_FORMAT_RETRY))
                continue
            if (
                _looks_incomplete_reply(clean, had_tools=bool(tool_calls))
                and iteration < last_iter
            ):
                logger.info("agent incomplete-reply retry iteration=%s", iteration)
                messages.append(ChatMessage(role="assistant", content=reply))
                messages.append(
                    ChatMessage(role="user", content=_incomplete_reply_retry())
                )
                continue
            needs_retry = (
                not skip_file_retry
                and _needs_file_tool_retry(user_message, clean, tool_calls)
            )
            if needs_retry and iteration < last_iter:
                logger.info("agent file-tool retry iteration=%s", iteration)
                messages.append(ChatMessage(role="assistant", content=reply))
                import re

                append_mode = bool(re.search(r"追加", user_message, re.IGNORECASE))
                mode_hint = (
                    'mode 设为 "append"。'
                    if append_mode
                    else '覆盖写入用 mode "overwrite"，追加用 mode "append"。'
                )
                messages.append(
                    ChatMessage(
                        role="user",
                        content=(
                            "你尚未调用 edit_file / write_file 或 run_shell 就声称已完成文件操作。"
                            "局部修改请先调用 edit_file；新建或整文件覆盖用 write_file；"
                            f"{mode_hint}"
                            "再根据工具返回结果回答用户，不要编造文件内容。"
                        ),
                    )
                )
                continue
            if needs_retry:
                clean = (
                    "未能实际写入文件：模型未调用 edit_file / write_file 或 run_shell。"
                    "请重试，或使用 /provider openrouter 等更强模型。"
                )
            if not clean.strip():
                clean = _EMPTY_RESPONSE_FALLBACK
            elif _looks_incomplete_reply(clean, had_tools=bool(tool_calls)):
                clean = (
                    f"{clean.rstrip()}…\n\n"
                    "（回答被截断。请再试一次，或提高 Ollama 的 num_predict / 换用更强模型。）"
                )
            return ReactLoopResult(
                response=clean,
                tool_calls=tool_calls,
                last_observation=last_observation,
                last_tool_name=last_tool_name,
                last_validation=last_validation,
                semantic_calls=semantic_calls,
            )

        tool_name = call.get("name", "")
        arguments = call.get("arguments", {}) or {}
        sig = _call_signature(tool_name, arguments)
        if sig == last_sig:
            repeat_count += 1
        else:
            repeat_count = 0
            last_sig = sig

        if repeat_count >= 1 and wm.path_signature_seen(tool_name, arguments):
            logger.info(
                "agent repeat-call breaker (evidence) tool=%s iteration=%s",
                tool_name,
                iteration,
            )
            log_event(
                "agent.repeat_call_breaker",
                session_id=session_id,
                tool=tool_name,
                iteration=iteration,
                reason="evidence",
            )
            messages.append(ChatMessage(role="assistant", content=reply))
            messages.append(
                ChatMessage(role="user", content=wm.repeat_breaker_message())
            )
            synth = router.chat(
                messages,
                temperature=0.3,
                prefer=prefer,
                on_token=_make_answer_stream_gate(on_token),
                usage_command="chat",
                session_id=session_id,
            )
            clean = _strip_tool_blocks(synth if isinstance(synth, str) else "")
            if not clean.strip():
                clean = _EMPTY_RESPONSE_FALLBACK
            return ReactLoopResult(
                response=clean,
                tool_calls=tool_calls,
                last_observation=last_observation,
                last_tool_name=last_tool_name,
                last_validation=last_validation,
                semantic_calls=semantic_calls,
                repeat_breaker=True,
            )

        if repeat_count >= 2:
            logger.info("agent repeat-call breaker tool=%s iteration=%s", tool_name, iteration)
            log_event(
                "agent.repeat_call_breaker",
                session_id=session_id,
                tool=tool_name,
                iteration=iteration,
            )
            messages.append(ChatMessage(role="assistant", content=reply))
            messages.append(
                ChatMessage(role="user", content=wm.repeat_breaker_message())
            )
            # One more generation attempt for synthesis.
            synth = router.chat(
                messages,
                temperature=0.3,
                prefer=prefer,
                on_token=_make_answer_stream_gate(on_token),
                usage_command="chat",
                session_id=session_id,
            )
            clean = _strip_tool_blocks(synth if isinstance(synth, str) else "")
            if not clean.strip():
                clean = _EMPTY_RESPONSE_FALLBACK
            return ReactLoopResult(
                response=clean,
                tool_calls=tool_calls,
                last_observation=last_observation,
                last_tool_name=last_tool_name,
                last_validation=last_validation,
                semantic_calls=semantic_calls,
                repeat_breaker=True,
            )

        tool_label = _TOOL_LABELS.get(tool_name, tool_name or t("chat.tool_fallback"))
        if resolve_lang() == "en":
            tool_label = tool_name or t("chat.tool_fallback")
        logger.info("agent tool call name=%s iteration=%s", tool_name or "-", iteration)
        query = arguments.get("query", "") or arguments.get("command", "")
        if query:
            preview = query if len(query) <= 40 else f"{query[:40]}…"
            _status(t("chat.status_tool_call", label=tool_label, preview=preview))
        else:
            _status(t("chat.status_tool_call_plain", label=tool_label))

        tool_calls.append(call)

        from localagent.agent.validation.pre_call import (
            build_pre_call_followup,
            check_tool_call,
        )

        precheck = check_tool_call(
            tool_name,
            arguments,
            milestone_objective=milestone_objective,
            tool_calls=tool_calls[:-1],
        )
        if precheck is not None and precheck.severity in ("warn", "fail"):
            logger.info(
                "agent pre-call tool check tool=%s severity=%s iteration=%s",
                tool_name,
                precheck.severity,
                iteration,
            )
            messages.append(ChatMessage(role="assistant", content=reply))
            messages.append(
                ChatMessage(role="user", content=build_pre_call_followup(precheck))
            )
            tool_calls.pop()
            continue

        raw = gated_execute(tool_name, arguments)
        annotated, vresult = validate_tool_result(
            tool_name,
            raw,
            arguments=arguments,
            user_query=user_message,
            milestone_done_when=milestone_done_when,
            router=router,
            semantic_calls=semantic_calls,
        )
        if vresult.evidence.get("llm_verified"):
            semantic_calls += 1
        tier = wm.tier()
        result = wm.compress_tool_observation(
            tool_name,
            annotated,
            budget=tier.observe_budget,
        )
        last_observation = result
        last_tool_name = tool_name
        last_validation = vresult
        wm.append_evidence(tool_name, annotated, arguments=arguments)
        wm.refresh_system(messages)
        messages.append(ChatMessage(role="assistant", content=reply))
        messages.append(
            ChatMessage(
                role="user",
                content=build_tool_followup(tool_name, result, vresult),
            )
        )
        wm.compact_prior_observations(messages)

    final = _strip_tool_blocks(reply)
    if not final.strip():
        final = _EMPTY_RESPONSE_FALLBACK
    elif _looks_incomplete_reply(final, had_tools=bool(tool_calls)):
        final = (
            f"{final.rstrip()}…\n\n"
            "（回答被截断。请再试一次，或提高 Ollama 的 num_predict / 换用更强模型。）"
        )
    log_event(
        "agent.iteration_exhausted",
        session_id=session_id,
        iterations=max_iter,
        tools=len(tool_calls),
    )
    return ReactLoopResult(
        response=final,
        tool_calls=tool_calls,
        last_observation=last_observation,
        last_tool_name=last_tool_name,
        last_validation=last_validation,
        semantic_calls=semantic_calls,
        exhausted=True,
    )
