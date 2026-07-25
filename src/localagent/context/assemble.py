"""Assemble the system prompt from prefetch blocks and turn metadata."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from localagent.context.prompts import system_prompt_template
from localagent.memory.core_profile import load_core_profile
from localagent.tools import TOOL_DEFINITIONS
from localagent.tools.web_search import today_label


def build_system_prompt(
    *,
    personal_context: str = "",
    web_context: str = "",
    workspace_context: str = "",
    session_context: str = "",
    archive_context: str = "",
    document_context: str = "",
    aware_context: str = "",
    work_context: str = "",
    milestone_context: str = "",
    turn_evidence: str = "",
    tool_definitions: list[dict[str, Any]] | None = None,
) -> str:
    tools_desc = json.dumps(
        tool_definitions if tool_definitions is not None else TOOL_DEFINITIONS,
        ensure_ascii=False,
        indent=2,
    )
    today = date.today()
    today_text = f"{today_label(today)}（{today.isoformat()}）"
    profile = load_core_profile().format_for_prompt()
    prompt = (
        f"{system_prompt_template().format(tools=tools_desc, today=today_text)}\n\n{profile}"
    )
    if personal_context:
        prompt = f"{prompt}\n\n{personal_context}"
    if archive_context:
        prompt = f"{prompt}\n\n{archive_context}"
    if session_context:
        prompt = f"{prompt}\n\n{session_context}"
    if web_context:
        prompt = f"{prompt}\n\n{web_context}"
    if workspace_context:
        prompt = f"{prompt}\n\n{workspace_context}"
    if aware_context:
        prompt = f"{prompt}\n\n{aware_context}"
    if work_context:
        prompt = f"{prompt}\n\n{work_context}"
    if document_context:
        prompt = f"{prompt}\n\n{document_context}"
    if milestone_context:
        prompt = f"{prompt}\n\n{milestone_context}"
    if turn_evidence:
        prompt = f"{prompt}\n\n{turn_evidence}"
    from localagent.tone import evening_postscript_block

    evening = evening_postscript_block(surface="chat")
    if evening:
        prompt = f"{prompt}\n\n{evening}"
    return prompt
