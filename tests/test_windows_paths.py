"""Windows-oriented path fallbacks (schedules, kb link/copy)."""

from __future__ import annotations

import os

import pytest


def test_news_schedule_unsupported_on_windows(monkeypatch):
    from localagent.news import schedule as sched
    from localagent.news.profile import NewsProfile

    monkeypatch.setattr(sched.platform, "system", lambda: "Windows")
    monkeypatch.setattr(sched, "load_news_profile", lambda: NewsProfile())
    monkeypatch.setattr(sched, "save_news_profile", lambda _p: None)

    st = sched.schedule_status()
    assert st.enabled is False
    assert st.backend == "none"
    assert "Windows" in st.detail

    with pytest.raises(RuntimeError, match="Windows"):
        sched.enable_schedule()

    off = sched.disable_schedule()
    assert off.enabled is False
    assert "Windows" in off.detail


def test_prepare_symlink_falls_back_to_copy(tmp_path, monkeypatch):
    from localagent.ingest import add_file as af

    kb = tmp_path / "kb"
    kb.mkdir()
    src = tmp_path / "note.md"
    src.write_text("hello kb\n", encoding="utf-8")

    monkeypatch.setattr(af.config, "KB_DIR", kb)
    monkeypatch.setattr(af.config, "SUPPORTED_SUFFIXES", {".md"})
    monkeypatch.setattr(af.config, "ensure_data_dirs", lambda: None)
    monkeypatch.setattr(af, "is_sensitive_path", lambda _p: False)

    def _fail_symlink(_src, _dst):
        raise OSError("symlink privilege not held")

    monkeypatch.setattr(af.os, "symlink", _fail_symlink)

    source, target = af.prepare_symlink(src)
    assert source == src.resolve()
    assert target == kb / "note.md"
    assert target.is_file()
    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8") == "hello kb\n"


def test_prepare_symlink_prefers_symlink_when_available(tmp_path, monkeypatch):
    from localagent.ingest import add_file as af

    kb = tmp_path / "kb"
    kb.mkdir()
    src = tmp_path / "note.md"
    src.write_text("linked\n", encoding="utf-8")

    monkeypatch.setattr(af.config, "KB_DIR", kb)
    monkeypatch.setattr(af.config, "SUPPORTED_SUFFIXES", {".md"})
    monkeypatch.setattr(af.config, "ensure_data_dirs", lambda: None)
    monkeypatch.setattr(af, "is_sensitive_path", lambda _p: False)

    # Skip on platforms where the real os.symlink already fails.
    try:
        probe = tmp_path / "probe-link"
        os.symlink(src, probe)
        probe.unlink()
    except OSError:
        pytest.skip("symlink not available on this host")

    _source, target = af.prepare_symlink(src)
    assert target.is_symlink()
    assert target.read_text(encoding="utf-8") == "linked\n"
