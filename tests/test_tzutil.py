"""Tests for LA_TZ / tzutil local wall clock."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from localagent.tzutil import local_now, local_today, reset_tz_cache, resolve_local_tz, to_local_dt


@pytest.fixture(autouse=True)
def _clear_tz_cache() -> None:
    reset_tz_cache()
    yield
    reset_tz_cache()


def test_resolve_local_tz_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LA_TZ", "Asia/Shanghai")
    tz = resolve_local_tz()
    assert str(tz) == "Asia/Shanghai"


def test_resolve_local_tz_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LA_TZ", "Not/A/Real/Zone")
    tz = resolve_local_tz()
    assert tz is not None


def test_to_local_dt_utc_to_shanghai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LA_TZ", "Asia/Shanghai")
    local = to_local_dt("2026-07-25T09:48:00+00:00")
    assert local is not None
    assert local.hour == 17
    assert local.minute == 48


def test_to_local_dt_preserves_plus8_wall_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LA_TZ", "Asia/Shanghai")
    local = to_local_dt("2026-07-18T06:00:00+08:00")
    assert local is not None
    assert local.hour == 6


def test_local_today_respects_la_tz(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LA_TZ", "Asia/Shanghai")
    fixed = datetime(2026, 7, 25, 16, 0, tzinfo=timezone.utc)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is None:
                return fixed.replace(tzinfo=None)
            return fixed.astimezone(tz)

    monkeypatch.setattr("localagent.tzutil.datetime", _FixedDatetime)
    reset_tz_cache()
    assert local_today().isoformat() == "2026-07-26"
    assert local_now().hour == 0
