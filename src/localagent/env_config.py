"""Read/write model config — YAML file + .env pointers."""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass, fields, replace
from pathlib import Path

from localagent import config
from localagent.model_servers import (
    DEFAULT_MODEL_SERVERS_RELATIVE,
    LA_MODEL_SERVERS_FILE_ENV,
    ModelServer,
    load_model_servers_from_file,
    parse_model_servers_json,
    resolve_model_servers_path,
    write_model_servers_to_file,
)

LA_MODEL_SERVERS_KEY = "LA_MODEL_SERVERS"

STANDALONE_KEYS: dict[str, str] = {
    "tavily": "TAVILY_API_KEY",
    "hindsight": "LA_HINDSIGHT_LLM_API_KEY",
}


@dataclass(frozen=True)
class ServerStatus:
    server: ModelServer
    index: int

    @property
    def masked_key(self) -> str:
        return mask_secret(self.server.api_key)


@dataclass(frozen=True)
class ConfigEnsureResult:
    """Outcome of bootstrap / reload for model server config."""

    config_path: Path | None
    env_path: Path
    created: bool = False
    force_overwritten: bool = False
    env_pointer_added: bool = False
    servers_before: tuple[ModelServer, ...] = ()
    servers_after: tuple[ModelServer, ...] = ()
    priority_before: tuple[str, ...] = ()
    priority_after: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(self.change_lines())

    def change_lines(self) -> list[str]:
        lines: list[str] = []
        if self.created:
            lines.append("已从模板创建 config/model_servers.yaml")
        if self.force_overwritten:
            lines.append("已用模板覆盖现有配置文件（--force）")
        if self.env_pointer_added:
            lines.append(f"已在 {self.env_path.name} 写入 {LA_MODEL_SERVERS_FILE_ENV}")
        lines.extend(_diff_model_servers(self.servers_before, self.servers_after))
        if self.priority_before != self.priority_after:
            before = "→".join(self.priority_before) or "(空)"
            after = "→".join(self.priority_after) or "(空)"
            lines.append(f"生效优先级: {before} → {after}")
        return lines


_SERVER_FIELD_LABELS: dict[str, str] = {
    "base_url": "API 地址",
    "api_key": "API Key",
    "model": "模型",
    "timeout": "超时",
    "think": "think",
    "num_predict": "num_predict",
    "num_ctx": "num_ctx",
    "keep_alive": "keep_alive",
    "chat_timeout": "chat_timeout",
    "chat_stream": "chat_stream",
    "cwd": "cwd",
    "max_retries": "max_retries",
}


def _format_config_value(field_name: str, value: object) -> str:
    if field_name == "api_key":
        return "已配置" if str(value or "").strip() else "未配置"
    if isinstance(value, float) and value == int(value):
        return str(int(value))
    return str(value)


def _diff_model_servers(
    before: list[ModelServer] | tuple[ModelServer, ...],
    after: list[ModelServer] | tuple[ModelServer, ...],
) -> list[str]:
    before_map = {server.provider: server for server in before}
    after_map = {server.provider: server for server in after}
    lines: list[str] = []

    for provider in after_map:
        if provider not in before_map:
            lines.append(f"新增 provider: {provider}")

    for provider in before_map:
        if provider not in after_map:
            lines.append(f"删除 provider: {provider}")

    for provider, old in before_map.items():
        new = after_map.get(provider)
        if new is None:
            continue
        for item in fields(ModelServer):
            if item.name in ("provider", "extra"):
                continue
            old_value = getattr(old, item.name)
            new_value = getattr(new, item.name)
            if old_value == new_value:
                continue
            label = _SERVER_FIELD_LABELS.get(item.name, item.name)
            lines.append(
                f"{provider}.{label}: "
                f"{_format_config_value(item.name, old_value)} → "
                f"{_format_config_value(item.name, new_value)}"
            )
    return lines


def resolve_env_file() -> Path:
    override = os.getenv("LA_ENV_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return config.PROJECT_ROOT / ".env"


def mask_secret(value: str) -> str:
    if not value:
        return "(未设置)"
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def parse_env_line(line: str) -> tuple[str | None, str | None]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None, None
    if "=" not in stripped:
        return None, None
    key, _, raw = stripped.partition("=")
    return key.strip(), _strip_quotes(raw.strip())


def read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, value = parse_env_line(line)
        if key is not None:
            values[key] = value
    return values


def read_env_value(path: Path, key: str) -> str:
    return read_env_file(path).get(key, "")


def _ensure_env_file(path: Path) -> None:
    if path.is_file():
        return
    example = config.PROJECT_ROOT / ".env.example"
    if example.is_file():
        path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def write_env_value(path: Path, key: str, value: str) -> bool:
    _ensure_env_file(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    found = False
    updated: list[str] = []
    for line in lines:
        parsed_key, _ = parse_env_line(line)
        if parsed_key == key:
            updated.append(f"{key}={value}")
            found = True
        else:
            updated.append(line)
    if not found:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(f"{key}={value}")
    path.write_text("\n".join(updated).rstrip() + "\n", encoding="utf-8")
    return found


def read_priority_override(env_path: Path | None = None) -> str | None:
    env_path = env_path or resolve_env_file()
    value = read_env_value(env_path, "LA_MODEL_PROVIDER_PRIORITY")
    return value or None


def _refresh_project_env(env_path: Path) -> None:
    """Re-read project .env into os.environ before loading model config."""
    from dotenv import load_dotenv

    if env_path.is_file():
        load_dotenv(env_path, override=True)
    pointer = read_env_value(env_path, LA_MODEL_SERVERS_FILE_ENV)
    if pointer:
        os.environ[LA_MODEL_SERVERS_FILE_ENV] = pointer


def _reload_model_servers_from_env(
    *,
    env_path: Path,
    config_file: str | Path | None = None,
) -> None:
    config.reload_model_servers(
        config_file=str(config_file) if config_file is not None else None,
        priority_override=read_priority_override(env_path),
    )


def resolve_model_servers_file(env_path: Path | None = None) -> Path | None:
    env_path = env_path or resolve_env_file()
    env_values = read_env_file(env_path)
    explicit = env_values.get(LA_MODEL_SERVERS_FILE_ENV, "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = config.PROJECT_ROOT / path
        return path
    return resolve_model_servers_path(project_root=config.PROJECT_ROOT)


def default_model_servers_file() -> Path:
    return config.PROJECT_ROOT / DEFAULT_MODEL_SERVERS_RELATIVE


def _wire_env_servers_file(env_path: Path, target: Path) -> None:
    """Ensure LA_MODEL_SERVERS_FILE is set in .env when missing."""
    if read_env_value(env_path, LA_MODEL_SERVERS_FILE_ENV):
        return
    try:
        rel = target.relative_to(config.PROJECT_ROOT)
        pointer = str(rel)
    except ValueError:
        pointer = str(target)
    write_env_value(env_path, LA_MODEL_SERVERS_FILE_ENV, pointer)
    os.environ[LA_MODEL_SERVERS_FILE_ENV] = pointer


def auto_bootstrap_model_servers_config() -> Path | None:
    """First-run setup: create model_servers.yaml from example and wire .env (silent)."""
    env_path = resolve_env_file()
    existing = resolve_model_servers_file(env_path)
    if existing and existing.is_file():
        try:
            _wire_env_servers_file(env_path, existing)
        except OSError:
            pass
        return existing

    example = config.PROJECT_ROOT / "config/model_servers.yaml.example"
    target = default_model_servers_file()
    if not example.is_file():
        return None

    try:
        _ensure_env_file(env_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            shutil.copyfile(example, target)
        _wire_env_servers_file(env_path, target)
    except OSError:
        return target if target.is_file() else None
    return target


def ensure_config(*, env_path: Path | None = None) -> ConfigEnsureResult:
    """Bootstrap config file if missing, wire .env pointer, and reload in-process registry."""
    env_path = env_path or resolve_env_file()
    _refresh_project_env(env_path)
    servers_before = tuple(config.MODEL_SERVERS)
    priority_before = tuple(config.MODEL_PROVIDER_PRIORITY)
    had_pointer = bool(read_env_value(env_path, LA_MODEL_SERVERS_FILE_ENV).strip())
    existing = resolve_model_servers_file(env_path)
    existed_before = existing is not None and existing.is_file()

    auto_bootstrap_model_servers_config()
    config_path = resolve_model_servers_file(env_path)

    env_pointer_added = not had_pointer and bool(read_env_value(env_path, LA_MODEL_SERVERS_FILE_ENV).strip())
    created = not existed_before and config_path is not None and config_path.is_file()

    if config_path and config_path.is_file():
        _reload_model_servers_from_env(env_path=env_path, config_file=config_path)
    else:
        _reload_model_servers_from_env(env_path=env_path)

    servers_after = tuple(config.MODEL_SERVERS)
    priority_after = tuple(config.MODEL_PROVIDER_PRIORITY)
    return ConfigEnsureResult(
        config_path=config_path,
        env_path=env_path,
        created=created,
        env_pointer_added=env_pointer_added,
        servers_before=servers_before,
        servers_after=servers_after,
        priority_before=priority_before,
        priority_after=priority_after,
    )


def ensure_model_servers_file(env_path: Path | None = None) -> Path:
    """Return active config file path, creating from example when needed."""
    env_path = env_path or resolve_env_file()
    existing = resolve_model_servers_file(env_path)
    if existing and existing.is_file():
        return existing

    bootstrapped = auto_bootstrap_model_servers_config()
    if bootstrapped and bootstrapped.is_file():
        return bootstrapped

    target = default_model_servers_file()
    example = config.PROJECT_ROOT / "config/model_servers.yaml.example"
    if not target.is_file() and example.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example, target)

    rel = target.relative_to(config.PROJECT_ROOT) if target.is_relative_to(config.PROJECT_ROOT) else target
    write_env_value(env_path, LA_MODEL_SERVERS_FILE_ENV, str(rel))
    return target


def read_model_servers(env_path: Path | None = None) -> list[ModelServer]:
    env_path = env_path or resolve_env_file()
    config_file = resolve_model_servers_file(env_path)
    if config_file and config_file.is_file():
        return load_model_servers_from_file(config_file)

    raw = read_env_value(env_path, LA_MODEL_SERVERS_KEY)
    if raw:
        return parse_model_servers_json(raw)
    return list(config.build_legacy_model_servers(str(config.PROJECT_ROOT)))


def write_model_servers(servers: list[ModelServer], *, env_path: Path | None = None) -> Path:
    env_path = env_path or resolve_env_file()
    config_file = ensure_model_servers_file(env_path)
    write_model_servers_to_file(config_file, servers)
    _reload_model_servers_from_env(env_path=env_path, config_file=config_file)
    return config_file


def init_model_servers_config(*, env_path: Path | None = None, force: bool = False) -> ConfigEnsureResult:
    """Create or reload model_servers.yaml, wire .env, and reload in-process config."""
    env_path = env_path or resolve_env_file()
    _refresh_project_env(env_path)
    _ensure_env_file(env_path)
    target = default_model_servers_file()
    example = config.PROJECT_ROOT / "config/model_servers.yaml.example"
    servers_before = tuple(config.MODEL_SERVERS)
    priority_before = tuple(config.MODEL_PROVIDER_PRIORITY)
    had_pointer = bool(read_env_value(env_path, LA_MODEL_SERVERS_FILE_ENV).strip())
    existed_before = target.is_file()
    created = False
    force_overwritten = False

    if force:
        if not example.is_file():
            raise FileNotFoundError(f"模板不存在: {example}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example, target)
        created = not existed_before
        force_overwritten = existed_before
    elif not target.is_file():
        if not example.is_file():
            raise FileNotFoundError(f"模板不存在: {example}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example, target)
        created = True

    rel = target.relative_to(config.PROJECT_ROOT)
    write_env_value(env_path, LA_MODEL_SERVERS_FILE_ENV, str(rel))
    os.environ[LA_MODEL_SERVERS_FILE_ENV] = str(rel)
    if read_env_value(env_path, LA_MODEL_SERVERS_KEY):
        write_env_value(env_path, LA_MODEL_SERVERS_KEY, "")

    _reload_model_servers_from_env(env_path=env_path, config_file=target)
    env_pointer_added = not had_pointer
    servers_after = tuple(config.MODEL_SERVERS)
    priority_after = tuple(config.MODEL_PROVIDER_PRIORITY)
    return ConfigEnsureResult(
        config_path=target,
        env_path=env_path,
        created=created,
        force_overwritten=force_overwritten,
        env_pointer_added=env_pointer_added,
        servers_before=servers_before,
        servers_after=servers_after,
        priority_before=priority_before,
        priority_after=priority_after,
    )


def add_model_server(
    server: ModelServer | dict[str, object],
    *,
    env_path: Path | None = None,
) -> tuple[Path, bool]:
    entry = server if isinstance(server, ModelServer) else ModelServer.from_dict(server)
    env_path = env_path or resolve_env_file()
    servers = read_model_servers(env_path)
    was_update = any(item.provider == entry.provider for item in servers)
    servers = [item for item in servers if item.provider != entry.provider]
    servers.append(entry)
    config_path = write_model_servers(servers, env_path=env_path)
    return config_path, was_update


def remove_model_server(provider: str, *, env_path: Path | None = None) -> tuple[Path, bool]:
    alias = provider.strip().lower()
    env_path = env_path or resolve_env_file()
    servers = read_model_servers(env_path)
    filtered = [item for item in servers if item.provider != alias]
    existed = len(filtered) != len(servers)
    if not existed:
        config_path = resolve_model_servers_file(env_path) or default_model_servers_file()
        return config_path, False
    config_path = write_model_servers(filtered, env_path=env_path)
    return config_path, True


def set_server_api_key(
    provider: str,
    api_key: str,
    *,
    env_path: Path | None = None,
) -> tuple[Path, bool]:
    alias = provider.strip().lower()
    cleaned = api_key.strip()
    if not cleaned:
        raise ValueError("API Key 不能为空")
    env_path = env_path or resolve_env_file()
    servers = read_model_servers(env_path)
    updated: list[ModelServer] = []
    found = False
    for item in servers:
        if item.provider == alias:
            updated.append(replace(item, api_key=cleaned))
            found = True
        else:
            updated.append(item)
    if not found:
        raise ValueError(f"未找到 provider {alias!r}，请先在 config/model_servers.yaml 中添加")
    config_path = write_model_servers(updated, env_path=env_path)
    return config_path, True


def list_server_status(env_path: Path | None = None) -> list[ServerStatus]:
    env_path = env_path or resolve_env_file()
    return [
        ServerStatus(server=server, index=index)
        for index, server in enumerate(read_model_servers(env_path), start=1)
    ]


def parse_server_json(raw: str) -> ModelServer:
    raw = raw.strip()
    if not raw:
        raise ValueError("JSON 不能为空")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 无效: {exc}") from exc
    if isinstance(data, list):
        if len(data) != 1:
            raise ValueError("add 只接受单个对象；数组请只含一项")
        data = data[0]
    if not isinstance(data, dict):
        raise ValueError("必须是 JSON 对象或单元素数组")
    return ModelServer.from_dict(data)


def set_standalone_key(name: str, value: str, *, path: Path | None = None) -> tuple[Path, bool]:
    alias = name.strip().lower()
    if alias not in STANDALONE_KEYS:
        valid = ", ".join(sorted(STANDALONE_KEYS))
        raise ValueError(f"未知 key {name!r}，可选: {valid}")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("API Key 不能为空")
    env_path = path or resolve_env_file()
    was_update = write_env_value(env_path, STANDALONE_KEYS[alias], cleaned)
    return env_path, was_update


def read_key_from_stdin() -> str:
    if sys.stdin.isatty():
        raise ValueError("未提供 API Key，请作为参数传入或使用: echo 'sk-...' | LA config set-key <provider> -")
    value = sys.stdin.read().strip()
    if not value:
        raise ValueError("stdin 为空，未读取到 API Key")
    return value


# Backward-compatible alias
read_model_servers_from_env = read_model_servers
