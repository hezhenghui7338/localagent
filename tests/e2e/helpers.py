"""Subprocess helpers for end-to-end LA CLI tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_la(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: int = 60,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    base_env = os.environ.copy()
    for key in ("OPENROUTER_API_KEY", "CURSOR_API_KEY", "TAVILY_API_KEY"):
        base_env.pop(key, None)
    if env:
        base_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "localagent.cli", *args],
        input=input_text,
        text=True,
        capture_output=True,
        env=base_env,
        cwd=cwd or PROJECT_ROOT,
        timeout=timeout,
    )


def ollama_completion_models() -> list[str]:
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get("http://localhost:11434/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
    except Exception:
        return []

    names: list[str] = []
    for model in models:
        caps = set(model.get("capabilities") or [])
        if caps == {"embedding"}:
            continue
        name = model.get("name", "")
        if name:
            names.append(name)
    return names
