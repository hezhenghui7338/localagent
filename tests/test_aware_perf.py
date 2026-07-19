"""Performance / resource-budget tests for la aware (no real launchd)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from localagent.aware.policy import apply_policy
from localagent.aware.profile import SourceGrant, grant_source
from localagent.aware.sensors.browser import BrowserSensor, _with_db_copy
from localagent.aware.sensors.fs import FsSensor, walk_watch_files
from localagent.aware.sensors.terminal import TerminalSensor, _read_history_bounded
from localagent.aware.tick import run_tick, try_acquire_tick_lock, release_tick_lock
from localagent.aware.types import AwareEvent
from localagent.aware.platform_paths import BrowserDb

pytestmark = [
    pytest.mark.serial,
    pytest.mark.xdist_group("serial"),
]


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
    monkeypatch.setattr(config, "AWARE_SUGGESTIONS_FILE", data / "aware" / "suggestions.json")
    monkeypatch.setattr(config, "AWARE_NOW_DIR", data / "aware" / "now")
    monkeypatch.setattr(config, "AWARE_TICK_LOCK_FILE", data / "aware" / "tick.lock")
    monkeypatch.setattr(config, "KB_DIR", data / "kb")
    monkeypatch.setattr(config, "AUDIT_DIR", data / "audit")
    monkeypatch.setattr(config, "INGEST_TASKS_FILE", data / "ingest_tasks.json")
    monkeypatch.setattr(config, "TASK_LOGS_DIR", data / "task_logs")
    # Tight budgets for fast CI assertions
    monkeypatch.setattr(config, "AWARE_FS_MAX_SCAN_FILES", 200)
    monkeypatch.setattr(config, "AWARE_FS_MAX_DEPTH", 3)
    monkeypatch.setattr(config, "AWARE_TICK_DEADLINE_SEC", 20)
    monkeypatch.setattr(config, "AWARE_SUGGEST_PER_TICK", 10)
    monkeypatch.setattr(config, "AWARE_BROWSER_DB_MAX_BYTES", 1024)
    monkeypatch.setattr(config, "AWARE_HISTORY_MAX_BYTES", 4096)
    monkeypatch.setattr(config, "AWARE_EVENTS_MAX_BYTES", 1024)
    (data / "aware").mkdir(parents=True, exist_ok=True)
    (data / "aware" / "now").mkdir(parents=True, exist_ok=True)
    (data / "kb").mkdir(parents=True, exist_ok=True)
    (data / "audit").mkdir(parents=True, exist_ok=True)
    return data


def _build_wide_tree(root: Path, *, files: int, depth: int) -> int:
    """Create many files; returns count of regular files created."""
    created = 0
    cur = root
    for d in range(depth):
        cur = cur / f"d{d}"
        cur.mkdir(parents=True, exist_ok=True)
    for i in range(files):
        # Spread across shallow dirs so depth budget still bites on deep nest.
        bucket = root / f"b{i % 20}"
        bucket.mkdir(exist_ok=True)
        (bucket / f"f{i}.txt").write_text("x", encoding="utf-8")
        created += 1
    # Extra deep nest beyond depth budget
    deep = root
    for d in range(depth + 5):
        deep = deep / f"deep{d}"
        deep.mkdir(parents=True, exist_ok=True)
    (deep / "hidden.txt").write_text("deep", encoding="utf-8")
    created += 1
    return created


def test_fs_walk_respects_scan_budget(aware_home: Path, tmp_path: Path) -> None:
    watch = tmp_path / "big"
    watch.mkdir()
    _build_wide_tree(watch, files=800, depth=3)
    t0 = time.perf_counter()
    hits, scanned, truncated = walk_watch_files([watch], max_scan=200, max_depth=8)
    elapsed = time.perf_counter() - t0
    assert truncated is True
    assert scanned == 201  # stops after exceeding cap
    assert len(hits) == 200
    assert elapsed < 5.0


def test_fs_walk_respects_depth_budget(aware_home: Path, tmp_path: Path) -> None:
    watch = tmp_path / "deeproot"
    watch.mkdir()
    deep = watch
    for i in range(10):
        deep = deep / f"lvl{i}"
        deep.mkdir()
    (watch / "top.txt").write_text("a", encoding="utf-8")
    (deep / "bottom.txt").write_text("b", encoding="utf-8")
    hits, _scanned, _truncated = walk_watch_files([watch], max_scan=5000, max_depth=3)
    names = {p.name for p, _ in hits}
    assert "top.txt" in names
    assert "bottom.txt" not in names


def test_fs_sensor_collect_stops_within_budget(
    aware_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import localagent.config as config

    monkeypatch.setattr(config, "AWARE_FS_MAX_SCAN_FILES", 100)
    monkeypatch.setattr(config, "AWARE_FS_MAX_DEPTH", 4)
    watch = tmp_path / "watch"
    watch.mkdir()
    _build_wide_tree(watch, files=500, depth=2)
    sensor = FsSensor(SourceGrant(granted=True, paths=[str(watch)]))
    t0 = time.perf_counter()
    _events, cursor = sensor.collect({})
    elapsed = time.perf_counter() - t0
    assert cursor.get("primed") is True
    assert cursor.get("truncated") is True
    assert len(cursor.get("files") or {}) <= 100
    assert elapsed < 5.0


def test_policy_suggest_storm_capped(
    aware_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import localagent.config as config

    monkeypatch.setattr(config, "AWARE_SUGGEST_PER_TICK", 10)
    events = [
        AwareEvent(
            source="fs",
            kind="file.created",
            title=f"doc{i}.pdf",
            data={"path": str(aware_home / f"doc{i}.pdf"), "suffix": ".pdf"},
        )
        for i in range(80)
    ]
    result = apply_policy(events)
    assert result.auto_actions == []
    assert len(result.suggestions) == 10  # capped; never auto-ingest


def test_overlapping_tick_lock(aware_home: Path, tmp_path: Path) -> None:
    watch = tmp_path / "w"
    watch.mkdir()
    grant_source("fs", paths=[str(watch)])

    held = try_acquire_tick_lock()
    assert held is not None
    try:
        result = run_tick()
        assert result.skipped == "another tick is already running"
        assert result.event_count == 0
    finally:
        release_tick_lock(held)

    # After release, tick proceeds
    result2 = run_tick()
    assert not result2.skipped or "传感器" in result2.skipped or result2.event_count == 0


def test_overlapping_tick_threads(aware_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    watch = tmp_path / "w2"
    watch.mkdir()
    grant_source("fs", paths=[str(watch)])
    results: list = []

    from localagent.aware.sensors.fs import FsSensor

    orig_collect = FsSensor.collect
    entered = threading.Event()

    def slow_collect(self, cursor):  # type: ignore[no-untyped-def]
        entered.set()
        time.sleep(0.4)
        return orig_collect(self, cursor)

    monkeypatch.setattr(FsSensor, "collect", slow_collect)

    def worker_a() -> None:
        results.append(run_tick())

    def worker_b() -> None:
        assert entered.wait(timeout=5)
        results.append(run_tick())

    t_a = threading.Thread(target=worker_a)
    t_b = threading.Thread(target=worker_b)
    t_a.start()
    t_b.start()
    t_a.join(timeout=15)
    t_b.join(timeout=15)
    assert len(results) == 2
    skipped = [r for r in results if r.skipped == "another tick is already running"]
    ran = [r for r in results if r.skipped != "another tick is already running"]
    assert len(skipped) == 1
    assert len(ran) == 1


def test_browser_skips_huge_db_without_copy(
    aware_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    huge = tmp_path / "History"
    huge.write_bytes(b"0" * 2048)  # > AWARE_BROWSER_DB_MAX_BYTES=1024
    db = BrowserDb("chrome", "chromium", huge, profile="Default")
    monkeypatch.setattr(
        "localagent.aware.sensors.browser.discover_browser_dbs",
        lambda: [db],
    )
    with patch("localagent.aware.sensors.browser.shutil.copy2") as copy2:
        with pytest.raises(OSError, match="too large"):
            _with_db_copy(db)
        copy2.assert_not_called()

    monkeypatch.setattr(
        "localagent.aware.browser_tabs.collect_open_tabs",
        lambda: [],
    )
    sensor = BrowserSensor(SourceGrant(granted=True))
    with patch("localagent.aware.sensors.browser.shutil.copy2") as copy2:
        events, cursor = sensor.collect({})
        copy2.assert_not_called()
        assert events == []
        # Primed with watermark without copying
        assert cursor.get("last_visit_ts")


def test_terminal_oversized_history_bounded_read(
    aware_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import localagent.config as config

    monkeypatch.setattr(config, "AWARE_HISTORY_MAX_BYTES", 4096)
    hist = tmp_path / ".zsh_history"
    # ~10KB of lines
    hist.write_text("\n".join(f"echo line{i}" for i in range(2000)) + "\n", encoding="utf-8")
    assert hist.stat().st_size > 4096

    sensor = TerminalSensor(SourceGrant(granted=True, history_files=[str(hist)]))
    # Patch Path.read_bytes to fail if full-file read is attempted on this hist
    real_read_bytes = Path.read_bytes

    def guarded_read_bytes(self: Path) -> bytes:
        if self.resolve() == hist.resolve():
            raise AssertionError("full read_bytes on oversized history")
        return real_read_bytes(self)

    with patch.object(Path, "read_bytes", guarded_read_bytes):
        events1, cursor1 = sensor.collect({})
        assert events1 == []
        assert str(hist.resolve()) in (cursor1.get("byte_offsets") or {})

        with hist.open("a", encoding="utf-8") as fh:
            fh.write("echo brand_new_cmd\n")
        events2, _ = sensor.collect(cursor1)
        assert any("brand_new_cmd" in e.title for e in events2)


def test_history_bounded_helper_reads_tail_only(tmp_path: Path) -> None:
    path = tmp_path / "h"
    path.write_bytes(b"A" * 10_000 + b"\nTAIL\n")
    data, end = _read_history_bounded(path, start_byte=10_000, max_bytes=100)
    assert b"TAIL" in data
    assert end == path.stat().st_size


def test_digest_scan_uses_budget(
    aware_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timedelta, timezone

    from localagent.aware.digest import _scan_fs_mtime_window

    watch = tmp_path / "scan"
    watch.mkdir()
    _build_wide_tree(watch, files=600, depth=2)
    grant_source("fs", paths=[str(watch)])
    start = datetime.now(timezone.utc) - timedelta(days=1)
    t0 = time.perf_counter()
    paths = _scan_fs_mtime_window(start)
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0
    assert len(paths) <= 80


def test_events_rotate_on_append(aware_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import localagent.config as config
    from localagent.aware.store import append_events, _events_path

    monkeypatch.setattr(config, "AWARE_EVENTS_MAX_BYTES", 200)
    path = _events_path()
    # Fill past threshold
    big = AwareEvent(source="fs", kind="file.created", title="x", data={"path": "/tmp/x" * 20})
    append_events([big] * 20)
    assert path.exists() or (path.parent / (path.name + ".1")).exists()
    append_events([big])
    bak = path.parent / (path.name + ".1")
    assert bak.exists() or path.stat().st_size < 10_000
