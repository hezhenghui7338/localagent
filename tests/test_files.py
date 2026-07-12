"""Workspace file write tool tests."""

from __future__ import annotations

from pathlib import Path

from localagent.tools import execute_tool
from localagent.tools.files import write_file_tool


def test_write_file_tool_overwrite(tmp_path: Path):
    target = tmp_path / "test.txt"
    result = write_file_tool("test.txt", "hello world", cwd=str(tmp_path))

    assert "已写入文件" in result
    assert target.read_text(encoding="utf-8") == "hello world"


def test_write_file_tool_append(tmp_path: Path):
    target = tmp_path / "test.txt"
    target.write_text("line1\n", encoding="utf-8")

    result = write_file_tool("test.txt", "line2\n", mode="append", cwd=str(tmp_path))

    assert "已追加文件" in result
    assert target.read_text(encoding="utf-8") == "line1\nline2\n"


def test_write_file_tool_blocks_path_outside_workspace(tmp_path: Path):
    outside = tmp_path.parent / "outside.txt"
    result = write_file_tool(str(outside), "nope", cwd=str(tmp_path))

    assert "必须位于工作区内" in result
    assert not outside.exists()


def test_execute_tool_write_file(tmp_path: Path):
    result = execute_tool(
        "write_file",
        {"path": "nested/out.txt", "content": "nested content", "cwd": str(tmp_path)},
    )

    assert "已写入文件" in result
    assert (tmp_path / "nested" / "out.txt").read_text(encoding="utf-8") == "nested content"
