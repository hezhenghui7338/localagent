"""Measure LocalAgent memory recall against LoCoMo evidence dialogs.

Primary regression signal for long-term memory quality:
ingest → joint Warm∪Cold recall(question) → evidence hit@k.

Diagnostic modes: ``warm_only`` / ``cold_only`` (attribution only).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.locomo.dataset import DEFAULT_DATA_PATH, filter_samples, load_samples
from benchmarks.locomo.ingest import ingest_sample
from benchmarks.locomo.runtime import configure_data_dir

RecallMode = Literal["joint", "warm_only", "cold_only"]


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


def _aggregate_rows(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    by_cat: dict[int, dict[str, float]] = defaultdict(
        lambda: {"n": 0, "hit1": 0, "hit5": 0, "hit8": 0}
    )
    for row in rows:
        cat = int(row["category"])
        by_cat[cat]["n"] += 1
        by_cat[cat]["hit1"] += float(row["hit@1"])
        by_cat[cat]["hit5"] += float(row["hit@5"])
        by_cat[cat]["hit8"] += float(row["hit@8"])

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
    return overall, categories


def _score_questions(
    sample: dict[str, Any],
    *,
    top_k: int,
    max_questions: int | None,
    mode: RecallMode,
) -> list[dict[str, Any]]:
    from benchmarks.locomo.answer import joint_recall

    rows: list[dict[str, Any]] = []
    counted = 0
    for qa in sample.get("qa") or []:
        cat = int(qa.get("category"))
        if cat == 5:
            continue
        evidence = _normalize_evidence(list(qa.get("evidence") or []))
        if not evidence:
            continue
        hits = joint_recall(str(qa.get("question") or ""), top_k=top_k, mode=mode)
        dias = [
            str((h.get("metadata") or {}).get("dia_id") or "").strip()
            for h in hits
            if str((h.get("metadata") or {}).get("dia_id") or "").strip()
        ]
        row = {
            "question": qa.get("question"),
            "category": cat,
            "evidence": evidence,
            "retrieved_dia_ids": dias,
            "hit@1": _hit_at_k(dias, evidence, 1),
            "hit@5": _hit_at_k(dias, evidence, 5),
            "hit@8": _hit_at_k(dias, evidence, min(8, top_k)),
            "mode": mode,
        }
        rows.append(row)
        counted += 1
        if max_questions is not None and counted >= max_questions:
            break
    return rows


def _ensure_graphs_ready() -> None:
    from localagent import config

    if config.MEMORY_GRAPH:
        from localagent.memory.graph import get_memory_graph, rebuild_memory_graph

        stats = get_memory_graph().stats()
        if stats.get("facts", 0) == 0:
            rebuilt = rebuild_memory_graph()
            print(
                f"[locomo-recall] memory graph rebuilt: "
                f"entities={rebuilt['entities']} relations={rebuilt['relations']} "
                f"facts={rebuilt['facts']}"
            )
        else:
            print(
                f"[locomo-recall] memory graph ready: "
                f"entities={stats['entities']} relations={stats['relations']} "
                f"facts={stats['facts']}"
            )
    if getattr(config, "NEO4J", False):
        from localagent.memory.graph import (
            get_neo4j_store,
            neo4j_available,
            rebuild_neo4j_graph,
            reset_neo4j_store_singleton,
        )

        reset_neo4j_store_singleton()
        if not neo4j_available():
            print("[locomo-recall] LA_NEO4J=1 but Neo4j unavailable; skip neo4j rebuild")
        else:
            rebuilt = rebuild_neo4j_graph()
            print(
                f"[locomo-recall] neo4j graph rebuilt: "
                f"entities={rebuilt['entities']} relations={rebuilt['relations']} "
                f"facts={rebuilt['facts']} uri={config.NEO4J_URI}"
            )
            _ = get_neo4j_store().stats()


def measure_sample(
    sample: dict[str, Any],
    *,
    work_dir: Path,
    top_k: int,
    max_questions: int | None,
    skip_ingest: bool,
    mode: RecallMode = "joint",
    diagnostics: bool = False,
    incremental_sessions: bool = False,
) -> dict[str, Any]:
    sample_id = str(sample["sample_id"])
    configure_data_dir(work_dir / sample_id)

    if not skip_ingest:
        ingest_info = ingest_sample(
            sample,
            incremental_sessions=incremental_sessions,
        )
    else:
        from localagent.memory.backend import get_memory_backend

        backend = get_memory_backend()
        ingest_info = {
            "sample_id": sample_id,
            "backend": backend.backend_name(),
            "skipped_ingest": True,
            "memory_count": backend.count(),
        }

    _ensure_graphs_ready()

    primary_rows = _score_questions(
        sample,
        top_k=top_k,
        max_questions=max_questions,
        mode=mode,
    )
    overall, categories = _aggregate_rows(primary_rows)
    result: dict[str, Any] = {
        "sample_id": sample_id,
        "mode": mode,
        "ingest": ingest_info,
        "overall": overall,
        "categories": categories,
        "qa": primary_rows,
    }

    if diagnostics:
        diag: dict[str, Any] = {}
        for diag_mode in ("warm_only", "cold_only", "joint"):
            if diag_mode == mode:
                diag[diag_mode] = {"overall": overall, "categories": categories}
                continue
            rows = _score_questions(
                sample,
                top_k=top_k,
                max_questions=max_questions,
                mode=diag_mode,  # type: ignore[arg-type]
            )
            o, c = _aggregate_rows(rows)
            diag[diag_mode] = {"overall": o, "categories": c}
        result["diagnostics"] = diag
    return result


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
    parser.add_argument(
        "--mode",
        choices=("joint", "warm_only", "cold_only"),
        default="joint",
        help="joint=Warm∪Cold RRF (default/primary); warm_only/cold_only=diagnostics",
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Also score warm_only / cold_only / joint for attribution",
    )
    parser.add_argument(
        "--incremental-sessions",
        action="store_true",
        help="Ingest session-by-session (timeline-realistic retain)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="结果 JSON 路径；默认写带时间戳的新文件，避免覆盖历史产物",
    )
    parser.add_argument(
        "--label",
        default="",
        help="写入默认文件名：recall_hitk_YYYYMMDD_HHMMSS[_label].json",
    )
    args = parser.parse_args(argv)

    samples = filter_samples(load_samples(args.data_file), sample_ids=args.sample_ids)
    if not samples:
        print("[locomo-recall] no samples")
        return 1

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
            mode=args.mode,
            diagnostics=args.diagnostics,
            incremental_sessions=args.incremental_sessions,
        )
        results.append(result)
        o = result["overall"]
        print(
            f"[locomo-recall] {result['sample_id']} mode={result['mode']} "
            f"hit@1={o['hit@1']} hit@5={o['hit@5']} hit@8={o['hit@8']} n={o['n']}"
        )
        for cat, info in result["categories"].items():
            print(
                f"  cat{cat}: n={info['n']} "
                f"hit@1={info['hit@1']} hit@5={info['hit@5']} hit@8={info['hit@8']}"
            )
        if result.get("diagnostics"):
            for diag_mode, block in result["diagnostics"].items():
                d = block["overall"]
                print(
                    f"  diag[{diag_mode}]: "
                    f"hit@1={d['hit@1']} hit@5={d['hit@5']} hit@8={d['hit@8']}"
                )

    if args.out is not None:
        out = args.out
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        label = re.sub(r"[^\w\-]+", "_", (args.label or "").strip()).strip("_")
        name = f"recall_hitk_{stamp}_{label}.json" if label else f"recall_hitk_{stamp}.json"
        out = args.work_dir / name
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "label": (args.label or "").strip() or None,
        "mode": args.mode,
        "diagnostics": bool(args.diagnostics),
        "results": results,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"results → {out}")
    print("提示: 请将本次分表追加到 benchmarks/locomo/HISTORY.md（勿覆盖旧节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
