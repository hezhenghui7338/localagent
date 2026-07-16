"""Workspace read / edit / glob / grep tool tests."""

from __future__ import annotations

from pathlib import Path

from localagent.tools import execute_tool
from localagent.tools.approval import classify_tool, needs_approval
from localagent.tools.files import edit_file_tool, read_file_tool, write_file_tool
from localagent.tools.search import glob_tool, grep_tool


def test_read_file_tool_with_line_numbers(tmp_path: Path):
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    result = read_file_tool("a.txt", cwd=str(tmp_path))
    assert "文件: a.txt" in result
    assert "1|one" in result
    assert "2|two" in result
    assert "3|three" in result


def test_read_file_tool_offset_limit(tmp_path: Path):
    (tmp_path / "a.txt").write_text("a\nb\nc\nd\n", encoding="utf-8")
    result = read_file_tool("a.txt", offset=2, limit=2, cwd=str(tmp_path))
    assert "2|b" in result
    assert "3|c" in result
    assert "1|a" not in result
    assert "4|d" not in result


def test_read_file_blocks_outside_workspace(tmp_path: Path):
    outside = tmp_path.parent / "outside_read.txt"
    outside.write_text("secret", encoding="utf-8")
    result = read_file_tool(str(outside), cwd=str(tmp_path))
    assert "必须位于工作区内" in result


def test_read_file_missing(tmp_path: Path):
    result = read_file_tool("missing.txt", cwd=str(tmp_path))
    assert "不存在" in result


def test_edit_file_unique_replace(tmp_path: Path):
    target = tmp_path / "code.py"
    target.write_text("def foo():\n    return 1\n", encoding="utf-8")
    result = edit_file_tool(
        "code.py",
        "return 1",
        "return 2",
        cwd=str(tmp_path),
    )
    assert "已编辑文件" in result
    assert "替换 1 处" in result
    assert target.read_text(encoding="utf-8") == "def foo():\n    return 2\n"


def test_edit_file_requires_unique_match(tmp_path: Path):
    target = tmp_path / "dup.txt"
    target.write_text("x\nx\n", encoding="utf-8")
    result = edit_file_tool("dup.txt", "x", "y", cwd=str(tmp_path))
    assert "出现 2 次" in result
    assert target.read_text(encoding="utf-8") == "x\nx\n"


def test_edit_file_replace_all(tmp_path: Path):
    target = tmp_path / "dup.txt"
    target.write_text("x\nx\n", encoding="utf-8")
    result = edit_file_tool("dup.txt", "x", "y", replace_all=True, cwd=str(tmp_path))
    assert "替换 2 处" in result
    assert target.read_text(encoding="utf-8") == "y\ny\n"


def test_edit_file_not_found_string(tmp_path: Path):
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    result = edit_file_tool("a.txt", "missing", "x", cwd=str(tmp_path))
    assert "未找到" in result


def test_edit_file_blocks_outside_workspace(tmp_path: Path):
    outside = tmp_path.parent / "outside_edit.txt"
    outside.write_text("keep", encoding="utf-8")
    result = edit_file_tool(str(outside), "keep", "gone", cwd=str(tmp_path))
    assert "必须位于工作区内" in result
    assert outside.read_text(encoding="utf-8") == "keep"


def test_classify_edit_file_needs_approval():
    risk = classify_tool(
        "edit_file",
        {"path": "a.py", "old_string": "a", "new_string": "b"},
    )
    assert risk.level == "dangerous"
    assert needs_approval("edit_file", risk, policy="dangerous")
    assert needs_approval("edit_file", risk, policy="always")
    assert not needs_approval("edit_file", risk, policy="off")
    assert not needs_approval("read_file", risk, policy="always")


def test_glob_tool_finds_files(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("1", encoding="utf-8")
    (tmp_path / "src" / "b.txt").write_text("2", encoding="utf-8")
    (tmp_path / "src" / "nested").mkdir()
    (tmp_path / "src" / "nested" / "c.py").write_text("3", encoding="utf-8")

    result = glob_tool("**/*.py", cwd=str(tmp_path))
    assert "src/a.py" in result
    assert "src/nested/c.py" in result
    assert "b.txt" not in result


def test_glob_tool_truncates(tmp_path: Path):
    for i in range(5):
        (tmp_path / f"f{i}.py").write_text(str(i), encoding="utf-8")
    result = glob_tool("*.py", cwd=str(tmp_path), max_results=2)
    assert "已截断" in result
    assert result.count(".py") >= 2


def test_glob_blocks_outside_via_path(tmp_path: Path):
    result = glob_tool("*.py", path=str(tmp_path.parent), cwd=str(tmp_path))
    assert "必须位于工作区内" in result


def test_grep_tool_content(tmp_path: Path):
    (tmp_path / "a.py").write_text("def hello():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def world():\n    pass\n", encoding="utf-8")
    result = grep_tool(r"def hello", cwd=str(tmp_path))
    assert "a.py:1:def hello():" in result
    assert "b.py" not in result


def test_grep_tool_files_with_matches_and_glob(tmp_path: Path):
    (tmp_path / "a.py").write_text("TODO: fix\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("TODO: docs\n", encoding="utf-8")
    result = grep_tool(
        "TODO",
        glob="*.py",
        output_mode="files_with_matches",
        cwd=str(tmp_path),
    )
    assert "a.py" in result
    assert "b.md" not in result


def test_grep_tool_truncates(tmp_path: Path):
    lines = "\n".join(f"match {i}" for i in range(20))
    (tmp_path / "big.txt").write_text(lines + "\n", encoding="utf-8")
    result = grep_tool("match", cwd=str(tmp_path), head_limit=3)
    assert "已截断" in result
    assert result.count("big.txt:") == 3


def test_grep_invalid_regex(tmp_path: Path):
    result = grep_tool("[", cwd=str(tmp_path))
    assert "无效的正则" in result


def test_execute_tool_read_edit_glob_grep(tmp_path: Path):
    write_file_tool("demo.py", "alpha = 1\n", cwd=str(tmp_path))
    read = execute_tool("read_file", {"path": "demo.py", "cwd": str(tmp_path)})
    assert "1|alpha = 1" in read

    edited = execute_tool(
        "edit_file",
        {
            "path": "demo.py",
            "old_string": "alpha = 1",
            "new_string": "alpha = 2",
            "cwd": str(tmp_path),
        },
    )
    assert "已编辑文件" in edited

    found = execute_tool("glob", {"pattern": "*.py", "cwd": str(tmp_path)})
    assert "demo.py" in found

    grepped = execute_tool(
        "grep",
        {"pattern": "alpha = 2", "cwd": str(tmp_path)},
    )
    assert "demo.py:1:alpha = 2" in grepped
