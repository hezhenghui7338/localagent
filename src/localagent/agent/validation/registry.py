"""Tool result validation registry and entry point."""

from __future__ import annotations

import logging
from collections.abc import Callable

from localagent.agent.validation.annotate import annotate_output
from localagent.agent.validation.programmatic.files import validate_edit_file, validate_write_file
from localagent.agent.validation.programmatic.read_search import (
    validate_glob,
    validate_grep,
    validate_read_file,
)
from localagent.agent.validation.programmatic.shell import validate_shell
from localagent.agent.validation.programmatic.web_search import validate_web_search
from localagent.agent.validation.semantic import maybe_semantic_validate
from localagent.agent.validation.types import ValidationContext, ValidationResult

logger = logging.getLogger(__name__)

ValidatorFn = Callable[[ValidationContext], ValidationResult]

_REGISTRY: dict[str, ValidatorFn] = {
    "run_shell": validate_shell,
    "write_file": validate_write_file,
    "edit_file": validate_edit_file,
    "web_search": validate_web_search,
    "read_file": validate_read_file,
    "grep": validate_grep,
    "glob": validate_glob,
}


def register_validator(tool_name: str, fn: ValidatorFn) -> None:
    _REGISTRY[tool_name] = fn


def validate_tool_result(
    tool_name: str,
    raw: str,
    *,
    arguments: dict | None = None,
    user_query: str = "",
    milestone_done_when: str = "",
    router=None,
    semantic_calls: int = 0,
) -> tuple[str, ValidationResult]:
    """Validate tool output; return annotated text and structured result."""
    ctx = ValidationContext(
        tool_name=tool_name,
        raw=raw or "",
        arguments=arguments or {},
        user_query=user_query,
        milestone_done_when=milestone_done_when,
        router=router,
        semantic_calls=semantic_calls,
    )

    validator = _REGISTRY.get(tool_name)
    if validator is None:
        return raw or "", ValidationResult.ok()

    try:
        programmatic = validator(ctx)
    except Exception as exc:
        logger.warning("validator error tool=%s: %s", tool_name, exc)
        return raw or "", ValidationResult.ok(validator_error=str(exc))

    result = maybe_semantic_validate(ctx, programmatic)
    annotated = annotate_output(raw or "", result)
    return annotated, result
