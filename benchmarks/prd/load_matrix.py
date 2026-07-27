"""Load and validate docs/acceptance-matrix.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATRIX = _REPO_ROOT / "docs" / "acceptance-matrix.yaml"


def repo_root() -> Path:
    return _REPO_ROOT


def load_matrix(path: Path | None = None) -> dict[str, Any]:
    matrix_path = path or DEFAULT_MATRIX
    raw = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"invalid matrix: {matrix_path}")
    items = raw.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError(f"matrix has no items: {matrix_path}")
    return raw


def iter_items(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    return list(matrix.get("items") or [])
