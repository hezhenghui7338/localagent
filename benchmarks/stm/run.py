"""CLI: short-term memory benchmark (routing / in-session / same-day / priority)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.stm.metrics import THRESHOLDS, summarize_stm
from benchmarks.stm.scenarios import DEFAULT_FIXTURE, load_cases, run_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LocalAgent short-term memory (STM) benchmark")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=_REPO_ROOT / "benchmarks" / "data" / "runs" / "stm",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    cases = load_cases(args.fixture)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = args.work_dir / stamp
    detail = run_all(cases, work_dir=run_dir)
    summary = summarize_stm(detail)

    payload = {
        "benchmark": "STM",
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "thresholds": THRESHOLDS,
        "summary": summary,
        "detail": detail,
    }
    out = args.out or (args.work_dir / f"stm_{stamp}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[stm] short-term memory benchmark")
    for key in (
        "routing_accuracy",
        "in_session_coverage",
        "in_session_answer_hit",
        "session_hit",
        "priority_win_rate",
        "hot_profile_hit",
    ):
        gate = summary.get("gates", {}).get(key)
        marker = ""
        if gate is True:
            marker = " PASS"
        elif gate is False:
            marker = " FAIL"
        print(f"  {key}={summary.get(key)}{marker}")
    print(f"  passed={summary.get('passed')}")
    print(f"results → {out}")
    return 0 if summary.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
