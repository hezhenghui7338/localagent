"""Daily Actions + data-layer status surface tests."""

from __future__ import annotations

from localagent.status.daily import (
    DailyActionsStatus,
    collect_daily_actions_status,
    format_daily_actions_lines,
    format_daily_actions_report,
)
from localagent.status.layers import (
    DataLayerStatus,
    format_data_layer_banner_lines,
    format_data_layer_detail_lines,
    format_recall_priority_lines,
)
from localagent.status.report import format_status_report
from localagent.workspace.tasks import add_task


def test_format_daily_actions_lines():
    status = DailyActionsStatus(
        news_synced_today=True,
        pending_count=2,
        todo_count=3,
        aware_suggestion_count=1,
        aware_events_today=4,
        todo_previews=(("abcd1234", "修登录阻塞"),),
    )
    lines = format_daily_actions_lines(status)
    assert any("今日新闻已就绪" in line for line in lines)
    assert any("pending · 2" in line for line in lines)
    assert any("待办 · 3" in line for line in lines)
    assert any("[abcd1234]" in line for line in lines)
    assert any("workspace tasks" in line for line in lines)
    assert any("suggestion 1" in line for line in lines)


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
    assert "la workspace tasks" in report
    assert "la aware" in report
    assert "la aware suggestion" in report


def test_format_data_layer_banner_and_detail_lines():
    layers = DataLayerStatus(
        hot_configured=True,
        hot_name="Ada",
        hot_pref_count=3,
        hot_anchor_count=1,
        hot_updated_at="2026-07-18T12:00:00+08:00",
        warm_facts=12,
        warm_pending=1,
        warm_sources={"chat": 8, "chatgpt": 2, "file": 1, "other": 1},
        cold_kb_files=3,
        cold_chunks={"kb": 10, "chat": 5, "chatgpt": 7, "other": 0},
        cold_chat_sessions=4,
        cold_chatgpt_imported=2,
        cold_news_bookmarks=6,
        cold_summarize_kept=1,
        aware_events_today=575,
        aware_suggestions=2,
    )
    banner = format_data_layer_banner_lines(layers)
    assert any("Hot · 已配置 · 3偏好" in line for line in banner)
    assert any("Warm · 12事实 · pending 1" in line for line in banner)
    assert any("Cold · kb3" in line for line in banner)
    assert any("Aware · 今日575" in line for line in banner)
    assert any("la status 查看明细" in line for line in banner)

    detail = format_data_layer_detail_lines(layers)
    assert any(line.startswith("Hot   已配置") and "Ada" in line for line in detail)
    assert any("pending 1" in line and "chat=8" in line for line in detail)
    assert any("news=6" in line and "summarize=1" in line for line in detail)
    assert any("suggestion 2" in line for line in detail)


def test_format_status_report_includes_layers_and_recall():
    report = format_status_report(
        daily=DailyActionsStatus(
            news_synced_today=True,
            pending_count=1,
            todo_count=0,
        ),
        layers=DataLayerStatus(
            hot_configured=False,
            warm_facts=0,
            warm_pending=1,
            cold_kb_files=0,
            aware_events_today=3,
        ),
    )
    assert "LocalAgent · Status" in report
    assert "── Daily Actions ──" in report
    assert "── 数据层 ──" in report
    assert "── 综合召回 ──" in report
    assert "Hot   未配置" in report
    assert "Warm  0事实 · pending 1" in report
    assert "personal" in report
    assert "时间邻近加权" in report
    assert "la memory status" in report
    recall = format_recall_priority_lines()
    assert any("Hot/Warm" in line for line in recall)


def test_collect_daily_actions_status_isolated(isolated_data, monkeypatch, tmp_path):
    monkeypatch.setattr("localagent.status.daily.today_synced", lambda: True)
    monkeypatch.setattr("localagent.status.daily.pending_count", lambda: 1)
    monkeypatch.setenv("LA_WORKSPACE", str(tmp_path))
    add_task("今日核对", "用户指定的每日检查项需要处理", workspace=tmp_path)
    status = collect_daily_actions_status()
    assert status.news_synced_today is True
    assert status.pending_count == 1
    assert status.todo_count >= 1
    assert status.has_signal
    assert any(title == "今日核对" for _, title in status.todo_previews)


def test_collect_data_layer_status_isolated(isolated_data, monkeypatch):
    from localagent.memory.core_profile import CoreProfile, save_core_profile
    from localagent.status.layers import collect_data_layer_status

    save_core_profile(
        CoreProfile(name="TestUser", preferences={"语言": "中文"}, current_status="coding")
    )
    monkeypatch.setattr("localagent.pending.queue.pending_count", lambda: 2)
    monkeypatch.setattr(
        "localagent.aware.store.events_count_today",
        lambda: 9,
    )
    monkeypatch.setattr(
        "localagent.aware.suggestion.suggestion_count",
        lambda: 1,
    )
    status = collect_data_layer_status()
    assert status.hot_configured is True
    assert status.hot_name == "TestUser"
    assert status.hot_pref_count == 1
    assert status.warm_pending == 2
    assert status.aware_events_today == 9
    assert status.aware_suggestions == 1
