"""Read/write model config — YAML file + .env pointers."""

from __future__ import annotations

import json
import os
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
    "mem0": "LA_MEM0_LLM_API_KEY",
}

# Flat env-style keys → provider api_key in model_servers.yaml
PROVIDER_API_KEY_ENV: dict[str, str] = {
    "OPENROUTER_API_KEY": "openrouter",
    "CURSOR_API_KEY": "cursor",
    "OPENAI_API_KEY": "openai",
    "MINIMAX_API_KEY": "openai",  # legacy alias
    "AIPING_API_KEY": "aiping",
}

CONFIG_EXAMPLE_FILENAME = "config.example.json"


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


def _template_text(filename: str, *, project_relative: str) -> str | None:
    """Prefer checkout template; fall back to packaged resources after pip install."""
    project_path = config.PROJECT_ROOT / project_relative
    if project_path.is_file():
        return project_path.read_text(encoding="utf-8")
    from localagent.resources import read_text

    return read_text(filename)


def _ensure_env_file(path: Path) -> None:
    if path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _template_text("env.example", project_relative=".env.example")
    path.write_text(text if text is not None else "", encoding="utf-8")


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

    from localagent.i18n import reset_lang_cache

    if env_path.is_file():
        load_dotenv(env_path, override=True)
        # LA_LANG (and friends) may have changed; drop stale resolve_lang() cache.
        reset_lang_cache()
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

    target = default_model_servers_file()
    template = _template_text(
        "model_servers.yaml.example",
        project_relative="config/model_servers.yaml.example",
    )
    if template is None:
        return None

    try:
        _ensure_env_file(env_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            target.write_text(template, encoding="utf-8")
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
    template = _template_text(
        "model_servers.yaml.example",
        project_relative="config/model_servers.yaml.example",
    )
    if not target.is_file() and template is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template, encoding="utf-8")

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
    template = _template_text(
        "model_servers.yaml.example",
        project_relative="config/model_servers.yaml.example",
    )
    servers_before = tuple(config.MODEL_SERVERS)
    priority_before = tuple(config.MODEL_PROVIDER_PRIORITY)
    had_pointer = bool(read_env_value(env_path, LA_MODEL_SERVERS_FILE_ENV).strip())
    existed_before = target.is_file()
    created = False
    force_overwritten = False

    if force:
        if template is None:
            raise FileNotFoundError("模板不存在: model_servers.yaml.example")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template, encoding="utf-8")
        created = not existed_before
        force_overwritten = existed_before
    elif not target.is_file():
        if template is None:
            raise FileNotFoundError("模板不存在: model_servers.yaml.example")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(template, encoding="utf-8")
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


def set_server_model(
    provider: str,
    model: str,
    *,
    env_path: Path | None = None,
) -> tuple[Path, bool]:
    """Update ``model`` for one provider entry in model_servers.yaml."""
    alias = provider.strip().lower()
    cleaned = model.strip()
    if not cleaned:
        raise ValueError("模型名称不能为空")
    if alias == "auto":
        raise ValueError("请先用 /provider 指定具体路径，再设置模型")
    env_path = env_path or resolve_env_file()
    servers = read_model_servers(env_path)
    updated: list[ModelServer] = []
    found = False
    for item in servers:
        if item.provider == alias:
            updated.append(replace(item, model=cleaned))
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


def set_standalone_key(
    name: str,
    value: str,
    *,
    path: Path | None = None,
    allow_empty: bool = False,
) -> tuple[Path, bool]:
    alias = name.strip().lower()
    if alias not in STANDALONE_KEYS:
        valid = ", ".join(sorted(STANDALONE_KEYS))
        raise ValueError(f"未知 key {name!r}，可选: {valid}")
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        raise ValueError("API Key 不能为空")
    env_path = path or resolve_env_file()
    env_var = STANDALONE_KEYS[alias]
    was_update = write_env_value(env_path, env_var, cleaned)
    os.environ[env_var] = cleaned
    if alias == "tavily":
        config.TAVILY_API_KEY = cleaned
    return env_path, was_update


def read_key_from_stdin() -> str:
    if sys.stdin.isatty():
        raise ValueError("未提供 API Key，请作为参数传入或使用: echo 'sk-...' | LA config set-key <provider> -")
    value = sys.stdin.read().strip()
    if not value:
        raise ValueError("stdin 为空，未读取到 API Key")
    return value


@dataclass(frozen=True)
class SimpleConfigResult:
    """Outcome of ``LA config`` flat flags / JSON file apply."""

    env_path: Path
    config_path: Path | None
    changes: tuple[str, ...] = ()

    def change_lines(self) -> list[str]:
        return list(self.changes)


def config_example_text() -> str:
    """Return bundled ``config.example.json`` content."""
    text = _template_text(
        CONFIG_EXAMPLE_FILENAME,
        project_relative=f"config/{CONFIG_EXAMPLE_FILENAME}",
    )
    if text is None:
        raise FileNotFoundError(f"未找到模板: {CONFIG_EXAMPLE_FILENAME}")
    return text.rstrip() + "\n"


def upsert_provider_fields(
    provider: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
    env_path: Path | None = None,
) -> tuple[Path, bool, list[str]]:
    """Create or patch one provider entry; only provided fields are changed."""
    alias = provider.strip().lower()
    if not alias or alias == "auto":
        raise ValueError("请指定具体 provider（不能为空或 auto）")
    env_path = env_path or resolve_env_file()
    servers = read_model_servers(env_path)
    existing = next((item for item in servers if item.provider == alias), None)
    changes: list[str] = []

    if existing is None:
        entry = ModelServer(
            provider=alias,
            base_url=base_url or "",
            api_key=api_key or "",
            model=model or "",
            timeout=timeout if timeout is not None else 120.0,
        )
        config_path, _ = add_model_server(entry, env_path=env_path)
        changes.append(f"新增 provider: {alias}")
        return config_path, False, changes

    kwargs: dict[str, object] = {}
    if base_url is not None and base_url != existing.base_url:
        kwargs["base_url"] = base_url
        changes.append(f"{alias}.base_url → {base_url}")
    if model is not None and model != existing.model:
        kwargs["model"] = model
        changes.append(f"{alias}.model → {model}")
    if api_key is not None and api_key != existing.api_key:
        kwargs["api_key"] = api_key
        changes.append(f"{alias}.api_key → {mask_secret(api_key)}")
    if timeout is not None and timeout != existing.timeout:
        kwargs["timeout"] = timeout
        changes.append(f"{alias}.timeout → {timeout}")

    if not kwargs:
        config_path = resolve_model_servers_file(env_path) or default_model_servers_file()
        return config_path, True, changes

    updated = replace(existing, **kwargs)
    config_path, _ = add_model_server(updated, env_path=env_path)
    return config_path, True, changes


def apply_simple_config(
    data: dict[str, object],
    *,
    env_path: Path | None = None,
) -> SimpleConfigResult:
    """Apply a flat config dict (CLI flags or config.json).

    Recognized keys:
    - provider / base_url / model / api_key / timeout — upsert that provider
    - TAVILY_API_KEY / LA_MEM0_LLM_API_KEY (or tavily / mem0)
    - OPENROUTER_API_KEY / CURSOR_API_KEY / OPENAI_API_KEY / AIPING_API_KEY
    - servers: optional list of full ModelServer objects
    """
    if not isinstance(data, dict):
        raise ValueError("配置必须是 JSON 对象")

    env_path = env_path or resolve_env_file()
    ensure_config(env_path=env_path)
    changes: list[str] = []
    config_path: Path | None = resolve_model_servers_file(env_path)

    servers_raw = data.get("servers")
    if servers_raw is not None:
        if not isinstance(servers_raw, list):
            raise ValueError("servers 必须是数组")
        for index, item in enumerate(servers_raw):
            if not isinstance(item, dict):
                raise ValueError(f"servers[{index}] 必须是对象")
            server = ModelServer.from_dict(item)
            path, was_update = add_model_server(server, env_path=env_path)
            config_path = path
            action = "更新" if was_update else "新增"
            changes.append(f"{action} provider: {server.provider}")

    provider = str(data.get("provider") or "").strip()
    has_provider_fields = any(
        key in data for key in ("base_url", "base-url", "model", "api_key", "api-key", "timeout")
    )
    if provider or has_provider_fields:
        alias = provider or "ollama"
        base_url = data.get("base_url", data.get("base-url"))
        model = data.get("model")
        api_key = data.get("api_key", data.get("api-key"))
        timeout_raw = data.get("timeout")
        timeout = float(timeout_raw) if timeout_raw is not None and str(timeout_raw) != "" else None
        path, _, field_changes = upsert_provider_fields(
            alias,
            base_url=None if base_url is None else str(base_url),
            model=None if model is None else str(model),
            api_key=None if api_key is None else str(api_key),
            timeout=timeout,
            env_path=env_path,
        )
        config_path = path
        changes.extend(field_changes)

    # Standalone env keys (alias or full env name)
    standalone_by_env = {env_var: alias for alias, env_var in STANDALONE_KEYS.items()}
    for key, value in data.items():
        if key in ("provider", "base_url", "base-url", "model", "api_key", "api-key", "timeout", "servers"):
            continue
        key_str = str(key).strip()
        if not key_str:
            continue
        upper = key_str.upper()
        lower = key_str.lower()

        if upper in PROVIDER_API_KEY_ENV:
            target = PROVIDER_API_KEY_ENV[upper]
            path, _, field_changes = upsert_provider_fields(
                target,
                api_key=str(value),
                env_path=env_path,
            )
            config_path = path
            if field_changes:
                changes.extend(field_changes)
            else:
                changes.append(f"{target}.api_key → {mask_secret(str(value))}")
            continue

        alias = None
        if lower in STANDALONE_KEYS:
            alias = lower
        elif upper in standalone_by_env:
            alias = standalone_by_env[upper]
        if alias is not None:
            dotenv_path, _ = set_standalone_key(
                alias,
                str(value),
                path=env_path,
                allow_empty=True,
            )
            env_var = STANDALONE_KEYS[alias]
            changes.append(f"{env_var} → {mask_secret(str(value))} ({dotenv_path.name})")

    if not changes:
        raise ValueError(
            "未识别到可写入的配置项。可用: --provider/--base_url/--model/--api_key/"
            "--TAVILY_API_KEY，或见 la config-example"
        )

    return SimpleConfigResult(
        env_path=env_path,
        config_path=config_path,
        changes=tuple(changes),
    )


def apply_config_file(path: str | Path, *, env_path: Path | None = None) -> SimpleConfigResult:
    file_path = Path(path).expanduser().resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {file_path}")
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 无效: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("配置文件根节点必须是 JSON 对象")
    return apply_simple_config(data, env_path=env_path)


def apply_config_flags(
    *,
    provider: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: float | None = None,
    tavily_api_key: str | None = None,
    openrouter_api_key: str | None = None,
    cursor_api_key: str | None = None,
    openai_api_key: str | None = None,
    env_path: Path | None = None,
) -> SimpleConfigResult:
    data: dict[str, object] = {}
    if provider is not None:
        data["provider"] = provider
    if base_url is not None:
        data["base_url"] = base_url
    if model is not None:
        data["model"] = model
    if api_key is not None:
        data["api_key"] = api_key
    if timeout is not None:
        data["timeout"] = timeout
    if tavily_api_key is not None:
        data["TAVILY_API_KEY"] = tavily_api_key
    if openrouter_api_key is not None:
        data["OPENROUTER_API_KEY"] = openrouter_api_key
    if cursor_api_key is not None:
        data["CURSOR_API_KEY"] = cursor_api_key
    if openai_api_key is not None:
        data["OPENAI_API_KEY"] = openai_api_key
    return apply_simple_config(data, env_path=env_path)


# Backward-compatible alias
read_model_servers_from_env = read_model_servers
