"""Hot-layer (core_profile) auxiliary track for LTM eval.

Pins identity fields into ``core_profile.json`` and checks they survive reload.
Not part of evidence hit@k — reported separately as Profile Field Hit.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.locomo.runtime import configure_data_dir

DEFAULT_CASES: list[dict[str, Any]] = [
    {
        "id": "hot-alice",
        "pins": {
            "name": "Alice",
            "preferences": {"宠物": "Sunny", "居住地": "Seattle"},
        },
    },
    {
        "id": "hot-zh-user",
        "pins": {
            "name": "测试用户",
            "preferences": {"饮品": "绿茶", "居住地": "杭州"},
        },
    },
]


def measure_profile_cases(
    cases: list[dict[str, Any]],
    *,
    work_dir: Path,
) -> dict[str, Any]:
    from localagent.memory.core_profile import CoreProfile, load_core_profile, save_core_profile

    rows: list[dict[str, Any]] = []
    hits = 0
    for case in cases:
        case_dir = work_dir / str(case.get("id") or "hot")
        configure_data_dir(case_dir)
        pins = case.get("pins") or {}
        expect = case.get("expect") or pins
        profile = CoreProfile(
            name=str(pins.get("name") or ""),
            preferences={str(k): str(v) for k, v in dict(pins.get("preferences") or {}).items()},
            updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        save_core_profile(profile)
        loaded = load_core_profile()
        name_ok = loaded.name == str(expect.get("name") or "")
        pref_expect = {str(k): str(v) for k, v in dict(expect.get("preferences") or {}).items()}
        pref_ok = all(loaded.preferences.get(k) == v for k, v in pref_expect.items())
        ok = name_ok and pref_ok
        if ok:
            hits += 1
        rows.append(
            {
                "id": case.get("id"),
                "profile_hit": ok,
                "name_ok": name_ok,
                "preferences_ok": pref_ok,
            }
        )
    n = len(cases) or 1
    return {
        "overall": {
            "n": len(cases),
            "profile_field_hit": round(hits / n, 4),
        },
        "cases": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hot profile field-hit auxiliary track")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=_REPO_ROOT / "benchmarks" / "data" / "runs" / "locomo-profile",
    )
    parser.add_argument("--cases", type=Path, default=None, help="Optional JSON list of pin cases")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.cases is not None:
        cases = json.loads(args.cases.read_text(encoding="utf-8"))
        if isinstance(cases, dict):
            cases = list(cases.get("hot_profile") or cases.get("cases") or [])
    else:
        cases = DEFAULT_CASES

    result = measure_profile_cases(cases, work_dir=args.work_dir / "cases")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = args.out or (args.work_dir / f"profile_hit_{stamp}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "benchmark": "LTM-Hot",
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        **result,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    o = result["overall"]
    print(f"[locomo-profile] profile_field_hit={o['profile_field_hit']} n={o['n']}")
    print(f"results → {out}")
    return 0 if o["profile_field_hit"] >= 0.9 else 1


if __name__ == "__main__":
    raise SystemExit(main())
