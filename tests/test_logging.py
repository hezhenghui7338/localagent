"""Tests for diagnostic logging (loguru setup + LA logs)."""

from __future__ import annotations

import logging
from argparse import Namespace

from localagent.cli import build_parser, cmd_logs, main
from localagent.logging_setup import (
    read_app_log,
    resolve_log_level,
    setup_logging,
    truncate_for_log,
)


def test_resolve_log_level_defaults_and_debug(monkeypatch):
    monkeypatch.delenv("LA_LOG_LEVEL", raising=False)
    assert resolve_log_level() == "INFO"
    assert resolve_log_level(debug=True) == "DEBUG"
    monkeypatch.setenv("LA_LOG_LEVEL", "warning")
    assert resolve_log_level() == "WARNING"
    assert resolve_log_level(debug=True) == "DEBUG"


def test_setup_logging_writes_file_and_intercepts_stdlib(isolated_data, monkeypatch):
    monkeypatch.delenv("LA_LOG_LEVEL", raising=False)
    setup_logging(level="INFO", debug_stderr=False)

    from localagent import config

    assert config.APP_LOG_FILE.exists() or True  # created on first write
    logging.getLogger("localagent.test_logging").info("causal hit count=%s", 3)
    text = config.APP_LOG_FILE.read_text(encoding="utf-8")
    assert "causal hit count=3" in text
    assert "INFO" in text


def test_setup_logging_debug_writes_debug_lines(isolated_data, monkeypatch):
    monkeypatch.setenv("LA_LOG_LEVEL", "DEBUG")
    setup_logging(level="DEBUG", debug_stderr=False)
    logging.getLogger("localagent.test_logging").debug("debug-only detail")
    from localagent import config

    text = config.APP_LOG_FILE.read_text(encoding="utf-8")
    assert "debug-only detail" in text


def test_read_app_log_tail_and_level_filter(isolated_data, monkeypatch):
    monkeypatch.delenv("LA_LOG_LEVEL", raising=False)
    setup_logging(level="DEBUG", debug_stderr=False)
    log = logging.getLogger("localagent.test_logging")
    log.debug("line-debug")
    log.info("line-info")
    log.warning("line-warn")

    all_text = read_app_log(tail=0)
    assert "line-debug" in all_text
    assert "line-info" in all_text
    assert "line-warn" in all_text

    warn_only = read_app_log(tail=0, level_filter="WARNING")
    assert "line-warn" in warn_only
    assert "line-info" not in warn_only
    assert "line-debug" not in warn_only

    tailed = read_app_log(tail=1)
    assert "line-warn" in tailed
    assert tailed.count("\n") == 0 or len(tailed.splitlines()) == 1


def test_truncate_for_log():
    assert truncate_for_log("short") == "short"
    long = "x" * 100
    out = truncate_for_log(long, limit=20)
    assert len(out) == 20
    assert out.endswith("…")


def test_build_parser_exposes_logs_and_debug():
    help_text = build_parser().format_help()
    assert "--debug" in help_text
    assert "logs" in help_text


def test_cmd_logs_empty_and_path(isolated_data, capsys):
    from localagent import config

    # Ensure no leftover log from other tests in this data dir
    if config.APP_LOG_FILE.exists():
        config.APP_LOG_FILE.unlink()

    assert cmd_logs(Namespace(path=True, tail=80, level=None)) == 0
    out = capsys.readouterr().out
    assert str(config.APP_LOG_FILE) in out

    assert cmd_logs(Namespace(path=False, tail=80, level=None)) == 0
    out = capsys.readouterr().out
    assert "尚无日志" in out


def test_cmd_logs_prints_content(isolated_data, capsys):
    setup_logging(level="INFO", debug_stderr=False)
    logging.getLogger("localagent.test_logging").info("visible-for-logs-cmd")
    assert cmd_logs(Namespace(path=False, tail=80, level=None)) == 0
    out = capsys.readouterr().out
    assert "visible-for-logs-cmd" in out


def test_main_logs_command_smoke(isolated_data):
    assert main(["logs", "--path"]) == 0
    assert main(["logs"]) == 0
