"""PRD / product-tour acceptance journeys (offline subprocess e2e)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import (
    JOURNEY_NEWS_MARKER,
    PROJECT_ROOT,
    kb_entries,
    minimal_chatgpt_export,
    rss_fixture_server,
    run_la,
    seed_aware_suggestion,
    seed_memory,
    warm_count,
    write_aware_watch,
    write_chat_session,
    write_kb_doc,
)

pytestmark = pytest.mark.e2e

COLD_MARKER = "LocalAgentE2EColdMarker2026"
CHAT_MARKER = "LocalAgentE2EChatArchiveMarker2026"
JOURNEY_SUM_MARKER = "JOURNEY_SUM_2026"
JOURNEY_KEEP_MARKER = "JOURNEY_KEEP_2026"


def _journey_llm_guard(la_env: dict[str, str]) -> dict[str, str]:
    """Short-circuit accidental LLM calls in offline journeys."""
    return {**la_env, "LA_OLLAMA_CHAT_TIMEOUT": "1"}


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
        ["ingest", "chatgpt", str(export)],
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
        ["ingest", "chat", "--session", sid],
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
    add = run_la(["ingest", "doc", str(doc)], env=la_env, timeout=120)
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
        ["ingest", "chatgpt", str(export)],
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


@pytest.mark.xdist_group("serial")
def test_journey_ingest_resume_updates_hot_profile(la_env, la_data_dir: Path, tmp_path: Path):
    """Ingest resume doc into kb/, compile profiles, verify Hot layer name."""
    resume_md = tmp_path / "简历-e2e-test.md"
    resume_md.write_text(
        """陈测试

现居杭州 · 可立即到岗

## 求职意向
AI 工程师

## 技术栈
Python, LLM

## 工作经历
### E2E公司 · 开发
2022 - 至今：测试项目

## 教育背景
测试大学
""",
        encoding="utf-8",
    )
    ingest = run_la(["ingest", "doc", str(resume_md)], env=la_env, timeout=120)
    assert ingest.returncode == 0, ingest.stdout + ingest.stderr

    compile_script = """
import json
from localagent.memory.compile.engine import compile_kb_profiles
from localagent.memory.core_profile import load_core_profile

stats = compile_kb_profiles()
profile = load_core_profile()
print(json.dumps({"stats": stats, "name": profile.name}, ensure_ascii=False))
"""
    base = os.environ.copy()
    base.update(la_env)
    base["PYTHONPATH"] = str(PROJECT_ROOT / "src") + os.pathsep + base.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", compile_script],
        text=True,
        capture_output=True,
        env=base,
        cwd=PROJECT_ROOT,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["stats"]["files"] >= 1
    assert payload["name"] == "陈测试"


def test_journey_summarize_default_not_kept(la_env, la_data_dir: Path, tmp_path: Path):
    """Story 11: la summarize --heuristic default does not write kb/."""
    doc = write_kb_doc(
        tmp_path,
        "journey.md",
        f"# 产品概述\n\n含关键词 {JOURNEY_SUM_MARKER}。\n\n"
        "## 安装\n\n使用 pipx 安装后运行 la setup。\n",
    )
    kb_before = kb_entries(la_data_dir)
    result = run_la(
        ["summarize", str(doc), "--no-chat", "--heuristic"],
        env=la_env,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert JOURNEY_SUM_MARKER in out
    assert "## 总结" in out or "## 结构化要点" in out
    assert "§" in out or "〔" in out
    assert kb_entries(la_data_dir) == kb_before


def test_journey_summarize_keep_rag_searchable(la_env, tmp_path: Path):
    """Story 11: --keep indexes summarize output into kb/ and rag search hits."""
    doc = write_kb_doc(
        tmp_path,
        "keep-journey.md",
        f"# 周报\n\n本周完成 {JOURNEY_KEEP_MARKER} 相关规划。\n\n"
        "## 下一步\n\n补全 journey E2E。\n",
    )
    kept = run_la(
        ["summarize", str(doc), "--no-chat", "--heuristic", "--keep"],
        env=la_env,
        timeout=60,
    )
    assert kept.returncode == 0, kept.stdout + kept.stderr
    search = run_la(["rag", "search", JOURNEY_KEEP_MARKER], env=la_env, timeout=60)
    assert search.returncode == 0
    assert JOURNEY_KEEP_MARKER in search.stdout
    assert "未找到" not in search.stdout


def test_journey_news_sync_and_brief(la_env):
    """Story 12: news sync from fixture RSS then brief --no-ui lists links."""
    with rss_fixture_server() as feed_url:
        sync = run_la(
            ["news", "sync", "--url", feed_url, "--no-ui"],
            env=la_env,
            timeout=60,
        )
        assert sync.returncode == 0, sync.stdout + sync.stderr
        assert "fetched=" in sync.stdout.lower() or "拉取" in sync.stdout or "同步" in sync.stdout

        brief = run_la(
            ["news", "brief", "--no-ui", "--plain", "--limit", "5"],
            env=la_env,
            timeout=60,
        )
        assert brief.returncode == 0, brief.stdout + brief.stderr
        assert JOURNEY_NEWS_MARKER in brief.stdout
        assert "https://example.com/journey-news" in brief.stdout

    sched = run_la(["news", "schedule", "status"], env=la_env)
    assert sched.returncode == 0


def test_journey_polish_heuristic_report(la_env):
    """Story 13: la polish --heuristic prints Brief + primary/alts without LLM."""
    env = _journey_llm_guard(la_env)
    draft = "您好，上次说的方案这周能给一下吗？我们这边有点着急。"
    result = run_la(
        ["polish", "--no-copy", "--heuristic", "--scene", "email", draft],
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    out = result.stdout
    assert "【识别】" in out
    assert "【主推】" in out
    assert "【备选" in out
    assert "all model providers failed" not in out


@pytest.mark.xdist_group("serial")
def test_journey_aware_grant_tick_no_auto_kb(
    la_env, la_data_dir: Path, tmp_path: Path
):
    """Story 13b: grant fs → tick → suggestions; never auto-write kb/."""
    env = _journey_llm_guard(la_env)
    watch = tmp_path / "watch"
    write_aware_watch(env, watch)

    prime = run_la(["aware", "tick", "--no-chat", "--heuristic"], env=env, timeout=60)
    assert prime.returncode == 0, prime.stdout + prime.stderr
    assert "跳过" not in prime.stdout

    kb_before = kb_entries(la_data_dir)
    (watch / "note.md").write_text("hello journey\n", encoding="utf-8")
    (watch / "doc.pdf").write_bytes(b"%PDF-1.4")

    tick = run_la(["aware", "tick", "--no-chat", "--heuristic"], env=env, timeout=60)
    assert tick.returncode == 0, tick.stdout + tick.stderr
    assert kb_entries(la_data_dir) == kb_before
    tick_out = tick.stdout + tick.stderr
    assert "ingest doc" in tick_out.lower() or "suggestion" in tick_out.lower()

    sug = run_la(["aware", "suggestion"], env=env, timeout=30)
    assert sug.returncode == 0, sug.stdout + sug.stderr
    assert "la ingest doc" in sug.stdout or "LA ingest doc" in sug.stdout

    seed_aware_suggestion(la_data_dir, suggested_cmd="rm -rf /", item_id="sug-deny-e2e")
    deny = run_la(["aware", "suggestion", "approve", "sug-deny-e2e"], env=env, timeout=30)
    assert deny.returncode == 1
    assert "rm -rf" in deny.stdout or "拒绝" in deny.stdout or "deny" in deny.stdout.lower()
    assert kb_entries(la_data_dir) == kb_before


def test_journey_aware_ungranted_skips_collection(la_env):
    """Story 13b: without grant, tick does not collect events."""
    result = run_la(
        ["aware", "tick", "--no-chat", "--heuristic"],
        env=_journey_llm_guard(la_env),
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "跳过" in combined or "skip" in combined.lower() or "未授权" in combined
