"""PRD / product-tour acceptance journeys (offline subprocess e2e)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from helpers import (
    minimal_chatgpt_export,
    run_la,
    seed_memory,
    warm_count,
    write_chat_session,
    write_kb_doc,
)

pytestmark = pytest.mark.e2e

COLD_MARKER = "LocalAgentE2EColdMarker2026"
CHAT_MARKER = "LocalAgentE2EChatArchiveMarker2026"


def test_journey_cross_session_warm_recall(la_env):
    """Story 4: facts written once remain searchable (session-agnostic Warm)."""
    seed_memory(la_env, "用户姓名是张三，日常偏好用 VS Code。")
    search = run_la(["memory", "search", "姓名"], env=la_env)
    assert search.returncode == 0
    assert "张三" in search.stdout or "VS Code" in search.stdout


def test_journey_chatgpt_cold_before_warm(la_env, tmp_path: Path):
    """§6.2: ChatGPT ingest always indexes Cold; rag search must hit body text."""
    export = tmp_path / "conversations.json"
    export.write_text(
        json.dumps(
            minimal_chatgpt_export(
                conversation_id="conv-cold-1",
                user_text=f"我把项目代号定为 {COLD_MARKER} 以便归档检索。",
                assistant_text="已记录。",
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = run_la(
        ["memory", "ingest", "chatgpt", str(export)],
        env=la_env,
        timeout=180,
    )
    assert result.returncode == 0
    assert "cold_chunks=" in result.stdout
    cold_m = re.search(r"cold_chunks=(\d+)", result.stdout)
    assert cold_m is not None
    assert int(cold_m.group(1)) > 0

    search = run_la(["rag", "search", COLD_MARKER], env=la_env, timeout=60)
    assert search.returncode == 0
    assert COLD_MARKER in search.stdout
    assert "未找到" not in search.stdout


def test_journey_chat_ingest_cold_searchable(la_env, la_data_dir: Path):
    """LA chat ingest indexes conversation Cold even when Warm extract is empty."""
    sid = "s-e2e-cold-chat"
    write_chat_session(
        la_data_dir,
        sid,
        [
            {"ts": "2026-07-16T10:00:00", "role": "user", "content": f"请记住关键词 {CHAT_MARKER}"},
            {"ts": "2026-07-16T10:00:01", "role": "assistant", "content": "好的"},
        ],
    )
    result = run_la(
        ["memory", "ingest", "chat", "--session", sid],
        env=la_env,
        timeout=120,
    )
    assert result.returncode == 0
    assert "cold_chunks" in result.stdout.lower() or "未提取" in result.stdout or "已保存" in result.stdout

    search = run_la(["rag", "search", CHAT_MARKER], env=la_env, timeout=60)
    assert search.returncode == 0
    assert CHAT_MARKER in search.stdout
    assert "未找到" not in search.stdout


def test_journey_rag_does_not_create_warm(la_env, tmp_path: Path):
    """Story 6 / pillar 5: rag add indexes Cold only — Warm count unchanged."""
    before = warm_count(la_env)
    doc = write_kb_doc(tmp_path, "notes.md", f"# Notes\n\nRAG 文档不应产生 Warm：{COLD_MARKER}\n")
    add = run_la(["rag", "add", str(doc)], env=la_env, timeout=120)
    assert add.returncode == 0
    assert warm_count(la_env) == before

    search = run_la(["rag", "search", COLD_MARKER], env=la_env, timeout=60)
    assert search.returncode == 0
    assert COLD_MARKER in search.stdout


def test_journey_reset_chatgpt_clears_cold_archive(la_env, tmp_path: Path):
    """README Cold contract: memory reset chatgpt removes matching Cold chunks."""
    export = tmp_path / "conversations.json"
    export.write_text(
        json.dumps(
            minimal_chatgpt_export(
                conversation_id="conv-reset-cold",
                user_text=f"归档关键词 {COLD_MARKER} reset 测试。",
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ingest = run_la(
        ["memory", "ingest", "chatgpt", str(export)],
        env=la_env,
        timeout=180,
    )
    assert ingest.returncode == 0
    hit = run_la(["rag", "search", COLD_MARKER], env=la_env, timeout=60)
    assert COLD_MARKER in hit.stdout

    reset = run_la(["memory", "reset", "chatgpt"], env=la_env)
    assert reset.returncode == 0

    miss = run_la(["rag", "search", COLD_MARKER], env=la_env, timeout=60)
    assert miss.returncode == 0
    assert COLD_MARKER not in miss.stdout or "未找到" in miss.stdout


def test_journey_audit_report_html(la_env, tmp_path: Path):
    """Story 10 / tour checklist: audit --report out.html."""
    # Touch usage/audit via a cheap command that logs.
    assert run_la(["memory", "status"], env=la_env).returncode == 0
    out = tmp_path / "audit.html"
    result = run_la(["audit", "--report", str(out)], env=la_env)
    assert result.returncode == 0
    assert "报告已写入" in result.stdout
    assert out.is_file()
    html = out.read_text(encoding="utf-8")
    assert "<html" in html.lower()
    assert "LocalAgent" in html or "Token" in html or "token" in html.lower()
