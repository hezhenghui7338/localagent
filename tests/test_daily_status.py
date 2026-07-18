"""Daily Actions surface tests."""

from __future__ import annotations

from localagent.status.daily import (
    DailyActionsStatus,
    collect_daily_actions_status,
    format_daily_actions_lines,
    format_daily_actions_report,
)


def test_format_daily_actions_lines():
    status = DailyActionsStatus(
        news_synced_today=True,
        pending_count=2,
        todo_count=3,
    )
    lines = format_daily_actions_lines(status)
    assert any("今日新闻已就绪" in line for line in lines)
    assert any("pending · 2" in line for line in lines)
    assert any("待办 · 3" in line for line in lines)


def test_format_daily_actions_report_includes_tagline():
    report = format_daily_actions_report(
        DailyActionsStatus(
            news_synced_today=False,
            pending_count=0,
            todo_count=0,
        )
    )
    assert "Local First. Memory Forever. Actions Automated." in report
    assert "今日新闻未 sync" in report
    assert "la news brief" in report


def test_collect_daily_actions_status_isolated(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.status.daily.today_synced", lambda: True)
    monkeypatch.setattr("localagent.status.daily.pending_count", lambda: 1)
    status = collect_daily_actions_status()
    assert status.news_synced_today is True
    assert status.pending_count == 1
    assert status.has_signal
