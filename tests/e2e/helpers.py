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

# Offline e2e duration budgets (seconds), longest-prefix match on argv.
# Hang protection remains ``timeout=``; budgets are opt-in via ``budget=``.
DURATION_BUDGETS: dict[tuple[str, ...], float] = {
    ("--help",): 3.0,
    ("-V",): 3.0,
    ("complete",): 3.0,
    ("logs", "--path"): 3.0,
    ("memory", "status"): 5.0,
    ("rag", "status"): 5.0,
    ("status",): 5.0,
    ("workspace",): 5.0,
    ("config", "list"): 5.0,
    ("tasks",): 5.0,
    ("memory", "pending"): 5.0,
    ("ingest", "text"): 8.0,
    ("memory", "query"): 8.0,
    ("audit",): 8.0,
    ("memory", "search"): 10.0,
    ("rag", "search"): 10.0,
    ("chat",): 10.0,
    ("summarize",): 10.0,
    ("audit", "--report"): 10.0,
    ("ingest", "doc"): 15.0,
    ("ingest", "doc", "-b"): 8.0,  # enqueue only; completion uses BACKGROUND_TASK_BUDGET
    ("polish",): 15.0,
    ("memory", "reindex"): 20.0,
    ("ingest", "rebuild"): 20.0,
    ("ingest",): 30.0,
}

# End-to-end wait for background task completion (poll wall time).
BACKGROUND_TASK_BUDGET = 30.0


def budgets_enabled() -> bool:
    """Duration budgets on unless ``LA_E2E_BUDGETS=0``."""
    return os.environ.get("LA_E2E_BUDGETS", "1").strip() not in ("0", "false", "False", "no")


def lookup_duration_budget(args: list[str]) -> float | None:
    """Longest-prefix match against ``DURATION_BUDGETS``."""
    best: float | None = None
    best_len = -1
    for prefix, seconds in DURATION_BUDGETS.items():
        n = len(prefix)
        if n > best_len and tuple(args[:n]) == prefix:
            best = seconds
            best_len = n
    return best


def _assert_within_budget(
    *,
    label: str,
    elapsed: float,
    budget: float,
    detail: str = "",
) -> None:
    if elapsed <= budget:
        return
    extra = f"\n{detail}" if detail else ""
    pytest.fail(
        f"duration budget exceeded for {label}: "
        f"elapsed={elapsed:.3f}s budget={budget:.3f}s{extra}"
    )


def run_la(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    timeout: int = 60,
    cwd: Path | None = None,
    budget: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``python -m localagent.cli …``.

    ``timeout`` is hang protection only. Pass ``budget=`` (seconds) to fail when
    wall time exceeds the budget; existing e2e omit it and are unchanged.
    """
    base_env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "CURSOR_API_KEY", "TAVILY_API_KEY"):
        base_env.pop(key, None)
    if env:
        base_env.update(env)
    t0 = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-m", "localagent.cli", *args],
        input=input_text,
        text=True,
        capture_output=True,
        env=base_env,
        cwd=cwd or PROJECT_ROOT,
        timeout=timeout,
    )
    elapsed = time.perf_counter() - t0
    if budgets_enabled() and budget is not None:
        detail = (result.stdout or "")[:400] + (result.stderr or "")[:200]
        _assert_within_budget(
            label=repr(args),
            elapsed=elapsed,
            budget=budget,
            detail=detail,
        )
    return result


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


def parse_task_id(stdout: str) -> str:
    """Extract first ``t-…`` token from CLI output mentioning 后台任务."""
    for line in stdout.splitlines():
        if "后台任务" not in line and "background task" not in line and "t-" not in line:
            continue
        for token in line.replace("=", " ").split():
            if token.startswith("t-"):
                return token
    raise AssertionError(f"未找到 task id:\n{stdout}")


def wait_for_task(
    task_id: str,
    *,
    env: dict[str, str],
    timeout: float = 30.0,
    poll: float = 0.2,
    budget: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Poll ``LA tasks <id>`` until completed/skipped/failed or timeout.

    Optional ``budget`` asserts end-to-end poll wall time (hang ``timeout`` is separate).
    """
    t0 = time.perf_counter()
    deadline = time.monotonic() + timeout
    last: subprocess.CompletedProcess[str] | None = None
    while time.monotonic() < deadline:
        last = run_la(["tasks", task_id], env=env)
        assert last.returncode == 0, last.stdout + last.stderr
        out = last.stdout
        if "status: completed" in out or "status: skipped" in out:
            if budgets_enabled() and budget is not None:
                _assert_within_budget(
                    label=f"wait_for_task({task_id})",
                    elapsed=time.perf_counter() - t0,
                    budget=budget,
                    detail=out[:400],
                )
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
    result = run_la(["ingest", "text", text], env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Warm" in result.stdout or "warm=" in result.stdout or "已写入" in result.stdout
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
