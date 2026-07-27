"""LoCoMo tiny fixture CI smoke with baseline tolerance."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TINY_FIXTURE = _REPO_ROOT / "benchmarks" / "locomo" / "fixtures" / "tiny.json"
_DEFAULT_BASELINE = _REPO_ROOT / "benchmarks" / "locomo" / "baseline_tiny.json"
_DEFAULT_TOLERANCE = 0.02


def _configure_ci_env() -> None:
    os.environ.setdefault("LA_MEMORY_BACKEND", "json")
    os.environ.setdefault("LA_MEM0_EMBEDDER_PROVIDER", "hash")
    os.environ.setdefault("LA_INGEST_USE_LLM", "0")
    os.environ.setdefault("LA_NEO4J", "0")
    os.environ.setdefault("LA_MEMORY_GRAPH", "0")
    os.environ.setdefault("LA_MEMORY_RERANK", "0")


def run_tiny_smoke(*, work_dir: Path | None = None) -> dict[str, Any]:
    _configure_ci_env()
    if str(_REPO_ROOT / "src") not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT / "src"))
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

    from benchmarks.locomo.dataset import filter_samples, load_samples
    from benchmarks.locomo.measure_recall import measure_sample

    samples = filter_samples(load_samples(_TINY_FIXTURE), sample_ids=["conv-tiny"])
    if not samples:
        raise RuntimeError("conv-tiny sample missing from tiny.json")

    wd = work_dir or (_REPO_ROOT / "benchmarks" / "data" / "runs" / "locomo-ci-smoke")
    result = measure_sample(
        samples[0],
        work_dir=wd,
        top_k=8,
        max_questions=None,
        skip_ingest=False,
        mode="joint",
    )
    return result


def _load_baseline(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    overall = payload.get("overall") or payload
    return {
        "hit@1": float(overall["hit@1"]),
        "hit@5": float(overall["hit@5"]),
        "hit@8": float(overall["hit@8"]),
    }


def compare_to_baseline(
    overall: dict[str, Any],
    baseline: dict[str, float],
    *,
    tolerance: float,
) -> list[str]:
    errors: list[str] = []
    for key in ("hit@1", "hit@5", "hit@8"):
        got = float(overall[key])
        want = float(baseline[key])
        floor = want - tolerance
        if got + 1e-9 < floor:
            errors.append(f"{key} regressed: got={got:.4f} baseline={want:.4f} floor={floor:.4f}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LoCoMo tiny CI smoke")
    parser.add_argument("--baseline", type=Path, default=_DEFAULT_BASELINE)
    parser.add_argument("--tolerance", type=float, default=_DEFAULT_TOLERANCE)
    parser.add_argument("--write-baseline", action="store_true", help="Overwrite baseline from current run")
    parser.add_argument("--work-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    result = run_tiny_smoke(work_dir=args.work_dir)
    overall = result["overall"]
    print(
        f"[locomo-ci-smoke] hit@1={overall['hit@1']} "
        f"hit@5={overall['hit@5']} hit@8={overall['hit@8']} n={overall['n']}"
    )

    if args.write_baseline:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps({"overall": overall, "sample_id": result["sample_id"]}, indent=2),
            encoding="utf-8",
        )
        print(f"baseline → {args.baseline}")
        return 0

    if not args.baseline.is_file():
        print(f"[locomo-ci-smoke] baseline missing: {args.baseline}", file=sys.stderr)
        return 1

    baseline = _load_baseline(args.baseline)
    errors = compare_to_baseline(overall, baseline, tolerance=args.tolerance)
    if errors:
        for err in errors:
            print(f"[locomo-ci-smoke] FAIL {err}", file=sys.stderr)
        return 1
    print("[locomo-ci-smoke] PASS within tolerance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
