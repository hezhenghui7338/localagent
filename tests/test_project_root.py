"""Tests for runtime home / package-install path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from localagent import config
from localagent.resources import read_text


def test_packaged_resources_readable():
    assert read_text("env.example") is not None
    assert "LA_MODEL_SERVERS_FILE" in read_text("env.example")
    assert read_text("model_servers.yaml.example") is not None
    assert "provider: ollama" in read_text("model_servers.yaml.example")
    assert read_text("core_profile.example.json") is not None
    assert read_text("missing.example") is None


def test_resolve_project_root_honors_la_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "custom-home"
    monkeypatch.setenv("LA_HOME", str(home))
    monkeypatch.delenv("LA_PROJECT_ROOT", raising=False)
    assert config.resolve_project_root() == home.resolve()


def test_resolve_project_root_source_checkout():
    root = config.resolve_project_root()
    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "localagent").is_dir()
    assert config.IS_SOURCE_CHECKOUT is True


def test_resolve_project_root_installed_uses_user_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Wheel layout: config.py under site-packages → default ~/.localagent."""
    site = tmp_path / "site-packages" / "localagent"
    site.mkdir(parents=True)
    fake_config = site / "config.py"
    fake_config.write_text("# stub\n", encoding="utf-8")

    monkeypatch.delenv("LA_HOME", raising=False)
    monkeypatch.delenv("LA_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(config, "__file__", str(fake_config))

    expected = Path.home() / ".localagent"
    assert config.resolve_project_root() == expected.resolve()
