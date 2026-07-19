"""E2E fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def la_data_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    for sub in ("kb", "conversations", "chroma"):
        (data / sub).mkdir(parents=True, exist_ok=True)
    return data


@pytest.fixture
def la_env(la_data_dir: Path) -> dict[str, str]:
    """Isolated data dir; json backend; keep offline e2e reasonably fast."""
    return {
        "LA_DATA_DIR": str(la_data_dir),
        "LA_INGEST_USE_LLM": "0",
        "LA_MEMORY_BACKEND": "json",
        "LA_MEMORY_SESSION_SUMMARY": "0",
        "LA_MEMORY_REFLECT_MAX_HOPS": "0",
        # Pin Chinese UI so e2e assertions stay stable regardless of host LA_LANG.
        "LA_LANG": "zh",
        # Subprocess does not inherit unit-test monkeypatches; disable LLM pin
        # so memory add cannot hang on a slow/local Ollama call.
        "LA_PROFILE_PIN_LLM": "0",
        # Subprocess e2e: auto-approve Warm writes (no pending queue).
        "LA_MEMORY_APPROVAL_AUTO": "1",
        "LA_MEMORY_APPROVAL_REQUIRED": "0",
        # Isolate from developer .env (Neo4j / heavy rerank / graph expand).
        "LA_NEO4J": "0",
        "LA_MEMORY_GRAPH": "0",
        "LA_MEMORY_RERANK": "0",
        # Avoid hanging on slow/unavailable Ollama embeddings during ingest/search.
        "LA_MEM0_EMBEDDER_PROVIDER": "hash",
    }


@pytest.fixture
def la_env_pending(la_env: dict[str, str]) -> dict[str, str]:
    """Same isolation as la_env, but Warm writes require pending approve/reject."""
    return {
        **la_env,
        "LA_MEMORY_APPROVAL_AUTO": "0",
        "LA_MEMORY_APPROVAL_REQUIRED": "1",
    }
