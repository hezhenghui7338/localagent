"""Post-execution tool result validation."""

from localagent.agent.validation.annotate import (
    output_has_validation_failure,
    output_has_validation_warning,
)
from localagent.agent.validation.followup import build_tool_followup
from localagent.agent.validation.registry import register_validator, validate_tool_result
from localagent.agent.validation.types import FAIL_MARKER, WARN_MARKER, ValidationContext, ValidationResult

__all__ = [
    "FAIL_MARKER",
    "WARN_MARKER",
    "ValidationContext",
    "ValidationResult",
    "build_tool_followup",
    "output_has_validation_failure",
    "output_has_validation_warning",
    "register_validator",
    "validate_tool_result",
]
