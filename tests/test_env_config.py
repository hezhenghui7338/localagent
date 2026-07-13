"""Tests for LA_MODEL_SERVERS YAML file and env config CLI."""

from __future__ import annotations

import io
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from localagent import config, env_config
from localagent.cli import main
from localagent.model_servers import (
    ModelServer,
    compute_provider_priority,
    load_model_servers_from_file,
    parse_model_servers_json,
    write_model_servers_to_file,
)


@pytest.fixture
def config_setup(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    project = tmp_path / "project"
    project.mkdir()
    config_dir = project / "config"
    config_dir.mkdir()

    servers_yaml = textwrap.dedent(
        """
        - provider: ollama
          base_url: http://localhost:11434
          model: qwen3.5:4b
          timeout: 90
        - provider: minimax
          base_url: https://api.minimax.io/v1
          api_key: old-minimax-key
          model: MiniMax-M3
          timeout: 120
        - provider: openrouter
          base_url: https://openrouter.ai/api/v1
          api_key: ""
          model: anthropic/claude-sonnet-4
          timeout: 120
        """
    ).strip()
    yaml_path = config_dir / "model_servers.yaml"
    yaml_path.write_text(servers_yaml + "\n", encoding="utf-8")

    env_path = project / ".env"
    env_path.write_text("LA_MODEL_SERVERS_FILE=config/model_servers.yaml\n", encoding="utf-8")

    monkeypatch.setattr(config, "PROJECT_ROOT", project)
    monkeypatch.setenv("LA_ENV_FILE", str(env_path))
    return env_path, yaml_path


def test_load_model_servers_from_yaml(config_setup):
    _, yaml_path = config_setup
    servers = load_model_servers_from_file(yaml_path)
    assert [s.provider for s in servers] == ["ollama", "minimax", "openrouter"]
    assert servers[1].api_key == "old-minimax-key"


def test_write_model_servers_to_yaml(tmp_path: Path):
    path = tmp_path / "servers.yaml"
    servers = [
        ModelServer(provider="aiping", base_url="https://aiping.cn/api/v1", model="GLM-5.2", timeout=30),
    ]
    write_model_servers_to_file(path, servers)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert loaded[0]["provider"] == "aiping"


def test_parse_model_servers_json():
    raw = '[{"provider":"aiping","base_url":"https://aiping.cn/api/v1","model":"GLM-5.2","timeout":30}]'
    servers = parse_model_servers_json(raw)
    assert servers[0].provider == "aiping"


def test_compute_provider_priority_default_order():
    servers = [
        ModelServer(provider="ollama", model="qwen"),
        ModelServer(provider="aiping", model="GLM"),
    ]
    assert compute_provider_priority(servers, "") == ["ollama", "aiping"]


def test_add_model_server(config_setup):
    env_path, yaml_path = config_setup
    server = ModelServer(
        provider="aiping",
        base_url="https://aiping.cn/api/v1",
        api_key="",
        model="GLM-5.2",
        timeout=30,
    )
    path, was_update = env_config.add_model_server(server, env_path=env_path)
    assert path == yaml_path
    assert was_update is False
    names = [s.provider for s in env_config.read_model_servers(env_path)]
    assert names == ["ollama", "minimax", "openrouter", "aiping"]


def test_remove_model_server(config_setup):
    env_path, yaml_path = config_setup
    path, existed = env_config.remove_model_server("minimax", env_path=env_path)
    assert existed is True
    assert path == yaml_path
    names = [s.provider for s in env_config.read_model_servers(env_path)]
    assert "minimax" not in names


def test_set_server_api_key(config_setup):
    env_path, _ = config_setup
    env_config.set_server_api_key("openrouter", "sk-or-new", env_path=env_path)
    servers = env_config.read_model_servers(env_path)
    openrouter = next(s for s in servers if s.provider == "openrouter")
    assert openrouter.api_key == "sk-or-new"


def test_set_server_model(config_setup):
    env_path, _ = config_setup
    env_config.set_server_model("ollama", "llama3.2:3b", env_path=env_path)
    servers = env_config.read_model_servers(env_path)
    ollama = next(s for s in servers if s.provider == "ollama")
    assert ollama.model == "llama3.2:3b"


def test_set_server_model_rejects_auto(config_setup):
    env_path, _ = config_setup
    with pytest.raises(ValueError, match="具体路径"):
        env_config.set_server_model("auto", "x", env_path=env_path)


def test_init_model_servers_config(tmp_path: Path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    example = project / "config"
    example.mkdir()
    (example / "model_servers.yaml.example").write_text(
        "- provider: ollama\n  model: qwen3.5:4b\n  base_url: http://localhost:11434\n",
        encoding="utf-8",
    )
    env_path = project / ".env"
    monkeypatch.setattr(config, "PROJECT_ROOT", project)
    monkeypatch.setenv("LA_ENV_FILE", str(env_path))

    result = env_config.init_model_servers_config(env_path=env_path)
    assert result.config_path.is_file()
    assert result.created is True
    assert env_config.read_env_value(env_path, "LA_MODEL_SERVERS_FILE") == "config/model_servers.yaml"


def test_cli_config_list(config_setup, capsys):
    rc = main(["config", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "model_servers.yaml" in out
    assert "minimax" in out
    assert "ollama→minimax→openrouter" in out


def test_cli_config_add_json(config_setup, capsys):
    payload = '{"provider":"aiping","base_url":"https://aiping.cn/api/v1","api_key":"","model":"GLM-5.2","timeout":30}'
    rc = main(["config", "add", payload])
    assert rc == 0
    servers = env_config.read_model_servers(config_setup[0])
    assert any(s.provider == "aiping" for s in servers)


def test_cli_config_remove(config_setup, capsys):
    rc = main(["config", "remove", "minimax"])
    assert rc == 0
    servers = env_config.read_model_servers(config_setup[0])
    assert all(s.provider != "minimax" for s in servers)


def test_cli_config_set_key(config_setup, capsys):
    rc = main(["config", "set-key", "openrouter", "sk-test"])
    assert rc == 0
    servers = env_config.read_model_servers(config_setup[0])
    openrouter = next(s for s in servers if s.provider == "openrouter")
    assert openrouter.api_key == "sk-test"


def test_cli_config_set_key_from_stdin(config_setup, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("stdin-key"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    rc = main(["config", "set-key", "minimax", "-"])
    assert rc == 0
    servers = env_config.read_model_servers(config_setup[0])
    minimax = next(s for s in servers if s.provider == "minimax")
    assert minimax.api_key == "stdin-key"


def test_init_model_servers_config_reload_existing(config_setup, capsys):
    rc = main(["config", "init"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "model_servers.yaml" in out
    assert "无变更" in out


def test_init_model_servers_config_force_reports_overwrite(config_setup, capsys):
    env_path, yaml_path = config_setup
    example = yaml_path.parent / "model_servers.yaml.example"
    example.write_text(yaml_path.read_text(encoding="utf-8"), encoding="utf-8")
    rc = main(["config", "init", "--force"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "覆盖" in out or "变更" in out


def test_ensure_config_reloads_from_disk(config_setup):
    env_path, yaml_path = config_setup
    servers = env_config.read_model_servers(env_path)
    updated = [
        replace(s, api_key="disk-updated-key") if s.provider == "openrouter" else s
        for s in servers
    ]
    write_model_servers_to_file(yaml_path, updated)
    config.MODEL_SERVERS = list(servers)
    from localagent.model_servers import index_model_servers

    config.MODEL_SERVERS_BY_NAME = index_model_servers(config.MODEL_SERVERS)

    result = env_config.ensure_config(env_path=env_path)
    assert config.get_model_server("openrouter").api_key == "disk-updated-key"
    assert any("openrouter" in line and "API Key" in line for line in result.change_lines())


def test_yaml_list_order_is_priority(config_setup):
    env_path, yaml_path = config_setup
    servers = env_config.read_model_servers(env_path)
    reordered = [
        next(s for s in servers if s.provider == "ollama"),
        next(s for s in servers if s.provider == "openrouter"),
        next(s for s in servers if s.provider == "minimax"),
    ]
    write_model_servers_to_file(yaml_path, reordered)
    result = env_config.ensure_config(env_path=env_path)
    assert [s.provider for s in config.MODEL_SERVERS] == ["ollama", "openrouter", "minimax"]
    assert list(config.MODEL_PROVIDER_PRIORITY) == ["ollama", "openrouter", "minimax"]
    assert list(result.priority_after) == ["ollama", "openrouter", "minimax"]


def test_cli_config_list_reflects_yaml_order(config_setup, capsys):
    env_path, yaml_path = config_setup
    servers = env_config.read_model_servers(env_path)
    reordered = [
        next(s for s in servers if s.provider == "ollama"),
        next(s for s in servers if s.provider == "openrouter"),
        next(s for s in servers if s.provider == "minimax"),
    ]
    write_model_servers_to_file(yaml_path, reordered)
    rc = main(["config", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ollama→openrouter→minimax" in out


def test_auto_bootstrap_uses_packaged_templates(tmp_path: Path, monkeypatch):
    """After pip install, checkout templates are absent; package resources must work."""
    project = tmp_path / "user-home"
    project.mkdir()
    env_path = project / ".env"
    monkeypatch.setattr(config, "PROJECT_ROOT", project)
    monkeypatch.setenv("LA_ENV_FILE", str(env_path))

    created = env_config.auto_bootstrap_model_servers_config()
    assert created is not None
    assert created.is_file()
    assert (project / "config" / "model_servers.yaml").is_file()
    assert env_path.is_file()
    assert "LA_MODEL_SERVERS_FILE" in env_path.read_text(encoding="utf-8")
    assert "provider: ollama" in created.read_text(encoding="utf-8")
    assert env_config.read_env_value(env_path, "LA_MODEL_SERVERS_FILE") == "config/model_servers.yaml"


def test_auto_bootstrap_skips_when_yaml_exists(config_setup):
    env_path, yaml_path = config_setup
    again = env_config.auto_bootstrap_model_servers_config()
    assert again == yaml_path
    assert env_config.read_env_value(env_path, "LA_MODEL_SERVERS_FILE") == "config/model_servers.yaml"


def test_reload_model_servers_with_file(config_setup):
    _, yaml_path = config_setup
    config.reload_model_servers(config_file=str(yaml_path))
    assert "minimax" in config.VALID_PROVIDERS
    assert config.get_model_server("minimax").api_key == "old-minimax-key"


def test_apply_config_flags_provider_and_tavily(config_setup):
    env_path, _ = config_setup
    result = env_config.apply_config_flags(
        provider="ollama",
        base_url="http://127.0.0.1:11434",
        model="qwen3.5:4b",
        tavily_api_key="tvly-test",
        env_path=env_path,
    )
    ollama = next(s for s in env_config.read_model_servers(env_path) if s.provider == "ollama")
    assert ollama.base_url == "http://127.0.0.1:11434"
    assert ollama.model == "qwen3.5:4b"
    assert env_config.read_env_value(env_path, "TAVILY_API_KEY") == "tvly-test"
    assert any("TAVILY_API_KEY" in line for line in result.change_lines())


def test_cli_config_flat_flags(config_setup, capsys):
    rc = main(
        [
            "config",
            "--provider",
            "ollama",
            "--base_url",
            "http://localhost:9999",
            "--model",
            "qwen3.5:4b",
            "--TAVILY_API_KEY",
            "tvly-cli",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "已写入" in out
    ollama = next(s for s in env_config.read_model_servers(config_setup[0]) if s.provider == "ollama")
    assert ollama.base_url == "http://localhost:9999"
    assert env_config.read_env_value(config_setup[0], "TAVILY_API_KEY") == "tvly-cli"


def test_cli_config_from_json_file(config_setup, tmp_path, capsys):
    cfg = tmp_path / "my.json"
    cfg.write_text(
        '{"provider":"openrouter","api_key":"sk-or-json","model":"anthropic/claude-sonnet-4",'
        '"TAVILY_API_KEY":"tvly-json"}',
        encoding="utf-8",
    )
    rc = main(["config", str(cfg)])
    assert rc == 0
    servers = env_config.read_model_servers(config_setup[0])
    openrouter = next(s for s in servers if s.provider == "openrouter")
    assert openrouter.api_key == "sk-or-json"
    assert env_config.read_env_value(config_setup[0], "TAVILY_API_KEY") == "tvly-json"


def test_cli_config_example(capsys):
    rc = main(["config-example"])
    assert rc == 0
    out = capsys.readouterr().out
    assert '"provider": "ollama"' in out
    assert "TAVILY_API_KEY" in out
    assert "qwen3.5:4b" in out


def test_normalize_config_argv():
    from localagent.cli import _normalize_config_argv

    assert _normalize_config_argv(["config", "list"]) == ["config", "list"]
    assert _normalize_config_argv(["config", "--provider", "ollama"]) == [
        "config",
        "set",
        "--provider",
        "ollama",
    ]
    assert _normalize_config_argv(["config", "foo.json"]) == ["config", "apply", "foo.json"]
