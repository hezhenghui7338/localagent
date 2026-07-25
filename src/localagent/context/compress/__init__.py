"""Context compression — observations, evidence, and budget helpers."""

from localagent.context.compress.core import (
    ContextTier,
    EvidenceEntry,
    apply_context_budget,
    compact_prior_observations,
    compress_observation,
    extract_evidence_bullet,
    format_turn_evidence,
    resolve_context_tier,
    tool_path_signature,
    truncate_head_tail,
)
from localagent.context.compress.summary import summarize_for_milestone

__all__ = [
    "ContextTier",
    "EvidenceEntry",
    "apply_context_budget",
    "compact_prior_observations",
    "compress_observation",
    "extract_evidence_bullet",
    "format_turn_evidence",
    "resolve_context_tier",
    "summarize_for_milestone",
    "tool_path_signature",
    "truncate_head_tail",
]
