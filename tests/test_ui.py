"""Tests for terminal UI helpers."""

from __future__ import annotations

from localagent.ui.console import ActivityIndicator, emit, spinner


def test_emit(capsys):
    emit("test", "hello")
    assert capsys.readouterr().out == "[test] hello\n"


def test_spinner_non_tty(capsys):
    with spinner("sync", "working"):
        pass
    out = capsys.readouterr().out
    assert "[sync] working" in out


def test_activity_indicator_update(capsys):
    with ActivityIndicator("chat", "思考中…") as activity:
        activity.update("调用工具: search_memory")
    out = capsys.readouterr().out
    assert "[chat] 思考中…" in out
    assert "[chat] 调用工具: search_memory" in out
    assert "\r" not in out
    assert "\x1b[2K" not in out


def test_activity_indicator_streaming(capsys):
    with ActivityIndicator("chat", "思考中…") as activity:
        activity.update("生成回复…")
        activity.begin_streaming()
        print("streamed", end="", flush=True)
    out = capsys.readouterr().out
    assert "streamed" in out
    assert "\r" not in out
    assert "\x1b[2K" not in out


def test_activity_indicator_exit(capsys):
    with ActivityIndicator("chat", "思考中…") as activity:
        activity.update("调用工具: search_memory")
    out = capsys.readouterr().out
    assert "[chat] ✓" in out
    assert out.endswith("\n")
    assert "\r" not in out
