"""Optional Neo4j precise-query smoke via LA_NEO4J_URI=memory:// (no Bolt)."""

from __future__ import annotations

import pytest

from helpers import run_la, seed_memory

pytestmark = pytest.mark.e2e


def test_e2e_memory_graph_neo4j_memory_uri(la_env):
    env = {
        **la_env,
        "LA_NEO4J": "1",
        "LA_NEO4J_URI": "memory://",
    }
    seed_memory(env, "Caroline 住在 Seattle，和 Melanie 是朋友。")
    rebuild = run_la(["memory", "graph", "neo4j", "rebuild"], env=env, timeout=60)
    assert rebuild.returncode == 0, rebuild.stdout + rebuild.stderr
    assert "已重建" in rebuild.stdout
    assert "memory://" in rebuild.stdout

    stats = run_la(["memory", "graph", "neo4j", "stats"], env=env, timeout=60)
    assert stats.returncode == 0
    assert "启用" in stats.stdout
    assert "是" in stats.stdout

    query = run_la(
        ["memory", "graph", "query", "提到过几次 Caroline？"],
        env=env,
        timeout=60,
    )
    # Template path or hybrid fallback — must not crash; prefer a numeric/mention answer.
    assert query.returncode in (0, 1), query.stdout + query.stderr
    assert "[错误]" not in query.stdout
    assert "Caroline" in query.stdout or "次" in query.stdout or "value" in query.stdout.lower() or "结果" in query.stdout
