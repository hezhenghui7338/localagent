"""Compare two LoCoMo recall JSON reports (before/after Cold rerank)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _overall(report: dict[str, Any]) -> dict[str, Any]:
    if "overall" in report:
        return report["overall"]
    if isinstance(report.get("results"), list) and report["results"]:
        return report["results"][0].get("overall") or {}
    return {}


def _fmt_delta(before: float, after: float) -> str:
    delta = after - before
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.4f}"


def compare_reports(before: dict[str, Any], after: dict[str, Any]) -> str:
    b = _overall(before)
    a = _overall(after)
    lines = [
        "LoCoMo recall comparison",
        f"  before n={b.get('n', '?')}  after n={a.get('n', '?')}",
        "",
        "  metric    before    after     delta",
    ]
    for key in ("hit@1", "hit@5", "hit@8"):
        bv = float(b.get(key) or 0.0)
        av = float(a.get(key) or 0.0)
        lines.append(
            f"  {key:<8}  {bv:.4f}    {av:.4f}    {_fmt_delta(bv, av)}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare LoCoMo recall JSON reports")
    parser.add_argument("before", type=Path, help="baseline report JSON")
    parser.add_argument("after", type=Path, help="candidate report JSON")
    args = parser.parse_args(argv)

    if not args.before.exists():
        print(f"missing: {args.before}", file=sys.stderr)
        return 1
    if not args.after.exists():
        print(f"missing: {args.after}", file=sys.stderr)
        return 1

    before = _load_report(args.before)
    after = _load_report(args.after)
    print(compare_reports(before, after))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
