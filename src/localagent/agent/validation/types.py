"""Structured tool result validation types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["ok", "warn", "fail"]

FAIL_MARKER = "【核对失败】"
WARN_MARKER = "【核对警告】"


@dataclass
class ValidationResult:
    """Outcome of post-execution tool result validation."""

    severity: Severity = "ok"
    markers: list[str] = field(default_factory=list)
    retry_hint: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, **evidence: Any) -> ValidationResult:
        return cls(severity="ok", evidence=dict(evidence))

    @classmethod
    def warn(cls, message: str, *, retry_hint: str | None = None, **evidence: Any) -> ValidationResult:
        return cls(
            severity="warn",
            markers=[f"{WARN_MARKER}{message}"],
            retry_hint=retry_hint,
            evidence=dict(evidence),
        )

    @classmethod
    def fail(cls, message: str, *, retry_hint: str | None = None, **evidence: Any) -> ValidationResult:
        return cls(
            severity="fail",
            markers=[f"{FAIL_MARKER}{message}"],
            retry_hint=retry_hint,
            evidence=dict(evidence),
        )


@dataclass
class ValidationContext:
    """Inputs available to per-tool validators."""

    tool_name: str
    raw: str
    arguments: dict[str, Any] = field(default_factory=dict)
    user_query: str = ""
    milestone_done_when: str = ""
    router: Any | None = None
    semantic_calls: int = 0
