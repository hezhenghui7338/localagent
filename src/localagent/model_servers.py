"""Unified model server registry — YAML/JSON file or LA_MODEL_SERVERS env."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

_BUILTIN_PROVIDERS = frozenset({"ollama", "cursor"})
_OPENAI_COMPATIBLE_EXTRA_HEADERS = frozenset({"openrouter"})
DEFAULT_MODEL_SERVERS_RELATIVE = Path("config/model_servers.yaml")
LA_MODEL_SERVERS_FILE_ENV = "LA_MODEL_SERVERS_FILE"

_BUILTIN_PROVIDERS = frozenset({"ollama", "cursor"})
_OPENAI_COMPATIBLE_EXTRA_HEADERS = frozenset({"openrouter"})


@dataclass(frozen=True)
class ModelServer:
    """One model endpoint entry in LA_MODEL_SERVERS."""

    provider: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: float = 120.0
    # ollama
    think: bool = False
    num_predict: int = 512
    num_ctx: int = 4096
    keep_alive: str = "30m"
    chat_timeout: float = 12.0
    chat_stream: bool = True
    # cursor
    cwd: str = ""
    max_retries: int = 2
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", self.provider.strip().lower())

    @property
    def is_builtin(self) -> bool:
        return self.provider in _BUILTIN_PROVIDERS

    @property
    def needs_api_key(self) -> bool:
        return self.provider not in _BUILTIN_PROVIDERS

    @property
    def is_configured(self) -> bool:
        if self.provider == "ollama":
            return bool(self.base_url and self.model)
        if self.provider == "cursor":
            return bool(self.api_key and self.model)
        return bool(self.api_key and self.base_url and self.model)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"provider": self.provider}
        for item in fields(self):
            if item.name in ("provider", "extra"):
                continue
            value = getattr(self, item.name)
            if value in (None, "", 0, False) and item.name not in ("timeout", "max_retries"):
                continue
            if item.name == "timeout" and value == 120.0:
                continue
            if item.name == "max_retries" and value == 2:
                continue
            if item.name == "num_predict" and value == 512:
                continue
            if item.name == "num_ctx" and value == 4096:
                continue
            if item.name == "keep_alive" and value == "30m":
                continue
            if item.name == "chat_timeout" and value == 12.0:
                continue
            if item.name == "chat_stream" and value is True:
                continue
            data[item.name] = value
        if self.extra:
            data.update(self.extra)
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ModelServer:
        provider = str(raw.get("provider", "")).strip().lower()
        if not provider:
            raise ValueError("model server entry missing provider")
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", provider):
            raise ValueError(f"invalid provider name {provider!r}")

        known = {f.name for f in fields(cls)} - {"extra"}
        kwargs: dict[str, Any] = {"provider": provider}
        extra: dict[str, Any] = {}
        for key, value in raw.items():
            if key == "provider":
                continue
            if key in known:
                kwargs[key] = value
            else:
                extra[key] = value
        if extra:
            kwargs["extra"] = extra
        return cls(**kwargs)


def parse_model_servers_data(data: Any, *, source: str = "config") -> list[ModelServer]:
    if not isinstance(data, list):
        raise ValueError(f"{source} 必须是数组/list")
    servers: list[ModelServer] = []
    seen: set[str] = set()
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"{source}[{index}] 必须是对象")
        server = ModelServer.from_dict(item)
        if server.provider in seen:
            raise ValueError(f"{source} 中 provider 重复: {server.provider!r}")
        seen.add(server.provider)
        servers.append(server)
    return servers


def parse_model_servers_json(raw: str) -> list[ModelServer]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LA_MODEL_SERVERS JSON 无效: {exc}") from exc
    return parse_model_servers_data(data, source="LA_MODEL_SERVERS")


def resolve_model_servers_path(
    *,
    project_root: Path | str,
    file_override: str | None = None,
) -> Path | None:
    """Resolve config file path: explicit env > auto-detect default filenames."""
    root = Path(project_root)
    explicit = (file_override or os.getenv(LA_MODEL_SERVERS_FILE_ENV, "")).strip()
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = root / path
        return path
    for candidate in (
        root / "config/model_servers.yaml",
        root / "config/model_servers.yml",
        root / "config/model_servers.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def load_model_servers_from_file(path: Path) -> list[ModelServer]:
    if not path.is_file():
        raise FileNotFoundError(f"模型配置文件不存在: {path}")
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("读取 YAML 需要 PyYAML：pip install pyyaml") from exc
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        raise ValueError(f"不支持的模型配置文件格式: {path.suffix}（可用 .yaml / .json）")
    if data is None:
        return []
    return parse_model_servers_data(data, source=str(path))


def write_model_servers_to_file(path: Path, servers: list[ModelServer]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    payload = [server.to_dict() for server in servers]
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("写入 YAML 需要 PyYAML：pip install pyyaml") from exc
        text = yaml.dump(
            payload,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
    elif suffix == ".json":
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        raise ValueError(f"不支持的模型配置文件格式: {path.suffix}")
    path.write_text(text, encoding="utf-8")


def index_model_servers(servers: list[ModelServer]) -> dict[str, ModelServer]:
    return {server.provider: server for server in servers}


def compute_provider_priority(
    servers: list[ModelServer],
    override: str = "",
) -> list[str]:
    """List order is default priority; LA_MODEL_PROVIDER_PRIORITY overrides subset/order."""
    default_order = [server.provider for server in servers]
    if not override.strip():
        return default_order

    known = set(default_order)
    ordered: list[str] = []
    for part in override.split(","):
        name = part.strip().lower()
        if name and name in known and name not in ordered:
            ordered.append(name)
    for name in default_order:
        if name not in ordered:
            ordered.append(name)
    return ordered


def default_model_servers() -> list[ModelServer]:
    """Built-in default when neither LA_MODEL_SERVERS nor legacy vars exist."""
    return [
        ModelServer(
            provider="ollama",
            base_url="http://localhost:11434",
            model="qwen3.5:4b",
            timeout=90.0,
            chat_timeout=12.0,
        ),
        ModelServer(
            provider="minimax",
            base_url="https://api.minimax.io/v1",
            model="MiniMax-M3",
            timeout=120.0,
        ),
        ModelServer(
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            model="anthropic/claude-sonnet-4",
            timeout=120.0,
        ),
        ModelServer(
            provider="cursor",
            model="composer-2.5",
            timeout=120.0,
        ),
    ]


def _env_bool(raw: str, default: str = "0") -> bool:
    return os.getenv(raw, default).strip().lower() in ("1", "true", "yes")


def _env_float(raw: str, default: str) -> float:
    return float(os.getenv(raw, default).strip())


def _env_int(raw: str, default: str) -> int:
    return int(os.getenv(raw, default).strip())


def _env_str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def build_legacy_model_servers(project_root: str | None = None) -> list[ModelServer]:
    """Construct servers from legacy MINIMAX_* / OLLAMA_* env vars."""
    root = project_root or _env_str("LA_PROJECT_ROOT") or "."
    servers: list[ModelServer] = [
        ModelServer(
            provider="ollama",
            base_url=_env_str("OLLAMA_BASE_URL", "http://localhost:11434"),
            model=_env_str("OLLAMA_MODEL", "qwen3.5:4b"),
            timeout=_env_float("OLLAMA_TIMEOUT", "90"),
            think=_env_bool("OLLAMA_THINK", "0"),
            num_predict=_env_int("OLLAMA_NUM_PREDICT", "512"),
            num_ctx=_env_int("OLLAMA_NUM_CTX", "4096"),
            keep_alive=_env_str("OLLAMA_KEEP_ALIVE", "30m"),
            chat_timeout=_env_float("LA_OLLAMA_CHAT_TIMEOUT", "12"),
            chat_stream=_env_bool("OLLAMA_CHAT_STREAM", "1"),
        ),
        ModelServer(
            provider="minimax",
            base_url=_env_str("MINIMAX_BASE_URL", "https://api.minimax.io/v1"),
            api_key=_env_str("MINIMAX_API_KEY"),
            model=_env_str("MINIMAX_MODEL", "MiniMax-M3"),
            timeout=_env_float("MINIMAX_TIMEOUT", "120"),
        ),
        ModelServer(
            provider="openrouter",
            base_url=_env_str("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            api_key=_env_str("OPENROUTER_API_KEY"),
            model=_env_str("OPENROUTER_MODEL", "anthropic/claude-sonnet-4"),
            timeout=120.0,
        ),
        ModelServer(
            provider="cursor",
            api_key=_env_str("CURSOR_API_KEY"),
            model=_env_str("CURSOR_MODEL", "composer-2.5"),
            cwd=_env_str("CURSOR_CWD", root),
            max_retries=max(0, _env_int("LA_CURSOR_MAX_RETRIES", "2")),
            timeout=120.0,
        ),
    ]
    return servers


def load_model_servers(
    *,
    raw_json: str | None = None,
    config_file: str | Path | None = None,
    priority_override: str | None = None,
    project_root: str | Path | None = None,
) -> tuple[list[ModelServer], list[str]]:
    """Load servers and effective provider priority."""
    root = Path(project_root) if project_root else Path(_env_str("LA_PROJECT_ROOT") or ".")
    file_path = None
    if config_file:
        file_path = Path(config_file).expanduser()
        if not file_path.is_absolute():
            file_path = root / file_path
    else:
        file_path = resolve_model_servers_path(project_root=root)

    servers: list[ModelServer]
    if file_path and file_path.is_file():
        servers = load_model_servers_from_file(file_path)
    else:
        raw = raw_json if raw_json is not None else _env_str("LA_MODEL_SERVERS")
        if raw:
            servers = parse_model_servers_json(raw)
        else:
            legacy = build_legacy_model_servers(project_root=str(root))
            servers = legacy if legacy else default_model_servers()

    override = priority_override if priority_override is not None else _env_str("LA_MODEL_PROVIDER_PRIORITY")
    priority = compute_provider_priority(servers, override)
    return servers, priority


def serialize_model_servers(servers: list[ModelServer]) -> str:
    return json.dumps([server.to_dict() for server in servers], ensure_ascii=False, separators=(",", ":"))


def first_usable_openai_server(
    servers: list[ModelServer],
    *,
    require_api_key: bool = True,
) -> ModelServer | None:
    for server in servers:
        if server.provider in _BUILTIN_PROVIDERS:
            continue
        if require_api_key and not server.api_key:
            continue
        if not server.base_url or not server.model:
            continue
        return server
    return None


def openai_compatible_headers(provider: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if provider in _OPENAI_COMPATIBLE_EXTRA_HEADERS:
        headers["HTTP-Referer"] = "https://github.com/localagent"
        headers["X-Title"] = "LocalAgent"
    return headers
