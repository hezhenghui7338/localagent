"""LLM-as-judge helpers (optional; skipped when no judge provider)."""

from __future__ import annotations

import json
import os
import re
from typing import Any


def judge_available() -> bool:
    return bool(
        os.environ.get("LA_EVAL_JUDGE_PROVIDER")
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("CURSOR_API_KEY")
    )


def score_response(
    *,
    criterion: str,
    prompt: str,
    response: str,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return {score: 1-5, rationale: str} or skip when judge unavailable."""
    if os.environ.get("LA_EVAL_SKIP_JUDGE", "").strip() in ("1", "true", "yes"):
        return {"score": None, "rationale": "judge skipped (LA_EVAL_SKIP_JUDGE)"}

    if not judge_available():
        return {"score": None, "rationale": "judge unavailable (no provider/key)"}

    from localagent.models.router import chat_completion

    provider = os.environ.get("LA_EVAL_JUDGE_PROVIDER", "openrouter")
    rubric = (
        "You are an evaluator for LocalAgent. Score 1-5 where 5 fully meets the criterion.\n"
        f"Criterion: {criterion}\n"
        f"User prompt: {prompt}\n"
        f"Agent response: {response}\n"
        f"Trace JSON: {json.dumps(trace or {}, ensure_ascii=False)[:4000]}\n"
        "Reply with JSON only: {\"score\": N, \"rationale\": \"...\"}"
    )
    try:
        raw = chat_completion(
            [{"role": "user", "content": rubric}],
            provider=provider,
            temperature=0.0,
        )
    except Exception as exc:
        return {"score": None, "rationale": f"judge error: {exc}"}

    text = (raw or "").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {"score": None, "rationale": f"unparseable judge output: {text[:200]}"}
    try:
        payload = json.loads(match.group(0))
        score = int(payload.get("score", 0))
        return {
            "score": max(1, min(5, score)),
            "rationale": str(payload.get("rationale") or ""),
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"score": None, "rationale": f"invalid judge json: {text[:200]}"}
