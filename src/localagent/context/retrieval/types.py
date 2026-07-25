"""Structured retrieval results for the Context Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

RetrievalSource = Literal["warm", "cold", "documents", "empty", "fallback"]


@dataclass
class RetrievalResult:
    """Raw hits plus optional formatted tool-style text."""

    hits: list[dict[str, Any]] = field(default_factory=list)
    source: RetrievalSource = "empty"
    text: str = ""
    total: int = 0
