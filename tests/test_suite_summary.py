"""Unit tests for the pytest suite summary helper."""

from __future__ import annotations

from types import SimpleNamespace

from pathlib import Path

from suite_summary import (
    FileStats,
    collect_file_stats,
    docstring_from_file,
    file_path_from_nodeid,
    first_doc_line,
    format_suite_summary,
    short_test_name,
    suite_for,
    truncate,
)


def test_suite_for_unit_vs_e2e():
    assert suite_for("tests/test_cli.py") == "unit"
    assert suite_for("tests/e2e/test_la_commands.py") == "e2e"
    assert suite_for("tests\\e2e\\test_la_ops.py") == "e2e"


def test_nodeid_helpers():
    nodeid = "tests/e2e/test_la_commands.py::test_help"
    assert file_path_from_nodeid(nodeid) == "tests/e2e/test_la_commands.py"
    assert short_test_name(nodeid) == "test_help"


def test_first_doc_line_and_truncate():
    assert first_doc_line("\n  Hello world\nMore") == "Hello world"
    assert first_doc_line(None) == ""
    assert truncate("abcdefghij", 8) == "abcdefg…"


def test_collect_and_format_groups_unit_and_e2e():
    stats = {
        "passed": [
            SimpleNamespace(nodeid="tests/test_cli.py::test_a", when="call"),
            SimpleNamespace(nodeid="tests/test_cli.py::test_b", when="call"),
            SimpleNamespace(nodeid="tests/e2e/test_la_ops.py::test_c", when="call"),
        ],
        "failed": [
            SimpleNamespace(nodeid="tests/test_cli.py::test_d", when="call"),
        ],
        "skipped": [
            SimpleNamespace(nodeid="tests/e2e/test_la_live.py::test_live", when="setup"),
        ],
    }
    by_suite = collect_file_stats(stats)
    assert by_suite["unit"]["tests/test_cli.py"].passed == 2
    assert by_suite["unit"]["tests/test_cli.py"].failed == 1
    assert "test_d" in by_suite["unit"]["tests/test_cli.py"].failed_names
    assert by_suite["e2e"]["tests/e2e/test_la_ops.py"].passed == 1
    assert by_suite["e2e"]["tests/e2e/test_la_live.py"].skipped == 1

    lines = format_suite_summary(
        by_suite,
        file_docs={
            "tests/test_cli.py": "CLI integration tests covering PRD command surface.",
            "tests/e2e/test_la_ops.py": "Ops e2e.",
        },
    )
    text = "\n".join(lines)
    assert "单元 / 集成 (unit)" in text
    assert "端到端 (e2e)" in text
    assert "tests/test_cli.py" in text
    assert "CLI integration" in text
    assert "合计" in text
    assert any("✗ test_d" in line for line in lines)


def test_file_stats_counts_text():
    fs = FileStats(passed=3, skipped=1)
    assert fs.counts_text() == "3 passed, 1 skipped"
    assert fs.total == 4


def test_docstring_from_file_reads_module_doc(tmp_path: Path):
    path = tmp_path / "sample_test.py"
    path.write_text('"""Hello from sample.\\n\\nMore."""\n\ndef test_x():\n    pass\n', encoding="utf-8")
    assert docstring_from_file(path) == "Hello from sample."
    assert docstring_from_file(tmp_path / "missing.py") == ""
