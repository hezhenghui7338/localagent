"""Load and merge LA MCP yaml with optional Cursor mcp.json."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

from localagent import config as app_config
from localagent.mcp.errors import McpConfigError
from localagent.mcp.schema_adapter import normalize_server_id
from localagent.mcp.types import ApprovalPolicy, McpDefaults, McpServerConfig

logger = logging.getLogger(__name__)

_ENV_RE = re.compile(r"\$\{env:([^}]+)\}")
_APPROVAL_VALUES = frozenset({"always", "dangerous", "off"})


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _env_bool(key: str, default: str = "0") -> bool:
    return _env(key, default).lower() in ("1", "true", "yes")


def _normalize_approval(raw: Any, default: ApprovalPolicy = "dangerous") -> ApprovalPolicy:
    value = str(raw or default).strip().lower()
    if value in _APPROVAL_VALUES:
        return value  # type: ignore[return-value]
    return default


def interpolate_string(value: str, *, workspace: Path | None = None) -> str:
    """Resolve ``${env:NAME}`` and ``${userHome}`` placeholders."""

    def _env_sub(match: re.Match[str]) -> str:
        return os.getenv(match.group(1), "")

    text = _ENV_RE.sub(_env_sub, value)
    text = text.replace("${userHome}", str(Path.home()))
    if workspace is not None:
        text = text.replace("${workspaceFolder}", str(workspace))
        text = text.replace("${workspaceFolderBasename}", workspace.name)
    text = text.replace("${pathSeparator}", os.sep).replace("${/}", os.sep)
    return text


def _interpolate_mapping(data: dict[str, Any], *, workspace: Path | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, raw in data.items():
        if raw is None:
            continue
        out[str(key)] = interpolate_string(str(raw), workspace=workspace)
    return out


def resolve_mcp_config_path() -> Path:
    override = _env("LA_MCP_CONFIG")
    if override:
        return Path(override).expanduser().resolve()
    project_path = app_config.PROJECT_ROOT / "config" / "mcp.yaml"
    if project_path.is_file():
        return project_path
    return Path.home() / ".localagent" / "mcp.yaml"


def default_cursor_paths(*, workspace: Path | None = None) -> list[Path]:
    ws = workspace or app_config.PROJECT_ROOT
    paths = [
        Path.home() / ".cursor" / "mcp.json",
        ws / ".cursor" / "mcp.json",
    ]
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(resolved)
    return unique


def _server_from_la_entry(
    server_id: str,
    raw: dict[str, Any],
    *,
    defaults: McpDefaults,
) -> McpServerConfig | None:
    if not isinstance(raw, dict):
        return None
    enabled = raw.get("enabled", defaults.enabled)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
    approval = _normalize_approval(raw.get("approval", defaults.approval), defaults.approval)
    timeout_raw = raw.get("timeout_seconds", defaults.timeout_seconds)
    try:
        timeout_seconds = int(timeout_raw)
    except (TypeError, ValueError):
        timeout_seconds = defaults.timeout_seconds

    transport = str(raw.get("transport") or "").strip().lower()
    if not transport:
        if raw.get("url"):
            transport = "http"
        elif raw.get("command"):
            transport = "stdio"
    if transport not in ("stdio", "http"):
        logger.warning("mcp server %s: unknown transport %r, skipping", server_id, transport)
        return None

    if transport == "stdio":
        command = str(raw.get("command") or "").strip()
        if not command:
            logger.warning("mcp server %s: stdio missing command, skipping", server_id)
            return None
        args_raw = raw.get("args") or []
        args = tuple(str(a) for a in args_raw) if isinstance(args_raw, list) else ()
        env = _interpolate_mapping(raw.get("env") or {}, workspace=app_config.PROJECT_ROOT)
        cwd = str(raw.get("cwd") or "").strip()
        return McpServerConfig(
            server_id=normalize_server_id(server_id),
            transport="stdio",
            enabled=bool(enabled),
            approval=approval,
            timeout_seconds=timeout_seconds,
            command=command,
            args=args,
            env=env,
            cwd=cwd,
            source="la",
        )

    url = str(raw.get("url") or "").strip()
    if not url:
        logger.warning("mcp server %s: http missing url, skipping", server_id)
        return None
    headers = _interpolate_mapping(raw.get("headers") or {}, workspace=app_config.PROJECT_ROOT)
    return McpServerConfig(
        server_id=normalize_server_id(server_id),
        transport="http",
        enabled=bool(enabled),
        approval=approval,
        timeout_seconds=timeout_seconds,
        url=url,
        headers=headers,
        source="la",
    )


def _server_from_cursor_entry(
    server_id: str,
    raw: dict[str, Any],
    *,
    defaults: McpDefaults,
) -> McpServerConfig | None:
    if not isinstance(raw, dict):
        return None
    if raw.get("url"):
        url = interpolate_string(str(raw["url"]), workspace=app_config.PROJECT_ROOT)
        headers = _interpolate_mapping(raw.get("headers") or {}, workspace=app_config.PROJECT_ROOT)
        return McpServerConfig(
            server_id=normalize_server_id(server_id),
            transport="http",
            enabled=defaults.enabled,
            approval=defaults.approval,
            timeout_seconds=defaults.timeout_seconds,
            url=url,
            headers=headers,
            source="cursor",
        )
    command = str(raw.get("command") or "").strip()
    if not command:
        return None
    args_raw = raw.get("args") or []
    args = tuple(
        interpolate_string(str(a), workspace=app_config.PROJECT_ROOT)
        for a in (args_raw if isinstance(args_raw, list) else [])
    )
    env = _interpolate_mapping(raw.get("env") or {}, workspace=app_config.PROJECT_ROOT)
    return McpServerConfig(
        server_id=normalize_server_id(server_id),
        transport="stdio",
        enabled=defaults.enabled,
        approval=defaults.approval,
        timeout_seconds=defaults.timeout_seconds,
        command=command,
        args=args,
        env=env,
        source="cursor",
    )


def _load_la_yaml(path: Path) -> tuple[McpDefaults, dict[str, McpServerConfig], bool, list[Path]]:
    if not path.is_file():
        return McpDefaults(), {}, False, default_cursor_paths()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise McpConfigError(f"无法解析 MCP 配置 {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise McpConfigError(f"MCP 配置根节点必须是 mapping: {path}")

    defaults_raw = raw.get("defaults") or {}
    defaults = McpDefaults(
        enabled=bool(defaults_raw.get("enabled", True)),
        approval=_normalize_approval(defaults_raw.get("approval"), "dangerous"),
        timeout_seconds=int(defaults_raw.get("timeout_seconds", 30)),
    )
    import_cursor = bool(raw.get("import_cursor", _env_bool("LA_MCP_IMPORT_CURSOR", "1")))
    cursor_paths_raw = raw.get("cursor_paths")
    if isinstance(cursor_paths_raw, list) and cursor_paths_raw:
        cursor_paths = [
            Path(interpolate_string(str(p), workspace=app_config.PROJECT_ROOT)).expanduser()
            for p in cursor_paths_raw
        ]
    else:
        cursor_paths = default_cursor_paths()

    servers: dict[str, McpServerConfig] = {}
    servers_raw = raw.get("servers") or {}
    if isinstance(servers_raw, dict):
        for name, entry in servers_raw.items():
            cfg = _server_from_la_entry(str(name), entry or {}, defaults=defaults)
            if cfg is not None:
                servers[cfg.server_id] = cfg
    return defaults, servers, import_cursor, cursor_paths


def _load_cursor_json(path: Path, *, defaults: McpDefaults) -> dict[str, McpServerConfig]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("skip cursor mcp json %s: %s", path, exc)
        return {}
    servers_raw = raw.get("mcpServers") if isinstance(raw, dict) else None
    if not isinstance(servers_raw, dict):
        return {}
    out: dict[str, McpServerConfig] = {}
    for name, entry in servers_raw.items():
        cfg = _server_from_cursor_entry(str(name), entry or {}, defaults=defaults)
        if cfg is not None:
            out[cfg.server_id] = cfg
    return out


def load_mcp_config(*, path: Path | None = None) -> dict[str, McpServerConfig]:
    """Load merged MCP server configs (LA yaml overrides Cursor json on name clash)."""
    if not _env_bool("LA_MCP_ENABLED", "1"):
        return {}

    config_path = path or resolve_mcp_config_path()
    defaults, la_servers, import_cursor, cursor_paths = _load_la_yaml(config_path)

    merged = dict(la_servers)
    if import_cursor:
        for cursor_path in cursor_paths:
            for server_id, cfg in _load_cursor_json(cursor_path, defaults=defaults).items():
                merged.setdefault(server_id, cfg)

    enabled = {sid: cfg for sid, cfg in merged.items() if cfg.enabled}
    logger.info(
        "mcp config loaded path=%s servers=%d enabled=%d import_cursor=%s",
        config_path,
        len(merged),
        len(enabled),
        import_cursor,
    )
    return enabled


def mcp_available() -> bool:
    try:
        import mcp  # noqa: F401

        return True
    except ImportError:
        return False
