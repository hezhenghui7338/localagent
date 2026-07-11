"""Live end-to-end tests requiring real Ollama (slow)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers import ollama_completion_models, run_la

pytestmark = pytest.mark.e2e_live


def test_e2e_rememorize_chat(la_env, la_data_dir: Path):
    session_id = "s-remem-e2e"
    records = [
        {"ts": "2026-07-11T10:00:00", "role": "user", "content": "我计划下周开始 Phase 0"},
        {"ts": "2026-07-11T10:00:01", "role": "assistant", "content": "好的"},
    ]
    conv = la_data_dir / "conversations" / f"{session_id}.jsonl"
    conv.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    if not ollama_completion_models():
        pytest.skip("需要 Ollama 对话模型以提取记忆")

    result = run_la(["rememorize-chat", "--session", session_id], env=la_env, timeout=300)
    assert result.returncode == 0
    assert "已保存" in result.stdout or "未提取" in result.stdout


def test_e2e_chat_live(la_env, la_data_dir: Path):
    if not ollama_completion_models():
        pytest.skip("需要 Ollama 对话模型")

    env = {
        **la_env,
        "OLLAMA_MODEL": "qwen3:4b",
    }
    result = run_la(
        ["chat", "--session-id", "s-e2e-live"],
        env=env,
        input_text="say hi\n:q\n",
        timeout=300,
    )
    assert result.returncode == 0
    assert "all model providers failed" not in result.stdout
    assert "[错误]" not in result.stdout

    conv = la_data_dir / "conversations" / "s-e2e-live.jsonl"
    assert conv.exists()
    lines = [json.loads(line) for line in conv.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 2
    assert lines[0]["role"] == "user"
    assert lines[1]["role"] == "assistant"
