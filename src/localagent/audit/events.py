"""Append-only audit event stream for tool decisions, intent, and guardrails."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from localagent import config
from localagent.audit.usage import parse_since

SCHEMA_VERSION = 1
_MAX_SUMMARY_LEN = 240


def _events_log_path() -> Path:
    config.AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return getattr(config, "EVENTS_LOG_FILE", config.AUDIT_DIR / "events.jsonl")


def _truncate(value: str | None, limit: int = _MAX_SUMMARY_LEN) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def log_event(
    event_type: str,
    *,
    session_id: str | None = None,
    **payload: Any,
) -> dict[str, Any]:
    """Append one structured event to data/audit/events.jsonl."""
    event: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
    }
    for key, value in payload.items():
        if value is None:
            continue
        if key in {"summary", "reason", "message", "command", "path", "query"} and isinstance(
            value, str
        ):
            event[key] = _truncate(value)
        else:
            event[key] = value

    path = _events_log_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def load_events(
    since: datetime | None = None,
    *,
    event_type: str | None = None,
) -> list[dict[str, Any]]:
    path = _events_log_path()
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or "type" not in data:
            continue
        if event_type is not None and data.get("type") != event_type:
            continue
        if since is not None:
            ts_raw = data.get("ts")
            if not isinstance(ts_raw, str):
                continue
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if ts < since:
                continue
        events.append(data)
    return events


def load_events_since(since: str | None = None) -> list[dict[str, Any]]:
    since_dt = parse_since(since) if since else None
    return load_events(since_dt)


def aggregate_behavior(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up tool / guardrail events for audit reports."""
    tool_counts: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    guardrail_actions: Counter[str] = Counter()
    blocked: list[dict[str, str]] = []
    denied: list[dict[str, str]] = []

    for event in events:
        etype = str(event.get("type") or "")
        if etype == "tool.decision":
            tool = str(event.get("tool") or "unknown")
            outcome = str(event.get("outcome") or "unknown")
            tool_counts[tool] += 1
            outcomes[outcome] += 1
            entry = {
                "tool": tool,
                "reason": str(event.get("reason") or event.get("summary") or ""),
            }
            if outcome == "blocked":
                blocked.append(entry)
            elif outcome == "denied":
                denied.append(entry)
        elif etype in {"guardrail.triggered", "kb.blocked"}:
            action = str(event.get("action") or event.get("outcome") or "block")
            guardrail_actions[action] += 1
            if etype == "kb.blocked" or action == "block":
                blocked.append(
                    {
                        "tool": str(event.get("policy_id") or etype),
                        "reason": str(event.get("reason") or event.get("path") or ""),
                    }
                )

    return {
        "total_events": len(events),
        "tool_counts": dict(tool_counts),
        "outcomes": dict(outcomes),
        "guardrail_triggers": sum(guardrail_actions.values()),
        "guardrail_actions": dict(guardrail_actions),
        "blocked": blocked[:20],
        "denied": denied[:20],
        "shell_count": tool_counts.get("run_shell", 0),
        "write_file_count": tool_counts.get("write_file", 0),
        "web_search_count": tool_counts.get("web_search", 0),
    }
