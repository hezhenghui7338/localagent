"""Unified version evaluation report (PRD matrix + benchmarks + eval)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_capture(cmd: list[str], *, env: dict[str, str] | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def _section_matrix() -> dict[str, Any]:
    from benchmarks.prd.report_matrix import evaluate_matrix, summarize

    reports = evaluate_matrix()
    summary = summarize(reports)
    return {"summary": summary, "items": len(reports)}


def _section_locomo_smoke() -> dict[str, Any]:
    rc, out = _run_capture([sys.executable, "-m", "benchmarks.locomo.ci_smoke"])
    return {"pass": rc == 0, "output": out.strip()[-2000:]}


def _section_eval(tier: str) -> dict[str, Any]:
    rc, out = _run_capture(
        [sys.executable, "-m", "benchmarks.eval", "run", "--tier", tier],
        env={"LA_EVAL_SKIP_JUDGE": "1"},
    )
    return {"tier": tier, "pass": rc == 0, "output": out.strip()[-2000:]}


def _section_stm() -> dict[str, Any]:
    rc, out = _run_capture(
        [sys.executable, "-m", "pytest", "tests/test_stm_benchmark.py", "-q", "-n0"],
    )
    return {"pass": rc == 0, "output": out.strip()[-1500:]}


def build_report(*, tier: str = "release") -> dict[str, Any]:
    eval_tier = "smoke" if tier in ("pr", "release") else "full"
    sections = {
        "matrix": _section_matrix(),
        "stm": _section_stm(),
        "locomo_smoke": _section_locomo_smoke(),
        "eval": _section_eval(eval_tier),
    }
    critical = sections["matrix"]["summary"].get("critical_failures") or []
    lights = []
    if sections["stm"]["pass"]:
        lights.append("stm")
    if sections["locomo_smoke"]["pass"]:
        lights.append("locomo")
    if sections["eval"]["pass"]:
        lights.append("eval")
    if not critical:
        lights.append("matrix-critical")

    overall = "green"
    if critical or not sections["locomo_smoke"]["pass"]:
        overall = "red"
    elif not sections["eval"]["pass"] or sections["matrix"]["summary"].get("status", {}).get("partial"):
        overall = "yellow"

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tier": tier,
        "overall": overall,
        "lights": lights,
        "sections": sections,
        "manual_checklist": "examples/product-tour.zh-CN.md#验收清单",
        "known_gaps": [
            "CI uses json backend + hash embedder (no live Mem0/rerank/Neo4j)",
            "LLM judge skipped unless LA_EVAL_JUDGE_PROVIDER + API key set",
            "Polish live quality requires manual product-tour sign-off",
        ],
    }


def render_html(report: dict[str, Any]) -> str:
    overall = report["overall"]
    color = {"green": "#2e7d32", "yellow": "#f9a825", "red": "#c62828"}.get(overall, "#333")
    sections_json = json.dumps(report["sections"], ensure_ascii=False, indent=2)
    gaps = "".join(f"<li>{g}</li>" for g in report.get("known_gaps") or [])
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <title>LocalAgent Eval Report</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.5; }}
    .badge {{ display: inline-block; padding: 0.25rem 0.75rem; border-radius: 4px;
              color: #fff; background: {color}; font-weight: 600; }}
    pre {{ background: #f5f5f5; padding: 1rem; overflow: auto; }}
  </style>
</head>
<body>
  <h1>LocalAgent 版本评估报告</h1>
  <p>生成时间：{report["generated_at"]} · Tier: {report["tier"]}
     · 总评：<span class="badge">{overall}</span></p>
  <h2>人工签收</h2>
  <p>发版前请完成
    <a href="{report["manual_checklist"]}">product-tour 验收清单</a>（L3）。</p>
  <h2>已知 CI 降级项</h2>
  <ul>{gaps}</ul>
  <h2>各层结果</h2>
  <pre>{sections_json}</pre>
</body>
</html>
"""


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# LocalAgent 版本评估报告",
        "",
        f"- 生成: {report['generated_at']}",
        f"- Tier: `{report['tier']}`",
        f"- 总评: **{report['overall']}**",
        "",
        "## Executive summary",
        "",
        f"- 绿灯: {', '.join(report.get('lights') or []) or 'none'}",
        "",
        "## PRD matrix",
        "",
        f"- critical failures: {report['sections']['matrix']['summary'].get('critical_failures')}",
        f"- coverage: {report['sections']['matrix']['summary'].get('coverage')}",
        "",
        "## STM",
        "",
        f"- pass: {report['sections']['stm']['pass']}",
        "",
        "## LoCoMo tiny smoke",
        "",
        f"- pass: {report['sections']['locomo_smoke']['pass']}",
        "",
        "## Scenario eval",
        "",
        f"- pass: {report['sections']['eval']['pass']} (tier={report['sections']['eval']['tier']})",
        "",
        "## Manual release checklist (L3)",
        "",
        f"见 [{report['manual_checklist']}]({report['manual_checklist']})",
        "",
        "## Known gaps",
        "",
    ]
    for gap in report.get("known_gaps") or []:
        lines.append(f"- {gap}")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unified LocalAgent eval report")
    parser.add_argument("--tier", default="release", choices=["pr", "release", "nightly"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--format", choices=["html", "md", "json"], default="html")
    args = parser.parse_args(argv)

    report = build_report(tier=args.tier)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    elif args.format == "md":
        args.out.write_text(render_markdown(report), encoding="utf-8")
    else:
        args.out.write_text(render_html(report), encoding="utf-8")
    print(f"eval report → {args.out} (overall={report['overall']})")
    return 0 if report["overall"] != "red" else 1


if __name__ == "__main__":
    raise SystemExit(main())
