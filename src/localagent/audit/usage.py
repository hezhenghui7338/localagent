"""Model/API usage logging and aggregation."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from localagent import config

# Rough USD per 1M tokens (override via env)
_DEFAULT_COST_PER_M = {
    "ollama": 0.0,
    "openai": float(os.getenv("LA_COST_OPENAI_PER_M", os.getenv("LA_COST_MINIMAX_PER_M", "1.0"))),
    "openrouter": float(os.getenv("LA_COST_OPENROUTER_PER_M", "3.0")),
    "cursor": float(os.getenv("LA_COST_CURSOR_PER_CALL", "0.05")),
    "tavily": float(os.getenv("LA_COST_TAVILY_PER_CALL", "0.01")),
    "ddgs": 0.0,
    "searxng": 0.0,
}


def estimate_tokens(text: str) -> int:
    """Heuristic token count (~4 chars per token for mixed CJK/Latin)."""
    if not text:
        return 0
    return max(1, len(text) // 4)


@dataclass
class UsageEvent:
    ts: str
    provider: str
    model: str
    command: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UsageEvent:
        return cls(
            ts=str(data["ts"]),
            provider=str(data["provider"]),
            model=str(data.get("model", "")),
            command=str(data.get("command", "chat")),
            prompt_tokens=int(data.get("prompt_tokens", 0)),
            completion_tokens=int(data.get("completion_tokens", 0)),
            total_tokens=int(data.get("total_tokens", 0)),
            estimated_cost_usd=float(data.get("estimated_cost_usd", 0.0)),
            session_id=data.get("session_id"),
        )


def _usage_log_path() -> Path:
    config.AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return config.USAGE_LOG_FILE


def estimate_cost_usd(
    provider: str,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    per_call: bool = False,
) -> float:
    if per_call and provider in ("cursor", "tavily"):
        return _DEFAULT_COST_PER_M.get(provider, 0.0)
    rate = _DEFAULT_COST_PER_M.get(provider, 0.0)
    total = prompt_tokens + completion_tokens
    return round(total * rate / 1_000_000, 6)


def log_usage(
    provider: str,
    model: str,
    *,
    command: str = "chat",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    session_id: str | None = None,
    per_call: bool = False,
) -> UsageEvent:
    """Append one usage event to local audit log."""
    total = prompt_tokens + completion_tokens
    event = UsageEvent(
        ts=datetime.now(timezone.utc).isoformat(),
        provider=provider,
        model=model,
        command=command,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
        estimated_cost_usd=estimate_cost_usd(
            provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            per_call=per_call,
        ),
        session_id=session_id,
    )
    path = _usage_log_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
    return event


def parse_since(value: str | None) -> datetime | None:
    """Parse --since like 7d, 24h, 30m."""
    if not value:
        return None
    value = value.strip().lower()
    now = datetime.now(timezone.utc)
    if value.endswith("d"):
        return now - timedelta(days=int(value[:-1]))
    if value.endswith("h"):
        return now - timedelta(hours=int(value[:-1]))
    if value.endswith("m"):
        return now - timedelta(minutes=int(value[:-1]))
    raise ValueError(f"invalid --since {value!r}; use e.g. 7d, 24h, 30m")


def load_usage_events(since: datetime | None = None) -> list[UsageEvent]:
    path = _usage_log_path()
    if not path.exists():
        return []
    events: list[UsageEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = UsageEvent.from_dict(json.loads(line))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        if since is not None:
            try:
                ts = datetime.fromisoformat(event.ts.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if ts < since:
                continue
        events.append(event)
    return events


def aggregate_usage(events: list[UsageEvent]) -> dict[str, Any]:
    if not events:
        return {
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "by_provider": {},
            "by_command": {},
            "by_model": {},
        }

    by_provider: dict[str, dict[str, Any]] = {}
    by_command: dict[str, int] = {}
    by_model: dict[str, dict[str, Any]] = {}
    total_tokens = 0
    total_cost = 0.0

    for event in events:
        total_tokens += event.total_tokens
        total_cost += event.estimated_cost_usd
        by_command[event.command] = by_command.get(event.command, 0) + 1

        bucket = by_provider.setdefault(
            event.provider,
            {"calls": 0, "tokens": 0, "cost_usd": 0.0},
        )
        bucket["calls"] += 1
        bucket["tokens"] += event.total_tokens
        bucket["cost_usd"] = round(bucket["cost_usd"] + event.estimated_cost_usd, 6)

        model_key = f"{event.provider}/{event.model}" if event.model else event.provider
        mb = by_model.setdefault(model_key, {"calls": 0, "tokens": 0, "cost_usd": 0.0})
        mb["calls"] += 1
        mb["tokens"] += event.total_tokens
        mb["cost_usd"] = round(mb["cost_usd"] + event.estimated_cost_usd, 6)

    return {
        "total_calls": len(events),
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "by_provider": by_provider,
        "by_command": by_command,
        "by_model": by_model,
    }
