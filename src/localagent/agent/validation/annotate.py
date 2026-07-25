"""Inject validation markers into tool output."""

from __future__ import annotations

from localagent.agent.validation.types import FAIL_MARKER, WARN_MARKER, ValidationResult


def output_has_validation_failure(text: str) -> bool:
    """True when output tells the agent not to trust the result."""
    return FAIL_MARKER in text


def output_has_validation_warning(text: str) -> bool:
    """True when output asks the agent to double-check before answering."""
    return WARN_MARKER in text or FAIL_MARKER in text


def annotate_output(raw: str, result: ValidationResult) -> str:
    """Prepend validation markers; leave raw output intact below."""
    if not result.markers:
        return raw
    header = "\n".join(result.markers)
    body = (raw or "").strip()
    if not body:
        return header
    return f"{header}\n{body}"
