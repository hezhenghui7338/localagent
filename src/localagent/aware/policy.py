"""Whitelist reactions for aware events (suggestions only; never auto-ingest into kb)."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from localagent import config
from localagent.aware.suggestion import enqueue
from localagent.aware.types import AwareEvent


@dataclass
class PolicyResult:
    auto_actions: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _enqueue_rag_suggest(path: str, *, source: str) -> str:
    return enqueue(
        source=source,
        title=f"新文件 {Path(path).name}",
        rationale="可手动索引或 summarize（须用户确认后入库）",
        suggested_cmd=f"la ingest doc {shlex.quote(path)}",
        data={"path": path},
    )


def apply_policy(events: list[AwareEvent]) -> PolicyResult:
    result = PolicyResult()
    suggest_suffixes = set(getattr(config, "AWARE_SUGGEST_SUFFIXES", set()))
    noise = set(getattr(config, "AWARE_NOISE_SUFFIXES", set()))
    per_tick = int(getattr(config, "AWARE_SUGGEST_PER_TICK", 10) or 10)
    seen_paths: set[str] = set()
    suggest_n = 0

    for event in events:
        if event.source in {"fs", "wechat"} and event.kind in {
            "file.created",
            "wechat.file_received",
        }:
            path = str(event.data.get("path") or "")
            suffix = str(event.data.get("suffix") or Path(path).suffix.lower())
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            if suffix in noise:
                continue
            if suffix in suggest_suffixes and event.kind in {
                "file.created",
                "wechat.file_received",
            }:
                if suggest_n >= per_tick:
                    continue
                iid = _enqueue_rag_suggest(path, source=event.source)
                result.suggestions.append(iid)
                suggest_n += 1

    return result


def react_to_events(events: list[AwareEvent]) -> dict[str, Any]:
    result = apply_policy(events)
    return {
        "auto": result.auto_actions,
        "suggestions": result.suggestions,
        "errors": result.errors,
    }
