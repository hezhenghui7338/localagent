"""Generate PRD acceptance matrix coverage reports."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from benchmarks.prd.load_matrix import DEFAULT_MATRIX, iter_items, load_matrix, repo_root

CheckResult = dict[str, Any]


@dataclass
class ItemReport:
    item_id: str
    title: str
    prd_ref: str
    story: list[int]
    pillar: str
    coverage: str
    ci_tier: str
    critical: bool
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def status(self) -> str:
        if not self.checks:
            return "missing"
        required = [
            c
            for c in self.checks
            if c.get("type") not in ("manual", "e2e_live")
        ]
        if not required:
            required = self.checks
        failed = [c for c in required if c.get("status") == "fail"]
        missing = [c for c in required if c.get("status") == "missing"]
        if failed or missing:
            if self.coverage == "automated" and (failed or missing):
                return "fail"
            if missing and self.coverage != "automated":
                return "partial"
            return "partial"
        return "pass"


def _pytest_collect(nodeid: str, *, cwd: Path) -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-m",
            "",
            "-o",
            "addopts=",
            nodeid,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    name = nodeid.split("::")[-1]
    return name in proc.stdout or nodeid in proc.stdout


def _resolve_test_path(spec: str, *, root: Path) -> Path | None:
    path_part = spec.split("::", 1)[0]
    candidate = root / path_part
    if candidate.is_file():
        return candidate
    if (root / "tests" / path_part).is_file():
        return root / "tests" / path_part
    return None


def _check_test(spec: str, *, root: Path) -> CheckResult:
    path = _resolve_test_path(spec, root=root)
    if path is None:
        return {"type": "test", "ref": spec, "status": "missing", "detail": "file not found"}
    nodeid = spec if "::" in spec else str(path.relative_to(root)).replace("\\", "/")
    if _pytest_collect(nodeid, cwd=root):
        return {"type": "test", "ref": nodeid, "status": "pass"}
    return {"type": "test", "ref": nodeid, "status": "missing", "detail": "pytest collect failed"}


def _check_script(script: str) -> CheckResult:
    return {"type": "benchmark", "ref": script, "status": "pass", "detail": "declared script"}


def _check_manual(ref: str) -> CheckResult:
    root = repo_root()
    rel = ref.split("#", 1)[0]
    path = root / rel
    if path.is_file():
        return {"type": "manual", "ref": ref, "status": "pass", "detail": "manual checklist linked"}
    return {"type": "manual", "ref": ref, "status": "missing", "detail": "manual doc missing"}


def _evaluate_checks(raw: dict[str, Any], *, root: Path) -> list[CheckResult]:
    checks: list[CheckResult] = []
    for check in raw.get("checks") or []:
        ctype = str(check.get("type") or "")
        if ctype in ("e2e", "e2e_live", "unit") and check.get("test"):
            checks.append(_check_test(str(check["test"]), root=root))
        elif ctype == "benchmark" and check.get("test"):
            checks.append(_check_test(str(check["test"]), root=root))
        elif ctype == "benchmark" and check.get("script"):
            checks.append(_check_script(str(check["script"])))
        elif ctype == "manual":
            checks.append(_check_manual(str(check.get("ref") or "")))
        else:
            checks.append(
                {
                    "type": ctype or "unknown",
                    "ref": str(check),
                    "status": "missing",
                    "detail": "unsupported check",
                }
            )
    return checks


def evaluate_item(raw: dict[str, Any], *, root: Path) -> ItemReport:
    checks = _evaluate_checks(raw, root=root)
    return ItemReport(
        item_id=str(raw["id"]),
        title=str(raw.get("title") or raw["id"]),
        prd_ref=str(raw.get("prd_ref") or ""),
        story=[int(s) for s in (raw.get("story") or [])],
        pillar=str(raw.get("pillar") or ""),
        coverage=str(raw.get("coverage") or "partial"),
        ci_tier=str(raw.get("ci_tier") or "pr"),
        critical=bool(raw.get("critical")),
        checks=checks,
    )


def evaluate_matrix(matrix: dict[str, Any] | None = None, *, matrix_path: Path | None = None) -> list[ItemReport]:
    data = matrix or load_matrix(matrix_path)
    root = repo_root()
    return [evaluate_item(item, root=root) for item in iter_items(data)]


def summarize(reports: list[ItemReport]) -> dict[str, Any]:
    coverage_counts = Counter(r.coverage for r in reports)
    status_counts = Counter(r.status for r in reports)
    critical_fail = [r for r in reports if r.critical and r.status in ("fail", "missing")]
    return {
        "total": len(reports),
        "coverage": dict(coverage_counts),
        "status": dict(status_counts),
        "critical_failures": [r.item_id for r in critical_fail],
    }


def render_markdown(reports: list[ItemReport], *, summary: dict[str, Any]) -> str:
    lines = [
        "# LocalAgent PRD Acceptance Matrix Report",
        "",
        f"> Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "## Summary",
        "",
        f"- Items: **{summary['total']}**",
        f"- Coverage: {summary['coverage']}",
        f"- Status: {summary['status']}",
        "",
    ]
    if summary["critical_failures"]:
        lines.append(f"- **Critical failures:** {', '.join(summary['critical_failures'])}")
        lines.append("")

    lines.extend(["## Items", "", "| ID | § | Stories | Coverage | Status | Title |", "|---|---|---|---|---|---|"])
    for r in reports:
        stories = ",".join(str(s) for s in r.story)
        lines.append(
            f"| `{r.item_id}` | {r.prd_ref} | {stories} | {r.coverage} | {r.status} | {r.title} |"
        )

    lines.extend(["", "## Check details", ""])
    for r in reports:
        lines.append(f"### {r.item_id} — {r.title}")
        lines.append("")
        for c in r.checks:
            detail = c.get("detail") or ""
            lines.append(f"- [{c.get('status')}] `{c.get('type')}` {c.get('ref')} {detail}".rstrip())
        lines.append("")

    manual = [
        "- [ ] **故事 1–3**：安装 + 配置 + chat Hello",
        "- [ ] **故事 4**：跨 session 召回",
        "- [ ] **故事 5–6**：ChatGPT 导入 + rag search",
        "- [ ] **记忆确认门**：pending approve/reject",
        "- [ ] **故事 7**：web_search 带来源",
        "- [ ] **故事 8–9**：Shell/写文件确认 + 危险拦截",
        "- [ ] **故事 10**：audit token/费用 + HTML",
        "- [ ] **故事 6b–6e**：summarize / OCR / news / polish / aware",
        "",
        "完整清单见 [examples/product-tour.zh-CN.md](../examples/product-tour.zh-CN.md#验收清单)",
    ]
    lines.extend(["## Manual release checklist (L3)", ""] + manual)
    return "\n".join(lines) + "\n"


def render_prd_mapping_section(reports: list[ItemReport]) -> str:
    lines = [
        "## PRD §6 ↔ E2E 映射（三支柱）",
        "",
        "> **自动生成** — 源文件 [`docs/acceptance-matrix.yaml`](../docs/acceptance-matrix.yaml)；"
        "运行 `python -m benchmarks.prd.report_matrix --sync-catalog` 刷新本段。",
        "",
        "| 验收项 | 主要自动化 | 状态 |",
        "|--------|------------|------|",
    ]
    for r in reports:
        auto = []
        for c in r.checks:
            if c.get("type") in ("test", "benchmark") and c.get("status") == "pass":
                auto.append(str(c.get("ref", "")).split("::")[-1][:48])
        label = auto[0] if auto else ("manual" if r.coverage == "manual" else "partial")
        status = "✅" if r.status == "pass" else ("⚠️ partial" if r.status == "partial" else "❌")
        lines.append(f"| **{r.prd_ref}** {r.title[:40]} | `{label}` | {status} |")
    lines.append("")
    return "\n".join(lines)


def sync_test_catalog(reports: list[ItemReport], *, catalog_path: Path) -> None:
    section = render_prd_mapping_section(reports)
    text = catalog_path.read_text(encoding="utf-8")
    start = "## PRD §6 ↔ E2E 映射（三支柱）"
    end = "## E2E 核心命令覆盖"
    if start not in text or end not in text:
        raise RuntimeError("test-catalog-review.md markers not found")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    catalog_path.write_text(head + section + end + tail, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRD acceptance matrix report")
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--out", type=Path, default=None, help="Write Markdown report")
    parser.add_argument(
        "--fail-on-critical",
        action="store_true",
        help="Exit 1 when critical automated checks are missing/failing",
    )
    parser.add_argument(
        "--sync-catalog",
        action="store_true",
        help="Replace PRD mapping section in docs/test-catalog-review.md",
    )
    args = parser.parse_args(argv)

    reports = evaluate_matrix(matrix_path=args.matrix)
    summary = summarize(reports)
    md = render_markdown(reports, summary=summary)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(md, encoding="utf-8")
        print(f"report → {args.out}")
    else:
        print(md)

    if args.sync_catalog:
        sync_test_catalog(reports, catalog_path=repo_root() / "docs" / "test-catalog-review.md")
        print("synced docs/test-catalog-review.md PRD mapping section")

    if args.fail_on_critical and summary["critical_failures"]:
        print(f"critical failures: {summary['critical_failures']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
