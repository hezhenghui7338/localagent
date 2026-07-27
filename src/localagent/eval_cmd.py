"""`la eval` CLI handlers."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _ensure_benchmarks_importable() -> None:
    try:
        import benchmarks  # noqa: F401
    except ModuleNotFoundError:
        root = Path(__file__).resolve().parents[2]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))


def cmd_eval(args: argparse.Namespace) -> int:
    _ensure_benchmarks_importable()
    action = getattr(args, "eval_action", None) or "report"
    if action == "report":
        return _cmd_eval_report(args)
    if action == "matrix":
        return _cmd_eval_matrix(args)
    if action == "scenarios":
        return _cmd_eval_scenarios(args)
    print(f"[eval] unknown action: {action}")
    return 1


def _cmd_eval_report(args: argparse.Namespace) -> int:
    from benchmarks.report import build_report, main as report_main, render_html, render_markdown

    out = Path(args.out)
    fmt = args.format
    if args.quick:
        report = build_report(tier=args.tier)
        out.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            import json

            out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        elif fmt == "md":
            out.write_text(render_markdown(report), encoding="utf-8")
        else:
            out.write_text(render_html(report), encoding="utf-8")
        print(f"[eval] report → {out} (overall={report['overall']})")
        return 0 if report["overall"] != "red" else 1

    argv = ["--tier", args.tier, "--out", str(out), "--format", fmt]
    return report_main(argv)


def _cmd_eval_matrix(args: argparse.Namespace) -> int:
    from benchmarks.prd.report_matrix import main as matrix_main

    argv: list[str] = []
    if args.out:
        argv.extend(["--out", str(args.out)])
    if args.fail_on_critical:
        argv.append("--fail-on-critical")
    if args.sync_catalog:
        argv.append("--sync-catalog")
    return matrix_main(argv)


def _cmd_eval_scenarios(args: argparse.Namespace) -> int:
    from benchmarks.eval.runners.run_scenarios import main as scenarios_main

    argv = ["run", "--tier", args.tier]
    if args.report:
        argv.extend(["--report", str(args.report)])
    return scenarios_main(argv)
