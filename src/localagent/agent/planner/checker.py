"""Milestone completion heuristics and optional LLM done_when verification."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from localagent.agent.validation.annotate import output_has_validation_failure

logger = logging.getLogger(__name__)

_JSON_DONE_RE = re.compile(r"\{[^{}]*\"done\"[^{}]*\}", re.DOTALL)

_SUCCESS_MARKERS = (
    "已写入",
    "已追加",
    "已编辑",
    "已修改",
    "success",
    "passed",
    "ok",
    "完成",
    "executed",
    "written",
    "saved",
)
_FAILURE_MARKERS = (
    "错误",
    "失败",
    "不存在",
    "permission denied",
    "not found",
    "no such file",
    "用户拒绝",
    "测试失败",
    "failed",
    "error",
)
_READ_DONE_RE = re.compile(
    r"(?:已知|找到|定位|路径|path|line\s+\d+|第\s*\d+\s*行)",
    re.IGNORECASE,
)
_EXIT_RE = re.compile(r"^exit:\s*(-?\d+)\s*$", re.MULTILINE)


def summarize_observation(tool_name: str, result: str, *, limit: int = 200) -> str:
    """Compress a tool observation into a short milestone summary."""
    from localagent.context.compress import summarize_for_milestone

    return summarize_for_milestone(tool_name, result, limit=limit)


def _parse_exit_code(observation: str) -> int | None:
    match = _EXIT_RE.search(observation or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def milestone_done_heuristic(
    milestone,
    *,
    tool_calls: list[dict],
    last_observation: str,
    last_tool_name: str = "",
    last_validation=None,
) -> bool:
    """Best-effort check whether a milestone's done_when is satisfied."""
    obs = (last_observation or "").lower()
    done_when = (milestone.done_when or "").lower()

    if output_has_validation_failure(last_observation or ""):
        return False

    if last_validation is not None and last_validation.severity == "fail":
        return False

    if any(m in obs for m in _FAILURE_MARKERS):
        return False

    # Side-effect tools succeeding usually mean mutation milestones are done.
    if last_tool_name in {"write_file", "edit_file"} and any(
        m in obs for m in ("已写入", "已追加", "已编辑", "written", "saved")
    ):
        if last_validation is not None and last_validation.severity == "fail":
            return False
        return True

    if last_tool_name == "run_shell" and tool_calls:
        if any(m in obs for m in ("error", "失败", "not found", "permission denied")):
            return False
        exit_code = None
        if last_validation is not None:
            exit_code = last_validation.evidence.get("exit_code")
        if exit_code is None:
            exit_code = _parse_exit_code(last_observation or "")
        if exit_code is not None and exit_code != 0:
            return False
        if done_when and any(k in done_when for k in ("执行", "测试", "命令", "run", "test")):
            return True
        return False

    if last_tool_name in {"read_file", "glob", "grep"} and _READ_DONE_RE.search(obs):
        if done_when and any(k in done_when for k in ("路径", "定位", "已知", "找到")):
            return True

    if done_when:
        keywords = [w for w in re.split(r"[\s,，、/|]+", done_when) if len(w) >= 2]
        if keywords and sum(1 for k in keywords if k in obs) >= min(2, len(keywords)):
            return True

    if any(m in obs for m in _SUCCESS_MARKERS):
        return True

    return False


@dataclass
class MilestoneDoneDecision:
    """Outcome of milestone completion check (heuristic + optional LLM)."""

    done: bool
    source: str = "heuristic"  # heuristic | llm
    llm_rejected: bool = False


def _heuristic_is_confident(
    milestone,
    *,
    tool_calls: list[dict],
    last_observation: str,
    last_tool_name: str,
    last_validation,
) -> bool:
    """True when a positive heuristic needs no LLM confirmation."""
    if not milestone_done_heuristic(
        milestone,
        tool_calls=tool_calls,
        last_observation=last_observation,
        last_tool_name=last_tool_name,
        last_validation=last_validation,
    ):
        return False

    obs = (last_observation or "").lower()
    done_when = (milestone.done_when or "").lower()

    if last_tool_name in {"write_file", "edit_file"} and any(
        m in obs for m in ("已写入", "已追加", "已编辑", "written", "saved")
    ):
        return last_validation is None or last_validation.severity != "fail"

    if last_tool_name == "run_shell" and tool_calls:
        exit_code = None
        if last_validation is not None:
            exit_code = last_validation.evidence.get("exit_code")
        if exit_code is None:
            exit_code = _parse_exit_code(last_observation or "")
        if exit_code == 0 and done_when and any(
            k in done_when for k in ("执行", "测试", "命令", "run", "test")
        ):
            return True

    if last_tool_name in {"read_file", "glob", "grep"} and _READ_DONE_RE.search(obs):
        if done_when and any(k in done_when for k in ("路径", "定位", "已知", "找到")):
            return True

    if done_when:
        keywords = [w for w in re.split(r"[\s,，、/|]+", done_when) if len(w) >= 2]
        if keywords and sum(1 for k in keywords if k in obs) >= min(2, len(keywords)):
            return True

    return False


def _should_run_milestone_semantic(
    heuristic_done: bool,
    *,
    milestone,
    tool_calls: list[dict],
    last_observation: str,
    last_tool_name: str,
    last_validation,
    semantic_calls: int,
) -> bool:
    from localagent import config

    if not getattr(config, "VALIDATION_LLM", False):
        return False
    if semantic_calls >= max(0, int(getattr(config, "VALIDATION_LLM_MAX", 1))):
        return False
    if not tool_calls:
        return False
    if output_has_validation_failure(last_observation or ""):
        return False
    if last_validation is not None and last_validation.severity == "fail":
        return False
    if observation_suggests_replan(last_observation):
        return False

    if heuristic_done and _heuristic_is_confident(
        milestone,
        tool_calls=tool_calls,
        last_observation=last_observation,
        last_tool_name=last_tool_name,
        last_validation=last_validation,
    ):
        return False

    return True


def _parse_llm_done_verdict(text: str) -> bool | None:
    match = _JSON_DONE_RE.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    done = data.get("done")
    if isinstance(done, bool):
        return done
    if isinstance(done, str):
        return done.lower() in ("true", "yes", "1")
    return None


def _llm_verify_milestone_done(
    milestone,
    *,
    tool_calls: list[dict],
    last_observation: str,
    last_tool_name: str,
    agent_response: str,
    router: Any,
) -> bool | None:
    from localagent.models.router import ChatMessage

    observation = (last_observation or "")[:800]
    response = (agent_response or "")[:400]
    prompt = (
        "你是里程碑完成判定器。根据子目标、完成条件与工具观察，"
        "判断当前步骤是否已满足完成条件。\n"
        f"子目标: {milestone.objective}\n"
    )
    if milestone.done_when:
        prompt += f"完成条件: {milestone.done_when}\n"
    if last_tool_name:
        prompt += f"最后工具: {last_tool_name}\n"
    if observation:
        prompt += f"工具观察（截断）:\n{observation}\n"
    if response:
        prompt += f"助手回复（截断）:\n{response}\n"
    prompt += (
        "\n只输出 JSON：{\"done\": true|false, \"reason\": \"简短中文理由\"}\n"
        "规则：仅当观察/回复明确满足完成条件时 done=true；"
        "仅有部分进展、错误或条件未验证时为 false。"
    )

    try:
        reply = router.chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.0,
            usage_command="validation",
        )
        return _parse_llm_done_verdict(reply if isinstance(reply, str) else str(reply))
    except Exception as exc:
        logger.debug("milestone done_when LLM check failed: %s", exc)
        return None


def check_milestone_done(
    milestone,
    *,
    tool_calls: list[dict],
    last_observation: str,
    last_tool_name: str = "",
    last_validation=None,
    router: Any | None = None,
    agent_response: str = "",
    semantic_calls: int = 0,
) -> MilestoneDoneDecision:
    """Heuristic first; optional LLM verifies ambiguous done_when cases."""
    heuristic_done = milestone_done_heuristic(
        milestone,
        tool_calls=tool_calls,
        last_observation=last_observation,
        last_tool_name=last_tool_name,
        last_validation=last_validation,
    )

    if _should_run_milestone_semantic(
        heuristic_done,
        milestone=milestone,
        tool_calls=tool_calls,
        last_observation=last_observation,
        last_tool_name=last_tool_name,
        last_validation=last_validation,
        semantic_calls=semantic_calls,
    ):
        llm_done = _llm_verify_milestone_done(
            milestone,
            tool_calls=tool_calls,
            last_observation=last_observation,
            last_tool_name=last_tool_name,
            agent_response=agent_response,
            router=router,
        )
        if llm_done is not None:
            return MilestoneDoneDecision(
                done=llm_done,
                source="llm",
                llm_rejected=not llm_done,
            )

    return MilestoneDoneDecision(done=heuristic_done, source="heuristic")


def observation_suggests_replan(last_observation: str) -> bool:
    """True when the last tool result indicates the plan may need revision."""
    if output_has_validation_failure(last_observation or ""):
        return True
    obs = (last_observation or "").lower()
    triggers = (
        "不存在",
        "not found",
        "no such file",
        "permission denied",
        "测试失败",
        "test failed",
        "用户拒绝",
        "错误:",
        "failed",
    )
    return any(t in obs for t in triggers)
