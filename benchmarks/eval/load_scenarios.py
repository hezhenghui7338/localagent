"""Load scenario YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCENARIOS_ROOT = _REPO_ROOT / "benchmarks" / "eval" / "scenarios"


def scenarios_dir(tier: str) -> Path:
    if tier == "smoke":
        return _SCENARIOS_ROOT / "smoke"
    if tier == "full":
        return _SCENARIOS_ROOT / "full"
    raise ValueError(f"unknown tier: {tier}")


def load_scenarios(tier: str) -> list[dict[str, Any]]:
    root = scenarios_dir(tier)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("_file", str(path.relative_to(_REPO_ROOT)))
            out.append(data)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    item.setdefault("_file", str(path.relative_to(_REPO_ROOT)))
                    out.append(item)
    return out
