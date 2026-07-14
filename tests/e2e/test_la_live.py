"""Live end-to-end tests requiring real Ollama (slow)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from helpers import require_ollama_completion, run_la, seed_memory
from localagent.persist.chatgpt import parse_conversation

pytestmark = pytest.mark.e2e_live

FACT = "2026年7月决定使用 Mem0 作为记忆引擎，并搭配 Chroma 做知识库。"


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

    require_ollama_completion()

    result = run_la(["memory", "ingest", "chat", "--session", session_id], env=la_env, timeout=300)
    assert result.returncode == 0
    assert "已保存" in result.stdout or "未提取" in result.stdout


def test_e2e_chat_live(la_env, la_data_dir: Path):
    require_ollama_completion()

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

    conv = la_data_dir / "conversations" / "s-e2e-live.json"
    assert conv.exists()
    raw = json.loads(conv.read_text(encoding="utf-8"))
    messages = parse_conversation(raw).messages
    assert len(messages) >= 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"


def test_e2e_live_memory_search_semantic(la_env):
    require_ollama_completion()
    seed_memory(la_env, FACT)
    result = run_la(["memory", "search", "长期记忆用什么引擎"], env=la_env, timeout=180)
    assert result.returncode == 0
    assert "Mem0" in result.stdout


def test_e2e_live_memory_reflect_multihop(la_env):
    require_ollama_completion()
    env = {**la_env, "LA_MEMORY_REFLECT_MAX_HOPS": "2"}
    seed_memory(env, FACT)
    seed_memory(env, "用户周末喜欢徒步，不喜欢嘈杂的商场。")
    result = run_la(
        ["memory", "reflect", "记忆引擎选型，以及我周末偏好是什么？"],
        env=env,
        timeout=300,
    )
    assert result.returncode == 0
    assert "未能从记忆中推理出答案" not in result.stdout
    assert "Mem0" in result.stdout or "徒步" in result.stdout


def test_e2e_live_rag_search_after_add(la_env, tmp_path: Path):
    require_ollama_completion()
    doc = tmp_path / "live.md"
    doc.write_text("# Spec\n\n检索通路：Warm=Mem0，Cold=Chroma+BM25。\n", encoding="utf-8")
    assert run_la(["rag", "add", str(doc)], env=la_env, timeout=180).returncode == 0
    result = run_la(["rag", "search", "Cold 检索用什么"], env=la_env, timeout=120)
    assert result.returncode == 0
    assert "Chroma" in result.stdout or "BM25" in result.stdout or "Cold" in result.stdout
