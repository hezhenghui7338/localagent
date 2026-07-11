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
    return {
        "LA_DATA_DIR": str(la_data_dir),
        "LA_INGEST_USE_LLM": "0",
    }
