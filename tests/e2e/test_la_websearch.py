"""E2E: LA websearch CLI contract (story 7 — searchable, no auto Warm write)."""

from __future__ import annotations

import pytest

from helpers import run_la, seed_memory, warm_count

pytestmark = pytest.mark.e2e


def test_e2e_websearch_help(la_env):
    result = run_la(["websearch", "--help"], env=la_env)
    assert result.returncode == 0
    assert "query" in result.stdout.lower() or "搜索" in result.stdout


def test_e2e_websearch_without_tavily_key_does_not_write_warm(la_env):
    """Offline-stable: tavily without key fails loudly and must not retain Warm."""
    env = {
        **la_env,
        "LA_WEB_SEARCH_PROVIDER": "tavily",
        "TAVILY_API_KEY": "",
    }
    # Strip inherited key if any (helpers also pop it, but be explicit).
    before = warm_count(env)
    seed_memory(env, "对照事实：用户偏好离线测试联网不入库。")
    before_seeded = warm_count(env)

    result = run_la(
        ["websearch", "今天深圳天气", "--top-k", "3"],
        env=env,
        timeout=60,
    )
    assert result.returncode == 0
    out = result.stdout + result.stderr
    assert "未配置" in out or "TAVILY" in out or "联网搜索" in out
    assert warm_count(env) == before_seeded
    assert before_seeded == before + 1


def test_e2e_websearch_ddgs_smoke_or_skip(la_env):
    """Optional live ddgs; skip on network/provider failure — never write Warm."""
    env = {**la_env, "LA_WEB_SEARCH_PROVIDER": "ddgs"}
    before = warm_count(env)
    result = run_la(["websearch", "LocalAgent open source", "--top-k", "2"], env=env, timeout=90)
    assert result.returncode == 0
    out = result.stdout
    if "失败" in out or "未安装" in out or "Error" in out:
        pytest.skip(f"ddgs unavailable: {out[:200]}")
    assert warm_count(env) == before
    # Successful search should print something beyond the emit banner.
    assert len(out.strip()) > 10
