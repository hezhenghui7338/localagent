"""Subprocess helpers for end-to-end LA CLI tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

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
    for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "CURSOR_API_KEY", "TAVILY_API_KEY"):
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


def require_ollama_completion() -> list[str]:
    models = ollama_completion_models()
    if not models:
        pytest.skip("需要 Ollama 对话模型")
    return models


def ollama_vl_models() -> list[str]:
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get("http://localhost:11434/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])
    except Exception:
        return []

    names: list[str] = []
    for model in models:
        name = model.get("name", "")
        if not name:
            continue
        caps = {str(c) for c in (model.get("capabilities") or [])}
        lower = name.lower()
        if "vision" in caps or "-vl" in lower or "vision" in lower:
            names.append(name)
    return names


def require_ollama_vl() -> str:
    models = ollama_vl_models()
    if not models:
        pytest.skip("需要 Ollama 视觉模型")
    return models[0]


def parse_task_id(stdout: str) -> str:
    """Extract first ``t-…`` token from CLI output mentioning 后台任务."""
    for line in stdout.splitlines():
        if "后台任务" not in line and "t-" not in line:
            continue
        for token in line.split():
            if token.startswith("t-"):
                return token
    raise AssertionError(f"未找到 task id:\n{stdout}")


def wait_for_task(
    task_id: str,
    *,
    env: dict[str, str],
    timeout: float = 30.0,
    poll: float = 0.2,
) -> subprocess.CompletedProcess[str]:
    """Poll ``LA tasks <id>`` until completed/skipped/failed or timeout."""
    deadline = time.monotonic() + timeout
    last: subprocess.CompletedProcess[str] | None = None
    while time.monotonic() < deadline:
        last = run_la(["tasks", task_id], env=env)
        assert last.returncode == 0, last.stdout + last.stderr
        out = last.stdout
        if "status: completed" in out or "status: skipped" in out:
            return last
        if "status: failed" in out:
            pytest.fail(out)
        time.sleep(poll)
    pytest.fail(f"task {task_id} did not finish in {timeout}s:\n{last.stdout if last else ''}")


def memory_fact_ids(data_dir: Path) -> list[str]:
    store = data_dir / "memory_store.json"
    if not store.is_file():
        return []
    raw = json.loads(store.read_text(encoding="utf-8"))
    return [str(f["id"]) for f in raw.get("facts") or [] if f.get("id")]


def seed_memory(env: dict[str, str], text: str) -> subprocess.CompletedProcess[str]:
    result = run_la(["memory", "add", text], env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "已写入记忆" in result.stdout
    return result


def write_kb_doc(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def write_chat_session(
    data_dir: Path,
    session_id: str,
    records: list[dict],
) -> Path:
    """Write a minimal LA chat jsonl under data/conversations/."""
    path = data_dir / "conversations" / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )
    return path


def seed_pending_queue(
    data_dir: Path,
    texts: list[str],
    *,
    source: str = "e2e",
) -> list[str]:
    """Write pending_queue.json directly (CLI memory add bypasses the gate)."""
    items = []
    ids: list[str] = []
    for i, text in enumerate(texts):
        pid = f"pend{i:04d}{os.urandom(2).hex()}"
        ids.append(pid)
        items.append(
            {
                "id": pid,
                "text": text,
                "kind": "fact",
                "metadata": {"source": source},
                "slots": {},
                "memory_type": "fact",
                "tags": [],
                "created_at": "2026-07-16T00:00:00+00:00",
                "title": "e2e pending",
            }
        )
    path = data_dir / "pending_queue.json"
    path.write_text(
        json.dumps({"updated_at": "2026-07-16T00:00:00+00:00", "items": items}, ensure_ascii=False),
        encoding="utf-8",
    )
    return ids


def warm_count(env: dict[str, str]) -> int:
    """Parse Warm fact count from ``LA memory status``."""
    result = run_la(["memory", "status"], env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    for line in result.stdout.splitlines():
        if "记忆条数" in line:
            token = line.split(":")[-1].strip().split()[0]
            return int(token)
    raise AssertionError(f"未找到记忆条数:\n{result.stdout}")


def minimal_chatgpt_export(
    *,
    conversation_id: str = "conv-e2e-1",
    user_text: str = "2026年7月我决定用 LocalAgent 管理个人记忆",
    assistant_text: str = "好的，已记下。",
) -> list[dict]:
    """Minimal ChatGPT-export shaped conversation for ingest e2e."""
    user_id = "user-node"
    assistant_id = "assistant-node"
    root_id = "root-node"
    return [
        {
            "conversation_id": conversation_id,
            "id": conversation_id,
            "title": "e2e import",
            "create_time": 1757058223.0,
            "update_time": 1757058263.0,
            "current_node": assistant_id,
            "mapping": {
                root_id: {"id": root_id, "parent": None, "message": None},
                user_id: {
                    "id": user_id,
                    "parent": root_id,
                    "message": {
                        "author": {"role": "user"},
                        "content": {"content_type": "text", "parts": [user_text]},
                        "create_time": 1757058223.1,
                    },
                },
                assistant_id: {
                    "id": assistant_id,
                    "parent": user_id,
                    "message": {
                        "author": {"role": "assistant"},
                        "content": {"content_type": "text", "parts": [assistant_text]},
                        "create_time": 1757058263.0,
                    },
                },
            },
        }
    ]
