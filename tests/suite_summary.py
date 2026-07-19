"""Pytest suite summary: unit vs e2e, per-file pass counts + module blurb.

Keeps the fast xdist progress dots during the run; prints a structured
overview at the end so you can see what was exercised.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_OUTCOME_ATTR = {
    "passed": "passed",
    "failed": "failed",
    "error": "error",
    "skipped": "skipped",
    "xfailed": "xfailed",
    "xpassed": "xpassed",
}


@dataclass
class FileStats:
    passed: int = 0
    failed: int = 0
    error: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0
    failed_names: list[str] = field(default_factory=list)

    def add(self, outcome: str, short_name: str = "") -> None:
        attr = _OUTCOME_ATTR.get(outcome)
        if attr is None:
            return
        setattr(self, attr, getattr(self, attr) + 1)
        if outcome in {"failed", "error"} and short_name:
            self.failed_names.append(short_name)

    @property
    def total(self) -> int:
        return (
            self.passed
            + self.failed
            + self.error
            + self.skipped
            + self.xfailed
            + self.xpassed
        )

    def counts_text(self) -> str:
        parts: list[str] = []
        for label, n in (
            ("passed", self.passed),
            ("failed", self.failed),
            ("error", self.error),
            ("skipped", self.skipped),
            ("xfailed", self.xfailed),
            ("xpassed", self.xpassed),
        ):
            if n:
                parts.append(f"{n} {label}")
        return ", ".join(parts) if parts else "0"


def file_path_from_nodeid(nodeid: str) -> str:
    return nodeid.split("::", 1)[0].replace("\\", "/")


def suite_for(path: str) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("tests/e2e/") or "/tests/e2e/" in f"/{normalized}":
        return "e2e"
    return "unit"


def short_test_name(nodeid: str) -> str:
    parts = nodeid.split("::")
    return parts[-1] if len(parts) > 1 else nodeid


def first_doc_line(doc: str | None) -> str:
    if not doc:
        return ""
    for line in doc.strip().splitlines():
        text = line.strip()
        if text:
            return text
    return ""


def docstring_from_file(path: Path) -> str:
    """First module docstring line; works without importing (xdist-safe)."""
    try:
        source = path.read_text(encoding="utf-8")
        return first_doc_line(ast.get_docstring(ast.parse(source)))
    except (OSError, SyntaxError, UnicodeError, ValueError, TypeError):
        return ""


def truncate(text: str, width: int = 56) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def collect_file_stats(stats: dict[str, list[Any]]) -> dict[str, dict[str, FileStats]]:
    """Group terminalreporter.stats into suite → file → FileStats.

    Each nodeid contributes one outcome: call-phase wins; otherwise setup
    skip/fail (tests skipped before call never appear in call reports).
    """
    call_outcomes: dict[str, str] = {}
    setup_outcomes: dict[str, str] = {}

    for outcome in _OUTCOME_ATTR:
        for report in stats.get(outcome, []):
            nodeid = getattr(report, "nodeid", "") or ""
            if not nodeid:
                continue
            when = getattr(report, "when", "call")
            if when == "call":
                call_outcomes[nodeid] = outcome
            elif when == "setup" and outcome in {"skipped", "failed", "error"}:
                setup_outcomes[nodeid] = outcome

    final = dict(setup_outcomes)
    final.update(call_outcomes)

    by_suite: dict[str, dict[str, FileStats]] = {
        "unit": defaultdict(FileStats),
        "e2e": defaultdict(FileStats),
    }
    for nodeid, outcome in final.items():
        path = file_path_from_nodeid(nodeid)
        by_suite[suite_for(path)][path].add(outcome, short_test_name(nodeid))

    return {
        "unit": dict(by_suite["unit"]),
        "e2e": dict(by_suite["e2e"]),
    }


def _suite_totals(files: dict[str, FileStats]) -> FileStats:
    total = FileStats()
    for fs in files.values():
        total.passed += fs.passed
        total.failed += fs.failed
        total.error += fs.error
        total.skipped += fs.skipped
        total.xfailed += fs.xfailed
        total.xpassed += fs.xpassed
    return total


def format_suite_summary(
    by_suite: dict[str, dict[str, FileStats]],
    *,
    file_docs: dict[str, str] | None = None,
    doc_width: int = 56,
) -> list[str]:
    """Return printable lines for the suite summary (no trailing blank)."""
    file_docs = file_docs or {}
    lines: list[str] = []
    sections = (
        ("unit", "单元 / 集成 (unit)"),
        ("e2e", "端到端 (e2e)"),
    )

    any_files = any(by_suite.get(key) for key, _ in sections)
    if not any_files:
        return lines

    lines.append("测试套件汇总")
    lines.append("")

    grand = FileStats()
    file_count = 0

    for key, title in sections:
        files = by_suite.get(key) or {}
        if not files:
            continue
        sub = _suite_totals(files)
        grand.passed += sub.passed
        grand.failed += sub.failed
        grand.error += sub.error
        grand.skipped += sub.skipped
        grand.xfailed += sub.xfailed
        grand.xpassed += sub.xpassed
        file_count += len(files)

        n_files = len(files)
        lines.append(f"{title} · {sub.counts_text()} · {n_files} 个文件")
        path_width = max(len(p) for p in files) if files else 20
        path_width = min(max(path_width, 24), 48)

        for path in sorted(files):
            fs = files[path]
            counts = fs.counts_text()
            blurb = truncate(file_docs.get(path, ""), doc_width)
            row = f"  {path:<{path_width}}  {counts}"
            if blurb:
                row = f"{row}  · {blurb}"
            lines.append(row)
            for name in fs.failed_names[:8]:
                lines.append(f"    ✗ {name}")
            if len(fs.failed_names) > 8:
                lines.append(f"    … +{len(fs.failed_names) - 8} more")
        lines.append("")

    lines.append(f"合计 · {grand.counts_text()} · {file_count} 个文件")
    return lines


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("localagent")
    group.addoption(
        "--no-suite-summary",
        action="store_true",
        default=False,
        help="Disable the unit/e2e per-file suite summary at session end.",
    )


def _resolve_test_file(config: Any, rel_path: str) -> Path | None:
    root = Path(str(config.rootpath))
    candidate = root / rel_path
    if candidate.is_file():
        return candidate
    # nodeid sometimes omits the tests/ prefix depending on invocation cwd.
    alt = root / "tests" / rel_path
    if alt.is_file():
        return alt
    return None


def load_file_docs(config: Any, paths: list[str]) -> dict[str, str]:
    docs: dict[str, str] = {}
    for rel in paths:
        file_path = _resolve_test_file(config, rel)
        if file_path is None:
            continue
        blurb = docstring_from_file(file_path)
        if blurb:
            docs[rel] = blurb
    return docs


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: Any) -> None:
    if config.getoption("--no-suite-summary", default=False):
        return
    # xdist workers have no terminal reporter summary worth printing.
    workerinput = getattr(config, "workerinput", None)
    if workerinput is not None:
        return

    by_suite = collect_file_stats(terminalreporter.stats)
    if not by_suite["unit"] and not by_suite["e2e"]:
        return

    all_paths = sorted({*by_suite["unit"], *by_suite["e2e"]})
    lines = format_suite_summary(
        by_suite,
        file_docs=load_file_docs(config, all_paths),
    )
    if not lines:
        return

    tw = terminalreporter.write_line
    tw("")
    width = getattr(terminalreporter, "_tw", None)
    sep_len = 70
    if width is not None and hasattr(width, "fullwidth"):
        sep_len = max(50, min(int(width.fullwidth), 96))
    tw("=" * sep_len)
    for line in lines:
        tw(line)
    tw("=" * sep_len)
