"""Unit tests for la aware (consent, cursors, policy, view, suggestions)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from localagent.aware.digest import format_view
from localagent.aware.platform_paths import BrowserDb
from localagent.aware.policy import apply_policy
from localagent.aware.profile import grant_source, load_profile, ungrant_source
from localagent.aware.sensors.base import redact_secrets
from localagent.aware.sensors.browser import BrowserSensor
from localagent.aware.sensors.fs import FsSensor
from localagent.aware.sensors.terminal import TerminalSensor, _normalize_history_line
from localagent.aware.store import append_events, load_cursors, load_events, save_cursors
from localagent.aware.suggestion import enqueue, is_allowed_cmd, load_suggestions, remove_items
from localagent.aware.tick import run_tick
from localagent.aware.timewin import (
    format_period_span,
    format_span,
    label_since,
    parse_since,
    period_label,
    since_to_datetime,
)
from localagent.aware.types import AwareEvent


@pytest.fixture()
def aware_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    monkeypatch.setenv("LA_DATA_DIR", str(data))
    import localagent.config as config

    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "AWARE_DIR", data / "aware")
    monkeypatch.setattr(config, "AWARE_PROFILE_FILE", data / "aware" / "profile.json")
    monkeypatch.setattr(config, "AWARE_CURSORS_FILE", data / "aware" / "cursors.json")
    monkeypatch.setattr(config, "AWARE_EVENTS_FILE", data / "aware" / "events.jsonl")
    monkeypatch.setattr(
        config, "AWARE_INPUT_ACTIVITY_FILE", data / "aware" / "input_activity.json"
    )
    monkeypatch.setattr(config, "AWARE_EPISODES_FILE", data / "aware" / "episodes.jsonl")
    monkeypatch.setattr(config, "AWARE_SUGGESTIONS_FILE", data / "aware" / "suggestions.json")
    monkeypatch.setattr(config, "AWARE_SESSIONS_DIR", data / "aware" / "sessions")
    monkeypatch.setattr(config, "AWARE_NOW_DIR", data / "aware" / "now")
    monkeypatch.setattr(config, "AWARE_TICK_LOCK_FILE", data / "aware" / "tick.lock")
    monkeypatch.setattr(config, "AWARE_ACTIVE_HOURS_WELLNESS", 3)
    monkeypatch.setattr(config, "AWARE_TICK_INTERVAL_MINUTES", 15)
    monkeypatch.setattr(config, "KB_DIR", data / "kb")
    monkeypatch.setattr(config, "AUDIT_DIR", data / "audit")
    monkeypatch.setattr(config, "INGEST_TASKS_FILE", data / "ingest_tasks.json")
    monkeypatch.setattr(config, "TASK_LOGS_DIR", data / "task_logs")
    (data / "aware").mkdir(parents=True, exist_ok=True)
    (data / "aware" / "now").mkdir(parents=True, exist_ok=True)
    (data / "kb").mkdir(parents=True, exist_ok=True)
    (data / "audit").mkdir(parents=True, exist_ok=True)
    return data


def test_timewin_parse() -> None:
    assert parse_since(None) == "1w"
    assert parse_since("1d") == "1d"
    assert parse_since("2d") == "2d"
    assert parse_since("3w") == "3w"
    assert parse_since("3h") == "3h"
    assert "周" in label_since("1w")
    assert label_since("2d") == "最近 2 天"
    assert label_since("3h") == "最近 3 小时"
    # 1d cutoff is more recent than 1w cutoff
    assert since_to_datetime("1d") > since_to_datetime("1w")
    assert since_to_datetime("2d") > since_to_datetime("1w")
    assert since_to_datetime("3h") > since_to_datetime("1d")
    try:
        parse_since("abc")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_timewin_period_and_span() -> None:
    # 14:00 UTC → evening in UTC+8 / afternoon-ish elsewhere; period must be non-empty.
    start = "2026-07-18T14:00:00+00:00"
    end = "2026-07-18T14:30:00+00:00"
    assert period_label(start) in {"清晨", "上午", "下午", "傍晚", "晚上", "深夜"}
    span = format_span(start, end)
    assert "–" in span
    assert format_period_span(start, end).startswith(period_label(start))


def test_grant_ungrant_blocks_ungranted(aware_home: Path) -> None:
    profile = load_profile()
    assert not profile.is_granted("fs")
    grant_source("fs", paths=[str(aware_home / "watch")])
    assert load_profile().is_granted("fs")
    ungrant_source("fs")
    assert not load_profile().is_granted("fs")


def test_tick_skips_without_grant(aware_home: Path) -> None:
    result = run_tick()
    assert result.skipped
    assert result.event_count == 0


def test_fs_sensor_primes_then_detects_create(aware_home: Path, tmp_path: Path) -> None:
    watch = tmp_path / "watch"
    watch.mkdir()
    (watch / "a.txt").write_text("hi", encoding="utf-8")
    from localagent.aware.profile import SourceGrant

    sensor = FsSensor(SourceGrant(granted=True, paths=[str(watch)]))
    events1, cursor1 = sensor.collect({})
    assert events1 == []
    assert cursor1.get("primed") is True

    (watch / "new.pdf").write_bytes(b"%PDF-1.4")
    events2, _cursor2 = sensor.collect(cursor1)
    assert "file.created" in {e.kind for e in events2}


def test_terminal_redact_and_normalize() -> None:
    assert "PASSWORD=***" in redact_secrets("export PASSWORD=supersecret")
    assert _normalize_history_line(": 1234567890:0;ls -la") == "ls -la"


def test_terminal_sensor_seeds_offset(tmp_path: Path) -> None:
    hist = tmp_path / ".zsh_history"
    hist.write_text("echo one\necho two\n", encoding="utf-8")
    from localagent.aware.profile import SourceGrant

    sensor = TerminalSensor(SourceGrant(granted=True, history_files=[str(hist)]))
    events, cursor = sensor.collect({})
    assert events == []
    hist.write_text("echo one\necho two\necho three\n", encoding="utf-8")
    events2, _ = sensor.collect(cursor)
    assert len(events2) == 1
    assert "echo three" in events2[0].title


def test_browser_sensor_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "History"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT);
        CREATE TABLE visits (url INTEGER, visit_time INTEGER);
        INSERT INTO urls VALUES (1, 'https://example.com/a', 'Example');
        INSERT INTO visits VALUES (1, 13300000000000000);
        """
    )
    conn.commit()
    conn.close()

    db = BrowserDb("chrome", "chromium", db_path, profile="Default")
    monkeypatch.setattr(
        "localagent.aware.sensors.browser.discover_browser_dbs",
        lambda: [db],
    )
    monkeypatch.setattr(
        "localagent.aware.browser_tabs.collect_open_tabs",
        lambda: [],
    )
    from localagent.aware.profile import SourceGrant

    sensor = BrowserSensor(SourceGrant(granted=True))
    events1, cursor1 = sensor.collect({})
    assert events1 == []

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO urls VALUES (2, 'https://news.ycombinator.com/', 'HN')")
    conn.execute("INSERT INTO visits VALUES (2, 13300000000010000)")
    conn.commit()
    conn.close()

    events2, _ = sensor.collect(cursor1)
    assert events2
    assert events2[0].kind == "browser.summary"


def test_policy_noise_and_suggest(aware_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    events = [
        AwareEvent(
            source="fs",
            kind="file.created",
            title="x.dmg",
            data={"path": str(aware_home / "x.dmg"), "suffix": ".dmg"},
        ),
        AwareEvent(
            source="fs",
            kind="file.created",
            title="n.docx",
            data={"path": str(aware_home / "n.docx"), "suffix": ".docx"},
        ),
        AwareEvent(
            source="fs",
            kind="file.created",
            title="doc.pdf",
            data={"path": str(aware_home / "doc.pdf"), "suffix": ".pdf"},
        ),
    ]
    (aware_home / "doc.pdf").write_bytes(b"%PDF")
    result = apply_policy(events)
    assert result.auto_actions == []
    assert len(result.suggestions) == 2  # .docx + .pdf; never auto-ingest
    assert is_allowed_cmd("la ingest doc /tmp/a.pdf")
    assert is_allowed_cmd("la rag add /tmp/a.pdf")  # legacy inbox cmds still allowed
    assert not is_allowed_cmd("rm -rf /")


def test_suggestion_store(aware_home: Path) -> None:
    iid = enqueue(
        source="fs",
        title="t",
        rationale="r",
        suggested_cmd="la rag add /tmp/a.pdf",
    )
    assert load_suggestions()[0].id == iid
    remove_items([iid])
    assert load_suggestions() == []


def test_aware_cli_nested_suggestion_and_ungrant() -> None:
    from localagent.cli import build_parser

    p = build_parser()
    sug = p.parse_args(["aware", "suggestion", "approve", "all"])
    assert sug.aware_action == "suggestion"
    assert sug.suggestion_action == "approve"
    assert sug.target == "all"
    ungrant = p.parse_args(["aware", "ungrant", "browser"])
    assert ungrant.aware_action == "ungrant"
    assert ungrant.sources == ["browser"]
    listed = p.parse_args(["aware", "suggestion"])
    assert listed.aware_action == "suggestion"
    assert getattr(listed, "suggestion_action", None) in (None, "list")


def test_format_view_default_summary(aware_home: Path) -> None:
    text = format_view(mode="now", use_llm=False)
    assert "概览" in text
    assert "主注意力" in text
    assert "当前状态" in text
    assert "按注意力" in text
    assert "感知动态" not in text
    assert "系统" in text
    assert "近期状态" not in text
    assert "■ browser" not in text
    assert "aware>" in text or "--detail" in text


def test_format_view_now_keeps_activity_as_lines(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Input activity must not overwrite summarize_activity list (char-by-char bullets)."""
    from localagent.aware.input_activity import record_input_activity

    monkeypatch.setattr("localagent.aware.engagement.tick_interval_minutes", lambda: 15.0)
    grant_source("apps")
    record_input_activity(app="Cursor", idle_seconds=10.0)

    text = format_view(mode="now", use_llm=False)
    assert "今日输入活跃" in text
    # activity section should still be list bullets, not one char per line
    after = text.split("最近 3 小时（按注意力）", 1)[1]
    for stop in ("近期 Episode", "系统"):
        if stop in after:
            after = after.split(stop, 1)[0]
            break
    bullets = [ln for ln in after.splitlines() if ln.startswith("  · ")]
    assert bullets
    assert all(len(ln.removeprefix("  · ").strip()) > 1 for ln in bullets)
    assert "今日输入活跃" not in after  # belongs in 当前状态/系统, not overwritten into activity


def test_format_view_now_filters_old_episodes(aware_home: Path) -> None:
    from datetime import datetime, timedelta, timezone

    from localagent.aware.episode import AwareEpisode, append_episodes
    from localagent.aware.types import utc_now

    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(hours=5)).isoformat()
    fresh_ts = utc_now()
    append_episodes(
        [
            AwareEpisode(
                id="old-ep",
                scene="video",
                start=old_ts,
                end=old_ts,
                duration_min=15,
                source="browser",
                title="旧页面 bilibili 岁月无情",
                entities=["bilibili.com"],
            ),
            AwareEpisode(
                id="fresh-ep",
                scene="coding",
                start=fresh_ts,
                end=fresh_ts,
                duration_min=5,
                source="apps",
                title="Cursor 当前编辑",
                entities=["Cursor"],
            ),
        ]
    )
    text = format_view(mode="now", use_llm=False)
    assert "当前状态" in text
    assert "按注意力" in text
    assert "Cursor 当前编辑" in text
    assert "岁月无情" not in text
    assert "旧页面" not in text


def test_format_view_detail_ungranted(aware_home: Path) -> None:
    text = format_view(mode="now", detail=True)
    assert "LocalAgent · Aware · 当前" in text
    assert "未授权" in text
    assert "■ browser" in text


def test_format_view_window(aware_home: Path) -> None:
    append_events(
        [AwareEvent(source="terminal", kind="terminal.cmd", title="echo hi")]
    )
    grant_source("terminal", history_files=[])
    summary = format_view(
        mode="window", since="1w", source="terminal", use_llm=False
    )
    assert "最近 1 周" in summary
    assert "感知动态" in summary
    detail = format_view(
        mode="window", since="1w", source="terminal", detail=True
    )
    assert "最近 1 周" in detail
    assert "■ terminal" in detail


def test_format_view_llm_fallback(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_events(
        [AwareEvent(source="terminal", kind="terminal.cmd", title="pytest -q")]
    )
    grant_source("terminal", history_files=[])
    import localagent.aware.summary as summary_mod

    monkeypatch.setattr(summary_mod, "llm_summarize_facts", lambda _card: None)
    text = format_view(mode="window", since="1w", source="terminal", use_llm=True)
    assert "感知动态" in text
    assert "系统" in text
    assert "terminal" in text.lower() or "pytest" in text


def test_aware_cli_detail_flag() -> None:
    from localagent.cli import build_parser

    p = build_parser()
    bare = p.parse_args(["aware", "--detail"])
    assert bare.detail is True
    since = p.parse_args(["aware", "--since", "1d", "--detail"])
    assert since.detail is True
    assert since.since == "1d"
    since2 = p.parse_args(["aware", "--since", "2d"])
    assert since2.since == "2d"
    tick = p.parse_args(["aware", "tick", "--detail"])
    assert tick.detail is True
    assert tick.aware_action == "tick"
    default = p.parse_args(["aware"])
    assert default.detail is False
    no_chat = p.parse_args(["aware", "--no-chat"])
    assert no_chat.no_chat is True
    tick_nc = p.parse_args(["aware", "tick", "--no-chat"])
    assert tick_nc.no_chat is True


def test_build_episodes_from_fs_and_terminal(aware_home: Path) -> None:
    from localagent.aware.episode import (
        append_episodes,
        build_episodes_from_events,
        load_episodes,
        retrieve_aware_context,
    )

    events = [
        AwareEvent(
            source="fs",
            kind="file.modified",
            title="notes.md",
            data={
                "path": "/tmp/notes.md",
                "suffix": ".md",
                "size": 120,
                "chars_approx": 40,
            },
        ),
        AwareEvent(
            source="terminal",
            kind="terminal.cmd",
            title="pytest -q",
            data={"command": "pytest -q"},
        ),
        AwareEvent(
            source="terminal",
            kind="terminal.cmd",
            title="git status",
            data={"command": "git status"},
        ),
    ]
    eps = build_episodes_from_events(events)
    scenes = {e.scene for e in eps}
    assert "writing" in scenes or "coding" in scenes
    assert any(e.source == "terminal" for e in eps)
    append_episodes(eps)
    loaded = load_episodes(limit=20)
    assert len(loaded) >= 1
    ctx = retrieve_aware_context("pytest 文件", since_hours=48)
    assert "Aware" in ctx
    assert "Episode" in ctx


def test_wellness_active_hours(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timezone

    from localagent.aware.episode import maybe_enqueue_active_hours_wellness
    from localagent.aware.suggestion import load_suggestions

    now = datetime.now(timezone.utc)
    events = []
    for hour in (8, 10, 12, 14):
        ts = now.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()
        events.append(
            AwareEvent(
                source="terminal",
                kind="terminal.cmd",
                title=f"cmd{hour}",
                ts=ts,
                data={"command": f"echo {hour}"},
            )
        )
    append_events(events)
    iid = maybe_enqueue_active_hours_wellness()
    assert iid
    items = load_suggestions()
    assert any(i.data.get("kind") == "wellness" for i in items)
    # cooldown
    assert maybe_enqueue_active_hours_wellness() is None


def test_classify_scenes() -> None:
    from localagent.aware.scenes import classify_focus, classify_host, is_browser_app

    assert classify_focus(app="Cursor", bundle_id="com.todesktop.xxx") == "coding"
    assert classify_focus(app="zoom.us", window_title="Standup") == "call"
    assert classify_focus(media_title="情书", media_app="Spotify") == "music"
    assert classify_focus(app="IINA", window_title="Movie") == "movie"
    assert classify_host("www.bilibili.com") == "video"
    assert classify_host("music.163.com") == "music"
    assert classify_host("xhamster.com") == "sensitive_video"
    assert is_browser_app("Google Chrome")
    assert is_browser_app("chrome")
    assert not is_browser_app("Cursor")


def test_apps_sensor_mocked(aware_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from localagent.aware.profile import SourceGrant
    from localagent.aware.sensors.apps import AppsSensor

    payload = json.dumps(
        {
            "app": "Cursor",
            "bundle_id": "com.todesktop.xxx",
            "window_title": "LocalAgent",
            "media_title": "",
            "media_artist": "",
            "media_app": "",
            "error": "",
        }
    )

    class _Proc:
        returncode = 0
        stdout = payload
        stderr = ""

    monkeypatch.setattr("localagent.aware.sensors.apps.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "localagent.aware.sensors.apps.subprocess.run",
        lambda *a, **k: _Proc(),
    )
    monkeypatch.setattr(
        "localagent.aware.sensors.apps._idle_seconds",
        lambda: 12.0,
    )
    sensor = AppsSensor(SourceGrant(granted=True))
    events, cursor = sensor.collect({})
    assert len(events) == 1
    assert events[0].kind == "apps.focus"
    assert events[0].data.get("scene") == "coding"
    assert events[0].data.get("engagement") == "glance"
    assert events[0].data.get("ticks_seen") == 1
    assert events[0].data.get("input_active") is True
    # identical snapshot → heartbeat with accumulated dwell
    events2, cursor2 = sensor.collect(cursor)
    assert len(events2) == 1
    assert events2[0].data.get("ticks_seen") == 2
    assert events2[0].data.get("engagement") == "engage"  # idle=12 < 120
    assert cursor2["session"]["ticks_seen"] == 2


def test_input_activity_idle_and_by_app(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from localagent.aware.input_activity import (
        format_input_activity_line,
        load_day,
        record_input_activity,
    )
    from localagent.aware.profile import SourceGrant
    from localagent.aware.sensors.apps import AppsSensor

    monkeypatch.setattr("localagent.aware.engagement.tick_interval_minutes", lambda: 15.0)

    record_input_activity(app="Cursor", idle_seconds=10.0)
    record_input_activity(app="Terminal", idle_seconds=20.0)
    record_input_activity(app="Safari", idle_seconds=400.0)  # idle high → no minutes
    day = load_day()
    assert day["ticks_total"] == 3
    assert day["ticks_active"] == 2
    assert day["active_minutes"] == 30.0
    assert day["by_app"]["Cursor"] == 15.0
    assert day["by_app"]["Terminal"] == 15.0
    assert "Safari" not in day["by_app"]
    line = format_input_activity_line()
    assert line is not None
    assert "约 30 分钟" in line
    assert "Cursor" in line

    # Display collect must not inflate aggregates
    payload = json.dumps(
        {
            "app": "Notes",
            "bundle_id": "com.apple.Notes",
            "window_title": "x",
            "media_title": "",
            "media_artist": "",
            "media_app": "",
            "error": "",
        }
    )

    class _Proc:
        returncode = 0
        stdout = payload
        stderr = ""

    monkeypatch.setattr("localagent.aware.sensors.apps.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "localagent.aware.sensors.apps.subprocess.run",
        lambda *a, **k: _Proc(),
    )
    monkeypatch.setattr("localagent.aware.sensors.apps._idle_seconds", lambda: 5.0)
    before = load_day()["active_minutes"]
    AppsSensor(SourceGrant(granted=True)).collect({}, record_activity=False)
    assert load_day()["active_minutes"] == before

    # Default collect records
    AppsSensor(SourceGrant(granted=True)).collect({})
    assert load_day()["active_minutes"] == before + 15.0
    assert load_day()["by_app"]["Notes"] == 15.0


def test_hypothesis_from_music_episodes(aware_home: Path) -> None:
    from localagent.aware.episode import AwareEpisode, append_episodes
    from localagent.aware.hypothesis import (
        generate_hypotheses_from_episodes,
        run_hypothesis_loop,
    )
    from localagent.aware.suggestion import load_suggestions
    from localagent.aware.types import utc_now

    now = utc_now()
    append_episodes(
        [
            AwareEpisode(
                id="e1",
                scene="music",
                start=now,
                end=now,
                duration_min=45,
                source="apps",
                title="Spotify · ♪ 情书",
                entities=["情书", "Spotify"],
                signals={"media_title": "情书"},
                evidence=["Spotify · ♪ 情书"],
            )
        ]
    )
    hyps = generate_hypotheses_from_episodes(
        [
            AwareEpisode(
                id="e1",
                scene="music",
                start=now,
                end=now,
                duration_min=45,
                source="apps",
                title="Spotify · ♪ 情书",
                entities=["情书"],
                signals={"media_title": "情书"},
            )
        ]
    )
    assert hyps
    assert hyps[0].scene == "music"
    assert "听音乐" in hyps[0].claim
    added = run_hypothesis_loop(force=True, since_hours=48)
    assert added
    assert any(i.data.get("kind") == "insight" for i in load_suggestions())


def test_prefetch_aware_query_gate() -> None:
    from localagent.agent.runtime import _AWARE_QUERY, _prefetch_aware_context

    assert _AWARE_QUERY.search("我今天下午在忙什么")
    assert _AWARE_QUERY.search("最近听了什么歌")
    assert not _AWARE_QUERY.search("今天天气怎么样")
    # empty episodes still returns a status card → non-empty or empty ok
    ctx = _prefetch_aware_context("随便聊聊天气")
    assert ctx == ""


def test_should_enter_aware_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    from localagent.aware import repl as repl_mod
    from localagent.aware.repl import should_enter_aware_chat

    assert should_enter_aware_chat(no_chat=True) is False

    class _Tty:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(repl_mod.sys, "stdin", _Tty())
    monkeypatch.setattr(repl_mod.sys, "stdout", _Tty())
    assert should_enter_aware_chat(no_chat=False) is True


def test_tick_with_fs_grant(
    aware_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from localagent.aware.episode import load_episodes
    from localagent.aware.suggestion import load_suggestions
    import localagent.config as config

    watch = tmp_path / "w"
    watch.mkdir()
    grant_source("fs", paths=[str(watch)])
    kb_before = {p.name for p in config.KB_DIR.iterdir()} if config.KB_DIR.is_dir() else set()
    r1 = run_tick()
    assert r1.event_count == 0
    (watch / "n.pdf").write_bytes(b"%PDF")
    (watch / "note.md").write_text("hello world\n", encoding="utf-8")
    r2 = run_tick()
    assert r2.event_count >= 1
    kb_after = {p.name for p in config.KB_DIR.iterdir()} if config.KB_DIR.is_dir() else set()
    assert kb_after == kb_before  # aware must not auto-link into kb/
    assert any(s.source == "fs" for s in load_suggestions())
    # second tick after modify should record size delta / episode
    (watch / "note.md").write_text("hello world\nmore\n", encoding="utf-8")
    r3 = run_tick()
    assert r3.event_count >= 1
    eps = load_episodes(limit=20)
    assert any(e.source == "fs" for e in eps)


def test_browser_episode_keeps_title_samples(aware_home: Path) -> None:
    from localagent.aware.episode import AwareEpisode, build_episodes_from_events

    events = [
        AwareEvent(
            source="browser",
            kind="browser.summary",
            title="浏览摘要: www.bilibili.com×3, 51cg1.com×1",
            data={
                "hosts": [
                    {
                        "host": "www.bilibili.com",
                        "count": 3,
                        "sample": "哔哩哔哩 (゜-゜)つロ 干杯~",
                    },
                    {
                        "host": "51cg1.com",
                        "count": 1,
                        "sample": "每日大赛 - 投稿页 | 51吃瓜网",
                    },
                ],
                "visit_count": 4,
            },
        )
    ]
    eps = build_episodes_from_events(events)
    assert len(eps) == 1
    ep = eps[0]
    assert ep.source == "browser"
    assert "每日大赛" in " ".join(ep.evidence)
    assert any("每日大赛" in str(s) for s in (ep.signals.get("samples") or []))
    card = ep.to_card_line()
    assert "每日大赛" in card
    assert "51cg1.com" in card or "bilibili" in card


def test_browser_episode_redacts_sensitive_samples(aware_home: Path) -> None:
    from localagent.aware.episode import build_episodes_from_events

    events = [
        AwareEvent(
            source="browser",
            kind="browser.summary",
            title="浏览摘要: www.pornhub.com×2",
            data={
                "hosts": [
                    {
                        "host": "www.pornhub.com",
                        "count": 2,
                        "sample": "Secret Title Should Not Leak",
                    }
                ],
                "visit_count": 2,
            },
        )
    ]
    eps = build_episodes_from_events(events)
    assert len(eps) == 1
    ep = eps[0]
    assert ep.scene == "sensitive_video"
    assert ep.entities == []
    assert ep.evidence == []
    assert "samples" not in ep.signals
    assert "Secret Title" not in ep.to_card_line()
    assert "敏感类" in ep.title


def test_retrieve_aware_context_injects_open_tabs(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from localagent.aware.browser_tabs import BrowserNow
    from localagent.aware.episode import retrieve_aware_context

    snap = BrowserNow(
        browser="chrome",
        windows=1,
        tabs=2,
        active_title="每日大赛 - 投稿页 | 51吃瓜网",
        active_url="https://51cg1.com/category/mrds/",
        frontmost=False,
        items=[
            {
                "title": "每日大赛 - 投稿页 | 51吃瓜网",
                "url": "https://51cg1.com/category/mrds/",
                "active": "true",
            },
            {
                "title": "GitHub",
                "url": "https://github.com/",
                "active": "",
            },
        ],
    )
    monkeypatch.setattr(
        "localagent.aware.browser_tabs.collect_open_tabs",
        lambda: [snap],
    )
    ctx = retrieve_aware_context("我在浏览的每日大赛投稿页面是什么东西?")
    assert "### 当前浏览器" in ctx
    assert "时间线 · 最近 3 小时" in ctx or "最近 3 小时" in ctx
    assert "当前本地时间:" in ctx
    assert "发生时刻/时段是最重要元数据" in ctx
    assert "每日大赛" in ctx
    assert "51cg1.com" in ctx
    assert "GitHub" in ctx
    assert "后台选中" in ctx
    assert "前台:" not in ctx
    assert "30min" not in ctx
    assert "后台选中标签不等于浏览" in ctx


def test_retrieve_aware_context_redacts_sensitive_open_tabs(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from localagent.aware.browser_tabs import BrowserNow
    from localagent.aware.episode import retrieve_aware_context

    snap = BrowserNow(
        browser="chrome",
        windows=1,
        tabs=2,
        active_title="Secret Adult Title",
        active_url="https://www.pornhub.com/video/123",
        frontmost=False,
        items=[
            {
                "title": "Secret Adult Title",
                "url": "https://www.pornhub.com/video/123",
                "active": "true",
            },
            {
                "title": "Other Secret",
                "url": "https://xvideos.com/watch/1",
                "active": "",
            },
        ],
    )
    monkeypatch.setattr(
        "localagent.aware.browser_tabs.collect_open_tabs",
        lambda: [snap],
    )
    ctx = retrieve_aware_context("我在看什么")
    assert "### 当前浏览器" in ctx
    assert "最近 3 小时" in ctx
    assert "敏感类标签" in ctx
    assert "后台选中" in ctx
    assert "Secret Adult Title" not in ctx
    assert "Other Secret" not in ctx
    assert "pornhub.com" not in ctx.lower()
    assert "不得因主题敏感拒答" in ctx
    assert "时段与时长" in ctx


def test_episode_card_includes_local_time_range() -> None:
    from localagent.aware.episode import AwareEpisode

    ep = AwareEpisode(
        id="t1",
        scene="sensitive_video",
        start="2026-07-18T14:00:00+00:00",
        end="2026-07-18T14:30:00+00:00",
        duration_min=30,
        source="browser",
        title="敏感类浏览（仅时长信号）",
        signals={"engagement": "dwell"},
    )
    card = ep.to_card_line()
    assert "30min" in card
    assert "敏感类" in card
    assert "–" in card  # local start–end span
    # Period label leads the card (e.g. [晚上 22:00–22:30])
    assert card.startswith("[")
    assert any(
        p in card for p in ("清晨", "上午", "下午", "傍晚", "晚上", "深夜")
    )
    # month-day present (timezone-local; still same calendar day in most zones)
    assert "07-18" in card or "07-19" in card or ":" in card


def test_retrieve_aware_context_sensitive_episode_keeps_time(
    aware_home: Path,
) -> None:
    from localagent.aware.episode import AwareEpisode, append_episodes, retrieve_aware_context

    append_episodes(
        [
            AwareEpisode(
                id="sens1",
                scene="sensitive_video",
                start="2026-07-18T14:00:00+00:00",
                end="2026-07-18T14:30:00+00:00",
                duration_min=30,
                source="browser",
                title="敏感类浏览（仅时长信号）",
                signals={"engagement": "dwell"},
            )
        ]
    )
    ctx = retrieve_aware_context("敏感类浏览多久", since_hours=48)
    assert "敏感类浏览" in ctx
    assert "30min" in ctx
    assert "pornhub" not in ctx.lower()
    assert "不得因主题敏感拒答" in ctx
    assert "–" in ctx


def test_digest_browser_now_redacts_sensitive(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from localagent.aware.browser_tabs import BrowserNow
    from localagent.aware.digest import _render_browser_now

    snap = BrowserNow(
        browser="chrome",
        windows=1,
        tabs=2,
        active_title="Secret Adult Title",
        active_url="https://www.pornhub.com/video/123",
        frontmost=True,
        items=[
            {
                "title": "Secret Adult Title",
                "url": "https://www.pornhub.com/video/123",
                "active": "true",
            },
            {
                "title": "Other Secret",
                "url": "https://xvideos.com/watch/1",
                "active": "",
            },
        ],
    )
    monkeypatch.setattr(
        "localagent.aware.digest.collect_open_tabs",
        lambda: [snap],
    )
    lines = _render_browser_now()
    text = "\n".join(lines)
    assert "敏感类标签" in text
    assert "Secret Adult Title" not in text
    assert "Other Secret" not in text
    assert "pornhub.com" not in text.lower()
    assert "xvideos.com" not in text.lower()


def test_digest_browser_events_redact_sensitive_hosts(aware_home: Path) -> None:
    from localagent.aware.digest import _summarize_browser_events

    events = [
        AwareEvent(
            source="browser",
            kind="browser.summary",
            title="浏览摘要: www.pornhub.com×2",
            data={
                "hosts": [
                    {
                        "host": "www.pornhub.com",
                        "count": 2,
                        "sample": "Secret Title",
                    },
                    {"host": "github.com", "count": 3, "sample": "LocalAgent"},
                ],
                "visit_count": 5,
            },
        ),
        AwareEvent(
            source="browser",
            kind="browser.active",
            title="正在看: Secret",
            data={
                "active_url": "https://www.pornhub.com/v/1",
                "active_title": "Secret Title Leak",
                "host": "www.pornhub.com",
                "engagement": "dwell",
                "dwell_sec": 1800,
                "viewing": True,
            },
        ),
    ]
    lines = _summarize_browser_events(events)
    text = "\n".join(lines)
    assert "敏感类" in text
    assert "github.com" in text
    assert "Secret Title" not in text
    assert "pornhub" not in text.lower()
    assert "正在看: 敏感类浏览" in text
    assert "30min" in text


def test_classify_engagement_tiers() -> None:
    from localagent.aware.engagement import classify_engagement

    assert classify_engagement(ticks_seen=1, dwell_sec=900) == "glance"
    assert classify_engagement(ticks_seen=2, dwell_sec=1800, idle_seconds=600) == "dwell"
    assert classify_engagement(ticks_seen=2, dwell_sec=1800, idle_seconds=30) == "engage"
    assert (
        classify_engagement(ticks_seen=2, dwell_sec=1800, has_interaction=True) == "engage"
    )
    assert classify_engagement(ticks_seen=2, dwell_sec=1800, visit_count=5) == "engage"


def test_apps_engagement_glance_then_dwell(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from localagent.aware.profile import SourceGrant
    from localagent.aware.sensors.apps import AppsSensor

    def _snap(app: str, title: str) -> dict:
        return {
            "app": app,
            "bundle_id": "com.example",
            "window_title": title,
            "media_title": "",
            "media_artist": "",
            "media_app": "",
            "error": "",
        }

    monkeypatch.setattr("localagent.aware.sensors.apps.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "localagent.aware.sensors.apps._collect_focus_snapshot",
        lambda: _snap("Safari", "Tab A"),
    )
    monkeypatch.setattr("localagent.aware.sensors.apps._idle_seconds", lambda: 400.0)

    sensor = AppsSensor(SourceGrant(granted=True))
    e1, c1 = sensor.collect({})
    assert e1[0].data["engagement"] == "glance"

    # switch away → new focus is still glance
    monkeypatch.setattr(
        "localagent.aware.sensors.apps._collect_focus_snapshot",
        lambda: _snap("Notes", "Shopping"),
    )
    e2, c2 = sensor.collect(c1)
    assert e2[0].data["engagement"] == "glance"
    assert e2[0].data["ticks_seen"] == 1

    # stay on Notes with high idle → dwell
    e3, _ = sensor.collect(c2)
    assert e3[0].data["ticks_seen"] == 2
    assert e3[0].data["engagement"] == "dwell"


def test_browser_active_dwell_and_engage(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from localagent.aware.browser_tabs import BrowserNow
    from localagent.aware.profile import SourceGrant
    from localagent.aware.sensors.browser import BrowserSensor

    monkeypatch.setattr(
        "localagent.aware.sensors.browser.discover_browser_dbs",
        lambda: [],
    )
    snap = BrowserNow(
        browser="chrome",
        windows=1,
        tabs=1,
        active_title="Daily Contest",
        active_url="https://51cg1.com/category/mrds/",
        frontmost=True,
        items=[
            {
                "title": "Daily Contest",
                "url": "https://51cg1.com/category/mrds/",
                "active": "true",
            }
        ],
    )
    monkeypatch.setattr(
        "localagent.aware.browser_tabs.collect_open_tabs",
        lambda: [snap],
    )
    sensor = BrowserSensor(SourceGrant(granted=True))
    e1, c1 = sensor.collect({})
    actives = [e for e in e1 if e.kind == "browser.active"]
    assert len(actives) == 1
    assert actives[0].data["engagement"] == "glance"
    assert actives[0].data["viewing"] is True
    assert "正在看" in actives[0].title

    e2, c2 = sensor.collect(c1)
    actives2 = [e for e in e2 if e.kind == "browser.active"]
    assert actives2[0].data["ticks_seen"] == 2
    assert actives2[0].data["engagement"] == "dwell"

    # Same URL + high visit_count in summary path: inject via host_counts by
    # mocking active session classify with visit_count through a synthetic collect.
    # Simulate engage by calling classify on the second heartbeat with visits —
    # instead bump visits via monkeypatched _host_visit_count.
    monkeypatch.setattr(
        "localagent.aware.sensors.browser._host_visit_count",
        lambda host_counts, host: 5,
    )
    e3, _ = sensor.collect(c2)
    actives3 = [e for e in e3 if e.kind == "browser.active"]
    assert actives3[0].data["engagement"] == "engage"
    assert actives3[0].data["ticks_seen"] == 3


def test_browser_background_selected_does_not_accumulate_dwell(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cursor frontmost + Chrome background: same URL must not grow ticks/dwell."""
    from localagent.aware.browser_tabs import BrowserNow
    from localagent.aware.profile import SourceGrant
    from localagent.aware.sensors.browser import BrowserSensor

    monkeypatch.setattr(
        "localagent.aware.sensors.browser.discover_browser_dbs",
        lambda: [],
    )
    snap = BrowserNow(
        browser="chrome",
        windows=1,
        tabs=1,
        active_title="Adult Site",
        active_url="https://51cg1.com/category/mrds/",
        frontmost=False,
        items=[
            {
                "title": "Adult Site",
                "url": "https://51cg1.com/category/mrds/",
                "active": "true",
            }
        ],
    )
    monkeypatch.setattr(
        "localagent.aware.browser_tabs.collect_open_tabs",
        lambda: [snap],
    )
    sensor = BrowserSensor(SourceGrant(granted=True))
    e1, c1 = sensor.collect({})
    selected = [e for e in e1 if e.kind == "browser.selected"]
    assert len(selected) == 1
    assert selected[0].data["viewing"] is False
    assert selected[0].data["ticks_seen"] == 0
    assert selected[0].data["dwell_sec"] == 0
    assert selected[0].data["engagement"] == "glance"
    assert "选中标签" in selected[0].title
    assert not any(e.kind == "browser.active" for e in e1)

    e2, c2 = sensor.collect(c1)
    selected2 = [e for e in e2 if e.kind == "browser.selected"]
    assert selected2[0].data["ticks_seen"] == 0
    assert selected2[0].data["dwell_sec"] == 0
    assert selected2[0].data["engagement"] == "glance"
    assert c2["active_session"]["viewing"] is False


def test_browser_resume_viewing_after_background_freeze(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Background gap must not inflate ticks; resume continues from frozen value."""
    from localagent.aware.browser_tabs import BrowserNow
    from localagent.aware.profile import SourceGrant
    from localagent.aware.sensors.browser import BrowserSensor

    monkeypatch.setattr(
        "localagent.aware.sensors.browser.discover_browser_dbs",
        lambda: [],
    )

    def _snap(*, frontmost: bool) -> BrowserNow:
        return BrowserNow(
            browser="chrome",
            windows=1,
            tabs=1,
            active_title="HN",
            active_url="https://news.ycombinator.com/",
            frontmost=frontmost,
            items=[
                {
                    "title": "HN",
                    "url": "https://news.ycombinator.com/",
                    "active": "true",
                }
            ],
        )

    monkeypatch.setattr(
        "localagent.aware.browser_tabs.collect_open_tabs",
        lambda: [_snap(frontmost=True)],
    )
    sensor = BrowserSensor(SourceGrant(granted=True))
    _e1, c1 = sensor.collect({})
    _e2, c2 = sensor.collect(c1)
    assert c2["active_session"]["ticks_seen"] == 2
    assert c2["active_session"]["engagement"] == "dwell"

    # Background for two ticks — freeze
    monkeypatch.setattr(
        "localagent.aware.browser_tabs.collect_open_tabs",
        lambda: [_snap(frontmost=False)],
    )
    _e3, c3 = sensor.collect(c2)
    _e4, c4 = sensor.collect(c3)
    assert c4["active_session"]["ticks_seen"] == 2
    assert c4["active_session"]["viewing"] is False

    # Back to frontmost — resume from 2 → 3 (not 2 + background ticks)
    monkeypatch.setattr(
        "localagent.aware.browser_tabs.collect_open_tabs",
        lambda: [_snap(frontmost=True)],
    )
    e5, c5 = sensor.collect(c4)
    actives = [e for e in e5 if e.kind == "browser.active"]
    assert actives[0].data["ticks_seen"] == 3
    assert c5["active_session"]["viewing"] is True


def test_browser_selected_events_do_not_create_dwell_episodes(
    aware_home: Path,
) -> None:
    from localagent.aware.episode import build_episodes_from_events

    events = [
        AwareEvent(
            source="browser",
            kind="browser.selected",
            title="选中标签: Adult",
            data={
                "active_url": "https://51cg1.com/x",
                "active_title": "Adult",
                "host": "51cg1.com",
                "scene": "browser",
                "ticks_seen": 0,
                "dwell_sec": 0,
                "engagement": "glance",
                "viewing": False,
            },
        )
    ]
    eps = build_episodes_from_events(events)
    assert eps == []


def test_format_browser_now_context_hides_dwell_when_background(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from localagent.aware.browser_tabs import BrowserNow
    from localagent.aware.episode import _format_browser_now_context
    from localagent.aware.store import save_cursors

    snap = BrowserNow(
        browser="chrome",
        windows=1,
        tabs=1,
        active_title="Adult",
        active_url="https://51cg1.com/x",
        frontmost=False,
        items=[{"title": "Adult", "url": "https://51cg1.com/x", "active": "1"}],
    )
    monkeypatch.setattr(
        "localagent.aware.browser_tabs.collect_open_tabs",
        lambda: [snap],
    )
    save_cursors(
        {
            "browser": {
                "active_session": {
                    "active_url": "https://51cg1.com/x",
                    "engagement": "dwell",
                    "dwell_sec": 1800,
                    "viewing": False,
                }
            }
        }
    )
    lines = _format_browser_now_context()
    text = "\n".join(lines)
    assert "后台选中" in text
    assert "前台" not in text
    assert "dwell" not in text
    assert "30min" not in text


def test_episode_cards_show_engagement(aware_home: Path) -> None:
    from localagent.aware.episode import build_episodes_from_events

    events = [
        AwareEvent(
            source="apps",
            kind="apps.focus",
            title="Cursor · LocalAgent",
            data={
                "app": "Cursor",
                "window_title": "LocalAgent",
                "scene": "coding",
                "focus_key": "Cursor|LocalAgent|",
                "ticks_seen": 2,
                "dwell_sec": 1800,
                "engagement": "dwell",
                "idle_seconds": 300,
            },
        ),
        AwareEvent(
            source="terminal",
            kind="terminal.cmd",
            title="pytest -q",
            data={"command": "pytest -q"},
        ),
        AwareEvent(
            source="browser",
            kind="browser.active",
            title="正在看: HN",
            data={
                "active_url": "https://news.ycombinator.com/",
                "active_title": "HN",
                "host": "news.ycombinator.com",
                "scene": "browser",
                "ticks_seen": 2,
                "dwell_sec": 1800,
                "engagement": "dwell",
                "sample": "HN",
                "viewing": True,
            },
        ),
    ]
    eps = build_episodes_from_events(events)
    apps_eps = [e for e in eps if e.source == "apps"]
    assert apps_eps
    assert apps_eps[0].signals.get("engagement") == "engage"  # terminal proxy
    assert apps_eps[0].duration_min == 30.0
    assert "/engage]" in apps_eps[0].to_card_line() or "[coding/engage]" in apps_eps[0].to_card_line()

    browser_eps = [e for e in eps if e.source == "browser" and e.signals.get("active_url")]
    assert browser_eps
    assert browser_eps[0].signals.get("engagement") == "dwell"
    assert "[browser/dwell]" in browser_eps[0].to_card_line()


def test_sensitive_browser_active_redacts_title(aware_home: Path) -> None:
    from localagent.aware.episode import build_episodes_from_events

    events = [
        AwareEvent(
            source="browser",
            kind="browser.active",
            title="正在看: Secret",
            data={
                "active_url": "https://www.pornhub.com/v/1",
                "active_title": "Secret Title Leak",
                "host": "www.pornhub.com",
                "scene": "sensitive_video",
                "ticks_seen": 2,
                "dwell_sec": 1800,
                "engagement": "dwell",
                "sample": "Secret Title Leak",
                "viewing": True,
            },
        )
    ]
    eps = build_episodes_from_events(events)
    assert len(eps) == 1
    assert "Secret" not in eps[0].title
    assert "Secret" not in eps[0].to_card_line()
    assert eps[0].signals.get("engagement") == "dwell"


def test_attention_score_ranks_coding_over_browser_and_legacy() -> None:
    from localagent.aware.engagement import attention_score
    from localagent.aware.episode import AwareEpisode, rank_episodes_by_attention

    cursor = attention_score(
        source="apps",
        scene="coding",
        title="Cursor",
        duration_min=30,
        signals={"engagement": "engage"},
    )
    bilibili = attention_score(
        source="browser",
        scene="video",
        title="正在看: bilibili",
        duration_min=15,
        signals={"engagement": "dwell", "viewing": True},
    )
    legacy = attention_score(
        source="browser",
        scene="browser",
        title="前台页: adult",
        duration_min=30,
        signals={"engagement": "dwell"},
    )
    bg = attention_score(
        source="browser",
        scene="browser",
        title="选中标签: adult",
        duration_min=0,
        signals={"engagement": "glance", "viewing": False},
    )
    assert cursor > bilibili > legacy
    assert bilibili > bg

    ranked = rank_episodes_by_attention(
        [
            AwareEpisode(
                id="1",
                scene="browser",
                start="t",
                end="t",
                duration_min=30,
                source="browser",
                title="前台页: adult",
                signals={"engagement": "dwell"},
            ),
            AwareEpisode(
                id="2",
                scene="coding",
                start="t",
                end="t",
                duration_min=30,
                source="apps",
                title="Cursor",
                signals={"engagement": "engage"},
            ),
            AwareEpisode(
                id="3",
                scene="video",
                start="t",
                end="t",
                duration_min=15,
                source="browser",
                title="正在看: bilibili",
                signals={"engagement": "dwell", "viewing": True},
            ),
        ],
        limit=5,
    )
    assert [e.id for e in ranked] == ["2", "3"]


def test_llm_summarize_facts_strips_instruction_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from localagent.aware import summary as summary_mod

    class _Router:
        def chat(self, *_a, **_k):
            return (
                "主要：在 Cursor 写代码\n"
                "未授权或无数据的源一笔带过；不要编造事实卡没有的内容；每行一句。\n"
                "其次：看了 Bilibili\n"
            )

    monkeypatch.setattr(
        "localagent.models.router.get_model_router",
        lambda: _Router(),
    )
    text = summary_mod.llm_summarize_facts("apps: 当前: Cursor\nbrowser: 当前: 正在看=bilibili")
    assert text is not None
    assert "未授权" not in text
    assert "不要编造" not in text
    assert "每行一句" not in text
    assert "Cursor" in text
    assert "Bilibili" in text


def test_fact_card_source_order_apps_before_browser(aware_home: Path) -> None:
    from localagent.aware.summary import build_fact_card

    grant_source("apps")
    grant_source("browser")
    card = build_fact_card(mode="now")
    apps_i = card.find("apps:")
    browser_i = card.find("browser:")
    assert apps_i >= 0
    assert browser_i >= 0
    assert apps_i < browser_i


def test_overview_hides_legacy_foreground_episode(aware_home: Path) -> None:
    from localagent.aware.episode import AwareEpisode, append_episodes
    from localagent.aware.types import utc_now

    ts = utc_now()
    append_episodes(
        [
            AwareEpisode(
                id="legacy",
                scene="browser",
                start=ts,
                end=ts,
                duration_min=30,
                source="browser",
                title="前台页: 每日大赛 adult",
                entities=["51cg1.com"],
                signals={"engagement": "dwell"},
            ),
            AwareEpisode(
                id="cursor",
                scene="coding",
                start=ts,
                end=ts,
                duration_min=30,
                source="apps",
                title="Cursor · LocalAgent",
                entities=["Cursor"],
                signals={"engagement": "engage"},
            ),
        ]
    )
    text = format_view(mode="now", use_llm=False)
    assert "Cursor · LocalAgent" in text
    assert "前台页" not in text
    assert "每日大赛" not in text
    assert "主注意力" in text


def test_browser_active_without_viewing_flag_skipped(aware_home: Path) -> None:
    from localagent.aware.episode import build_episodes_from_events

    events = [
        AwareEvent(
            source="browser",
            kind="browser.active",
            title="前台页: Old",
            data={
                "active_url": "https://example.com/",
                "active_title": "Old",
                "host": "example.com",
                "scene": "browser",
                "ticks_seen": 2,
                "dwell_sec": 1800,
                "engagement": "dwell",
                # no viewing field — must not count as viewing
            },
        )
    ]
    assert build_episodes_from_events(events) == []


def test_rebuild_episodes_drops_legacy(aware_home: Path) -> None:
    from localagent.aware.episode import (
        AwareEpisode,
        append_episodes,
        load_episodes,
        maybe_rebuild_stale_episodes,
        rebuild_episodes_from_events,
    )
    from localagent.aware.types import utc_now

    ts = utc_now()
    append_episodes(
        [
            AwareEpisode(
                id="legacy",
                scene="browser",
                start=ts,
                end=ts,
                duration_min=30,
                source="browser",
                title="前台页: adult",
                signals={"engagement": "dwell"},
            ),
            AwareEpisode(
                id="cursor",
                scene="coding",
                start=ts,
                end=ts,
                duration_min=30,
                source="apps",
                title="Cursor · keep",
                signals={"engagement": "engage"},
            ),
        ]
    )
    dropped = maybe_rebuild_stale_episodes(since_hours=24)
    assert dropped >= 1
    eps = load_episodes(limit=50)
    assert all(not (e.title or "").startswith("前台页:") for e in eps)
    assert any(e.title == "Cursor · keep" for e in eps)

    append_events(
        [
            AwareEvent(
                source="apps",
                kind="apps.focus",
                title="Cursor",
                ts=ts,
                data={
                    "app": "Cursor",
                    "window_title": "LocalAgent",
                    "scene": "coding",
                    "focus_key": "Cursor|LocalAgent|",
                    "ticks_seen": 2,
                    "dwell_sec": 1800,
                    "engagement": "dwell",
                },
            )
        ]
    )
    n = rebuild_episodes_from_events(since_hours=24)
    assert n >= 1
    eps2 = load_episodes(limit=50)
    assert any(e.source == "apps" for e in eps2)


def test_browser_active_episode_uses_focus_since(aware_home: Path) -> None:
    from localagent.aware.episode import build_episodes_from_events

    events = [
        AwareEvent(
            source="browser",
            kind="browser.active",
            title="正在看: HN",
            ts="2026-07-18T16:00:00+00:00",
            data={
                "active_url": "https://news.ycombinator.com/",
                "active_title": "HN",
                "host": "news.ycombinator.com",
                "scene": "browser",
                "focus_since": "2026-07-18T14:00:00+00:00",
                "ticks_seen": 8,
                "dwell_sec": 7200,
                "engagement": "dwell",
                "sample": "HN",
                "viewing": True,
            },
        )
    ]
    eps = build_episodes_from_events(events)
    assert len(eps) == 1
    assert eps[0].start == "2026-07-18T14:00:00+00:00"
    assert eps[0].end == "2026-07-18T16:00:00+00:00"
    card = eps[0].to_card_line()
    assert "–" in card
    assert any(p in card for p in ("清晨", "上午", "下午", "傍晚", "晚上", "深夜"))


def test_browser_summary_episode_uses_visit_span(aware_home: Path) -> None:
    from localagent.aware.episode import build_episodes_from_events

    events = [
        AwareEvent(
            source="browser",
            kind="browser.summary",
            title="浏览摘要: github.com×3",
            ts="2026-07-18T16:00:00+00:00",
            data={
                "hosts": [
                    {"host": "github.com", "count": 3, "sample": "Pull requests"}
                ],
                "visit_count": 3,
                "first_visit": "2026-07-18T02:00:00+00:00",
                "last_visit": "2026-07-18T04:00:00+00:00",
                "hour_buckets": [{"hour": 10, "count": 2}, {"hour": 12, "count": 1}],
            },
        )
    ]
    eps = build_episodes_from_events(events)
    assert len(eps) == 1
    assert eps[0].start == "2026-07-18T02:00:00+00:00"
    assert eps[0].end == "2026-07-18T04:00:00+00:00"
    assert eps[0].signals.get("hour_buckets")


def test_hypothesis_video_uses_period(aware_home: Path) -> None:
    from localagent.aware.episode import AwareEpisode
    from localagent.aware.hypothesis import generate_hypotheses_from_episodes

    hyps = generate_hypotheses_from_episodes(
        [
            AwareEpisode(
                id="v1",
                scene="video",
                start="2026-07-18T14:00:00+00:00",
                end="2026-07-18T15:00:00+00:00",
                duration_min=60,
                source="browser",
                title="Bilibili",
                entities=["bilibili.com"],
                signals={"engagement": "dwell"},
            )
        ]
    )
    assert hyps
    claim = hyps[0].claim
    assert "看视频" in claim
    assert "最近花了不少时间" not in claim
    assert any(p in claim for p in ("清晨", "上午", "下午", "傍晚", "晚上", "深夜", "白天"))


def test_engine_visit_to_iso() -> None:
    from localagent.aware.sensors.browser import _engine_visit_to_iso

    # Chromium: microseconds since 1601-01-01 → 2020-01-01 UTC
    chrome_ts = 13_222_310_400_000_000
    iso = _engine_visit_to_iso("chromium", chrome_ts)
    assert "2020-01-01" in iso

    ff = _engine_visit_to_iso("firefox", 1_577_836_800_000_000)  # 2020-01-01 UTC
    assert "2020-01-01" in ff
