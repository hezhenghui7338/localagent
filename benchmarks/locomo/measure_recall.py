"""Measure LocalAgent memory recall against LoCoMo evidence dialogs.

This is the primary regression signal for long-term memory quality:
ingest conversation turns → recall(question) → evidence hit@k.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.locomo.dataset import DEFAULT_DATA_PATH, filter_samples, load_samples
from benchmarks.locomo.ingest import ingest_sample
from benchmarks.locomo.runtime import configure_data_dir


def _hit_at_k(retrieved: list[str], evidence: list[str], k: int) -> bool:
    if not evidence:
        return False
    top = set(retrieved[:k])
    return any(item in top for item in evidence)


def _normalize_evidence(evidence: list[Any]) -> list[str]:
    """Split LoCoMo evidence cells that sometimes pack multiple dia_ids."""
    out: list[str] = []
    for item in evidence:
        for part in re.split(r"[;,]", str(item)):
            dia = part.strip()
            if dia:
                out.append(dia)
    return out


def measure_sample(
    sample: dict[str, Any],
    *,
    work_dir: Path,
    top_k: int,
    max_questions: int | None,
    skip_ingest: bool,
) -> dict[str, Any]:
    sample_id = str(sample["sample_id"])
    configure_data_dir(work_dir / sample_id)

    if not skip_ingest:
        ingest_info = ingest_sample(sample)
    else:
        from localagent.memory.backend import get_memory_backend

        backend = get_memory_backend()
        ingest_info = {
            "sample_id": sample_id,
            "backend": backend.backend_name(),
            "skipped_ingest": True,
            "memory_count": backend.count(),
        }

    from localagent.memory.backend import get_memory_backend

    backend = get_memory_backend()
    by_cat: dict[int, dict[str, float]] = defaultdict(
        lambda: {"n": 0, "hit1": 0, "hit5": 0, "hit8": 0}
    )
    rows: list[dict[str, Any]] = []
    counted = 0
    for qa in sample.get("qa") or []:
        cat = int(qa.get("category"))
        if cat == 5:
            continue
        evidence = _normalize_evidence(list(qa.get("evidence") or []))
        if not evidence:
            continue
        hits = backend.recall(str(qa.get("question") or ""), max_results=top_k)
        dias = [str((h.get("metadata") or {}).get("dia_id") or "") for h in hits]
        row = {
            "question": qa.get("question"),
            "category": cat,
            "evidence": evidence,
            "retrieved_dia_ids": dias,
            "hit@1": _hit_at_k(dias, evidence, 1),
            "hit@5": _hit_at_k(dias, evidence, 5),
            "hit@8": _hit_at_k(dias, evidence, min(8, top_k)),
        }
        rows.append(row)
        by_cat[cat]["n"] += 1
        by_cat[cat]["hit1"] += float(row["hit@1"])
        by_cat[cat]["hit5"] += float(row["hit@5"])
        by_cat[cat]["hit8"] += float(row["hit@8"])
        counted += 1
        if max_questions is not None and counted >= max_questions:
            break

    categories: dict[str, Any] = {}
    totals = {"n": 0, "hit1": 0.0, "hit5": 0.0, "hit8": 0.0}
    for cat in sorted(by_cat):
        stats = by_cat[cat]
        n = int(stats["n"]) or 1
        categories[str(cat)] = {
            "n": int(stats["n"]),
            "hit@1": round(stats["hit1"] / n, 4),
            "hit@5": round(stats["hit5"] / n, 4),
            "hit@8": round(stats["hit8"] / n, 4),
        }
        totals["n"] += int(stats["n"])
        totals["hit1"] += stats["hit1"]
        totals["hit5"] += stats["hit5"]
        totals["hit8"] += stats["hit8"]
    n = int(totals["n"]) or 1
    overall = {
        "n": int(totals["n"]),
        "hit@1": round(totals["hit1"] / n, 4),
        "hit@5": round(totals["hit5"] / n, 4),
        "hit@8": round(totals["hit8"] / n, 4),
    }
    return {
        "sample_id": sample_id,
        "ingest": ingest_info,
        "overall": overall,
        "categories": categories,
        "qa": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LoCoMo evidence hit@k for LA memory recall")
    parser.add_argument("--data-file", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=_REPO_ROOT / "benchmarks" / "data" / "runs" / "locomo-recall",
    )
    parser.add_argument("--sample-ids", nargs="*", default=["conv-26"])
    parser.add_argument("--max-questions", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--skip-ingest", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    samples = filter_samples(load_samples(args.data_file), sample_ids=args.sample_ids)
    if not samples:
        print("[locomo-recall] no samples")
        return 1

    # Reuse existing cursor bank if present and skip-ingest requested with default ids.
    results = []
    for sample in samples:
        sample_id = str(sample["sample_id"])
        existing = (
            _REPO_ROOT / "benchmarks" / "data" / "runs" / "locomo-cursor" / sample_id
        )
        work_dir = args.work_dir
        skip = args.skip_ingest
        if skip and not (work_dir / sample_id / "memory_store.json").exists() and existing.exists():
            work_dir = existing.parent
            print(f"[locomo-recall] reuse bank {existing}")
        result = measure_sample(
            sample,
            work_dir=work_dir,
            top_k=args.top_k,
            max_questions=args.max_questions,
            skip_ingest=skip,
        )
        results.append(result)
        o = result["overall"]
        print(
            f"[locomo-recall] {result['sample_id']} "
            f"hit@1={o['hit@1']} hit@5={o['hit@5']} hit@8={o['hit@8']} n={o['n']}"
        )
        for cat, info in result["categories"].items():
            print(
                f"  cat{cat}: n={info['n']} "
                f"hit@1={info['hit@1']} hit@5={info['hit@5']} hit@8={info['hit@8']}"
            )

    out = args.out or (args.work_dir / "recall_hitk.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"results → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
