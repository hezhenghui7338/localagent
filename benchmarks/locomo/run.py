"""CLI: run LoCoMo long-term memory benchmark against LocalAgent."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# Allow `python -m benchmarks.locomo.run` from repo root without install.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmarks.locomo.answer import AnswerMode, answer_question
from benchmarks.locomo.dataset import (
    DEFAULT_DATA_PATH,
    download_locomo,
    filter_samples,
    load_samples,
)
from benchmarks.locomo.ingest import ingest_sample
from benchmarks.locomo.metrics import CATEGORY_NAMES, score_qa_item, summarize_scores
from benchmarks.locomo.runtime import configure_data_dir


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate LocalAgent long-term memory on the LoCoMo QA benchmark.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    dl = sub.add_parser("download", help="Download official locomo10.json")
    dl.add_argument("--dest", type=Path, default=DEFAULT_DATA_PATH)
    dl.add_argument("--force", action="store_true")

    run = sub.add_parser("run", help="Ingest conversations and evaluate QA")
    run.add_argument("--data-file", type=Path, default=DEFAULT_DATA_PATH)
    run.add_argument(
        "--work-dir",
        type=Path,
        default=_REPO_ROOT / "benchmarks" / "data" / "runs" / "locomo",
        help="Isolated LA_DATA_DIR parent (one subdir per conversation).",
    )
    run.add_argument("--out", type=Path, default=None, help="JSON results path")
    run.add_argument("--sample-ids", nargs="*", default=None, help="Subset of sample_id")
    run.add_argument("--max-samples", type=int, default=None)
    run.add_argument("--max-questions", type=int, default=None, help="Per-conversation QA cap")
    run.add_argument("--max-turns", type=int, default=None, help="Ingest only first N turns")
    run.add_argument(
        "--categories",
        nargs="*",
        type=int,
        default=None,
        help="Only evaluate these LoCoMo categories (1-5)",
    )
    run.add_argument(
        "--mode",
        choices=["recall", "recall_generate", "reflect"],
        default="recall_generate",
        help="Answering strategy",
    )
    run.add_argument(
        "--provider",
        default="auto",
        help="LLM provider for recall_generate (e.g. cursor, ollama, openrouter, auto)",
    )
    run.add_argument("--top-k", type=int, default=5)
    run.add_argument("--skip-ingest", action="store_true", help="Reuse existing work-dir memories")
    run.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def cmd_download(args: argparse.Namespace) -> int:
    path = download_locomo(dest=args.dest, force=args.force)
    print(f"[locomo] dataset ready: {path} ({path.stat().st_size} bytes)")
    return 0


def _select_questions(
    qa_list: list[dict[str, Any]],
    *,
    max_questions: int | None,
    categories: set[int] | None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for qa in qa_list:
        cat = int(qa.get("category"))
        if categories is not None and cat not in categories:
            continue
        selected.append(qa)
        if max_questions is not None and len(selected) >= max_questions:
            break
    return selected


def _evidence_recall(retrieved_dia_ids: list[str], evidence: list[Any]) -> float | None:
    gold = [str(e) for e in (evidence or []) if e]
    if not gold:
        return None
    retrieved = set(retrieved_dia_ids)
    hits = sum(1 for e in gold if e in retrieved)
    return hits / len(gold)


def evaluate_sample(
    sample: dict[str, Any],
    *,
    work_dir: Path,
    mode: AnswerMode,
    top_k: int,
    provider: str,
    max_questions: int | None,
    max_turns: int | None,
    categories: set[int] | None,
    skip_ingest: bool,
    quiet: bool,
) -> dict[str, Any]:
    sample_id = str(sample["sample_id"])
    data_dir = work_dir / sample_id
    configure_data_dir(data_dir)

    ingest_info: dict[str, Any]
    if skip_ingest:
        from localagent.memory.backend import get_memory_backend

        backend = get_memory_backend()
        ingest_info = {
            "sample_id": sample_id,
            "backend": backend.backend_name(),
            "skipped_ingest": True,
            "memory_count": backend.count(),
        }
    else:
        if not quiet:
            print(f"[locomo] ingest {sample_id} → {data_dir}")

        def _progress(done: int, total: int) -> None:
            if not quiet:
                print(f"  retain {done}/{total}", flush=True)

        ingest_info = ingest_sample(sample, max_turns=max_turns, on_progress=_progress)

    questions = _select_questions(
        list(sample.get("qa") or []),
        max_questions=max_questions,
        categories=categories,
    )
    rows: list[dict[str, Any]] = []
    for index, qa in enumerate(questions, start=1):
        question = str(qa.get("question") or "")
        category = int(qa.get("category"))
        answer = qa.get("answer")
        t0 = time.time()
        result = answer_question(
            question,
            category=category,
            mode=mode,
            top_k=top_k,
            provider=provider,
        )
        elapsed = time.time() - t0
        f1 = score_qa_item(category=category, prediction=result["prediction"], answer=answer)
        evidence = list(qa.get("evidence") or [])
        retrieval_recall = _evidence_recall(result.get("retrieved_dia_ids") or [], evidence)
        row = {
            "question": question,
            "answer": answer,
            "category": category,
            "category_name": CATEGORY_NAMES.get(category, str(category)),
            "evidence": evidence,
            "prediction": result["prediction"],
            "f1": round(f1, 4),
            "retrieval_recall": None if retrieval_recall is None else round(retrieval_recall, 4),
            "retrieved_dia_ids": result.get("retrieved_dia_ids") or [],
            "mode": result.get("mode"),
            "provider": result.get("provider"),
            "model": result.get("model"),
            "latency_s": round(elapsed, 3),
        }
        rows.append(row)
        if not quiet:
            used = result.get("provider") or provider
            print(
                f"  qa {index}/{len(questions)} cat={category} f1={row['f1']:.3f} "
                f"via={used} pred={row['prediction'][:60]!r}",
                flush=True,
            )

    summary = summarize_scores(rows)
    return {
        "sample_id": sample_id,
        "ingest": ingest_info,
        "mode": mode,
        "provider": provider,
        "top_k": top_k,
        "summary": summary,
        "qa": rows,
    }


def cmd_run(args: argparse.Namespace) -> int:
    data_file = args.data_file
    if not data_file.exists():
        print(f"[locomo] data file missing: {data_file}")
        print("[locomo] run: python -m benchmarks.locomo.run download")
        return 1

    samples = filter_samples(
        load_samples(data_file),
        sample_ids=args.sample_ids,
        max_samples=args.max_samples,
    )
    if not samples:
        print("[locomo] no samples selected")
        return 1

    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    categories = set(args.categories) if args.categories else None

    results: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    started = time.time()
    provider = str(args.provider or "auto").strip().lower()
    if not args.quiet:
        print(f"[locomo] provider={provider} mode={args.mode} samples={len(samples)}", flush=True)

    for sample in samples:
        result = evaluate_sample(
            sample,
            work_dir=work_dir,
            mode=args.mode,
            top_k=args.top_k,
            provider=provider,
            max_questions=args.max_questions,
            max_turns=args.max_turns,
            categories=categories,
            skip_ingest=args.skip_ingest,
            quiet=args.quiet,
        )
        results.append(result)
        all_rows.extend(result["qa"])
        if not args.quiet:
            s = result["summary"]
            print(
                f"[locomo] {result['sample_id']} overall_f1={s['overall_f1']} n={s['n']}",
                flush=True,
            )

    overall = summarize_scores(all_rows)
    payload = {
        "benchmark": "LoCoMo",
        "task": "question_answering",
        "mode": args.mode,
        "provider": provider,
        "top_k": args.top_k,
        "data_file": str(data_file),
        "work_dir": str(work_dir),
        "elapsed_s": round(time.time() - started, 2),
        "overall": overall,
        "samples": results,
    }

    out = args.out or (work_dir / f"results_{args.mode}_{provider}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n===== LoCoMo / LocalAgent =====")
    print(f"mode={args.mode}  provider={provider}  top_k={args.top_k}  n={overall['n']}")
    print(f"overall_f1={overall['overall_f1']}")
    for cat, info in overall["categories"].items():
        print(f"  cat {cat} ({info['name']}): n={info['n']} f1={info['f1']}")
    print(f"results → {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "download":
        return cmd_download(args)
    if args.command == "run":
        return cmd_run(args)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
