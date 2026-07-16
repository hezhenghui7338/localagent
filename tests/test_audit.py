"""Tests for audit usage logging and reports."""

from __future__ import annotations

from pathlib import Path

from localagent.audit.health import collect_memory_health
from localagent.audit.report import generate_report, write_report
from localagent.audit.security import run_security_scan
from localagent.audit.usage import aggregate_usage, load_usage_events, log_usage, parse_since
from localagent.cli import main


def test_log_and_aggregate_usage(isolated_data):
    log_usage("ollama", "qwen3.5:4b", command="chat", prompt_tokens=100, completion_tokens=50)
    log_usage("openrouter", "claude", command="chat", prompt_tokens=200, completion_tokens=80)
    events = load_usage_events()
    assert len(events) == 2
    stats = aggregate_usage(events)
    assert stats["total_calls"] == 2
    assert stats["total_tokens"] == 430
    assert "ollama" in stats["by_provider"]


def test_parse_since():
    since = parse_since("7d")
    assert since is not None


def test_security_scan_flags_env_symlink(tmp_path: Path, isolated_data, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET=abc\n", encoding="utf-8")
    link = isolated_data["kb_dir"] / ".env"
    link.symlink_to(env_file)

    report = run_security_scan()
    assert report.high_count >= 1
    assert any(".env" in f.path for f in report.findings)


def test_memory_health_counts(isolated_data):
    health = collect_memory_health()
    assert health.memory_facts == 0


def test_generate_report(isolated_data):
    log_usage("tavily", "search", command="web_search", per_call=True)
    md = generate_report(since=None, include_workspace=False)
    assert "# LocalAgent 审计报告" in md
    assert "Token 与服务花费" in md
    assert "Agent 行为与护栏" in md
    assert "文件安全" in md


def test_write_report_html(isolated_data, tmp_path: Path):
    log_usage("ollama", "qwen3.5:4b", command="chat", prompt_tokens=10, completion_tokens=5)
    out = write_report(tmp_path / "audit.html")
    html = out.read_text(encoding="utf-8")
    assert "<html" in html.lower()
    assert "LocalAgent" in html
    assert "Token" in html


def test_log_event_and_behavior_in_cli(isolated_data, capsys):
    from localagent.audit.events import log_event

    log_event(
        "tool.decision",
        tool="run_shell",
        outcome="executed",
        risk_level="safe",
        session_id="s-1",
    )
    log_event(
        "tool.decision",
        tool="web_search",
        outcome="executed",
        risk_level="safe",
        session_id="s-1",
    )
    rc = main(["audit"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "shell=1" in out
    assert "web=1" in out


def test_cli_audit_summary(isolated_data, capsys):
    log_usage("ollama", "test", command="chat", prompt_tokens=10, completion_tokens=5)
    rc = main(["audit"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[audit]" in out
    assert "Token" in out


def test_cli_audit_report_file(isolated_data, tmp_path: Path):
    out = tmp_path / "report.md"
    rc = main(["audit", "--report", str(out)])
    assert rc == 0
    assert out.is_file()
    assert "审计报告" in out.read_text(encoding="utf-8")
