"""Path and runtime configuration — customer-facing values come from .env."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv

from localagent.model_servers import (
    ModelServer,
    build_legacy_model_servers,
    compute_provider_priority,
    index_model_servers,
    load_model_servers,
    parse_model_servers_json,
    resolve_model_servers_path,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_env_override = os.getenv("LA_ENV_FILE", "").strip()
if _env_override:
    load_dotenv(_env_override)
else:
    load_dotenv(PROJECT_ROOT / ".env")
    # 兼容从子目录或已安装 CLI 启动：cwd 向上查找 .env
    load_dotenv(override=False)

# 首次运行：自动从模板创建 config/model_servers.yaml 并写入 .env 指针
from localagent.env_config import auto_bootstrap_model_servers_config  # noqa: E402

_BOOTSTRAPPED_MODEL_SERVERS_FILE = auto_bootstrap_model_servers_config()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _env_bool(key: str, default: str = "0") -> bool:
    return _env(key, default).lower() in ("1", "true", "yes")


def _env_int(key: str, default: str) -> int:
    return int(_env(key, default))


def _env_float(key: str, default: str) -> float:
    return float(_env(key, default))


# --- Data paths (override with LA_DATA_DIR) ---
_DATA_OVERRIDE = _env("LA_DATA_DIR")
DATA_DIR = Path(_DATA_OVERRIDE) if _DATA_OVERRIDE else PROJECT_ROOT / "data"
KB_DIR = DATA_DIR / "kb"
SYNC_INDEX_FILE = DATA_DIR / "sync_index.json"
MEMORY_STORE_FILE = DATA_DIR / "memory_store.json"
KNOWLEDGE_STORE_FILE = DATA_DIR / "knowledge_store.json"
CORE_PROFILE_FILE = DATA_DIR / "core_profile.json"
CONVERSATIONS_DIR = DATA_DIR / "conversations"
CHATGPT_DATA_DIR = DATA_DIR / "chatGPTdata"
CHATGPT_IMPORT_INDEX_FILE = DATA_DIR / "chatgpt_import_index.json"
SESSIONS_DB = DATA_DIR / "sessions.db"
CHROMA_DIR = DATA_DIR / "chroma"
BM25_PATH = DATA_DIR / "bm25.pkl"
INGEST_TASKS_FILE = DATA_DIR / "ingest_tasks.json"
TASK_LOGS_DIR = DATA_DIR / "task_logs"
AUDIT_DIR = DATA_DIR / "audit"
USAGE_LOG_FILE = AUDIT_DIR / "usage.jsonl"

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".xlsx"}
DEFAULT_USER_ID = "default_user"


def hindsight_profile() -> str:
    """Hindsight embed profile; isolated per LA_DATA_DIR override."""
    if not _DATA_OVERRIDE:
        return "localagent"
    digest = hashlib.sha256(str(Path(_DATA_OVERRIDE).resolve()).encode()).hexdigest()[:16]
    return f"la-{digest}"


def default_bank_id() -> str:
    """Hindsight memory bank; follows hindsight_profile for isolation."""
    return hindsight_profile()


# Back-compat alias (prefer default_bank_id() when LA_DATA_DIR may be set)
DEFAULT_BANK_ID = "localagent"

# --- Workspace ---
LA_WORKSPACE = _env("LA_WORKSPACE")

# --- Agent shell tool ---
SHELL_TIMEOUT = _env_float("LA_SHELL_TIMEOUT", "30")
SHELL_MAX_OUTPUT = _env_int("LA_SHELL_MAX_OUTPUT", "12000")

# --- Model routing (LA_MODEL_SERVERS_FILE YAML or legacy env) ---
DEFAULT_MODEL_PROVIDER = "auto"
LA_MODEL_SERVERS_RAW = _env("LA_MODEL_SERVERS")
LA_MODEL_SERVERS_FILE = _env("LA_MODEL_SERVERS_FILE")
_resolved_servers_file = resolve_model_servers_path(
    project_root=PROJECT_ROOT,
    file_override=LA_MODEL_SERVERS_FILE or None,
) or _BOOTSTRAPPED_MODEL_SERVERS_FILE

MODEL_SERVERS, MODEL_PROVIDER_PRIORITY = load_model_servers(
    raw_json=LA_MODEL_SERVERS_RAW or None,
    config_file=_resolved_servers_file,
    priority_override=_env("LA_MODEL_PROVIDER_PRIORITY") or None,
    project_root=PROJECT_ROOT,
)
MODEL_SERVERS_BY_NAME: dict[str, ModelServer] = index_model_servers(MODEL_SERVERS)
VALID_PROVIDERS: tuple[str, ...] = tuple(server.provider for server in MODEL_SERVERS)


def get_model_server(provider: str) -> ModelServer | None:
    return MODEL_SERVERS_BY_NAME.get(provider.strip().lower())


def reload_model_servers(
    *,
    raw_json: str | None = None,
    config_file: str | Path | None = None,
    priority_override: str | None = None,
) -> None:
    """Reload in-process model server registry (tests / LA config)."""
    global MODEL_SERVERS, MODEL_PROVIDER_PRIORITY, MODEL_SERVERS_BY_NAME, VALID_PROVIDERS
    global LA_MODEL_SERVERS_RAW, LA_MODEL_SERVERS_FILE, OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_THINK
    global OLLAMA_NUM_PREDICT, OLLAMA_NUM_CTX, OLLAMA_KEEP_ALIVE, OLLAMA_TIMEOUT
    global OLLAMA_CHAT_TIMEOUT, OLLAMA_CHAT_STREAM, MINIMAX_API_KEY, MINIMAX_MODEL
    global MINIMAX_BASE_URL, MINIMAX_TIMEOUT, OPENROUTER_API_KEY, OPENROUTER_MODEL
    global OPENROUTER_BASE_URL, CURSOR_API_KEY, CURSOR_MODEL, CURSOR_CWD, CURSOR_MAX_RETRIES

    if raw_json is not None:
        LA_MODEL_SERVERS_RAW = raw_json
    if config_file is not None:
        LA_MODEL_SERVERS_FILE = str(config_file)

    resolved_file = None
    if config_file is not None:
        resolved_file = Path(config_file)
    elif LA_MODEL_SERVERS_FILE:
        resolved_file = resolve_model_servers_path(
            project_root=PROJECT_ROOT,
            file_override=LA_MODEL_SERVERS_FILE,
        )

    MODEL_SERVERS, MODEL_PROVIDER_PRIORITY = load_model_servers(
        raw_json=LA_MODEL_SERVERS_RAW or None,
        config_file=resolved_file,
        priority_override=priority_override if priority_override is not None else _env("LA_MODEL_PROVIDER_PRIORITY") or None,
        project_root=PROJECT_ROOT,
    )
    MODEL_SERVERS_BY_NAME = index_model_servers(MODEL_SERVERS)
    VALID_PROVIDERS = tuple(server.provider for server in MODEL_SERVERS)
    _sync_legacy_shortcuts()


def _ollama_server() -> ModelServer | None:
    return get_model_server("ollama")


def _sync_legacy_shortcuts() -> None:
    """Keep legacy module attrs in sync for gradual migration."""
    global OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_THINK, OLLAMA_NUM_PREDICT, OLLAMA_NUM_CTX
    global OLLAMA_KEEP_ALIVE, OLLAMA_TIMEOUT, OLLAMA_CHAT_TIMEOUT, OLLAMA_CHAT_STREAM
    global MINIMAX_API_KEY, MINIMAX_MODEL, MINIMAX_BASE_URL, MINIMAX_TIMEOUT
    global OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL
    global CURSOR_API_KEY, CURSOR_MODEL, CURSOR_CWD, CURSOR_MAX_RETRIES

    ollama = _ollama_server()
    OLLAMA_BASE_URL = ollama.base_url if ollama else _env("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = ollama.model if ollama else _env("OLLAMA_MODEL", "qwen3.5:4b")
    OLLAMA_THINK = ollama.think if ollama else _env_bool("OLLAMA_THINK", "0")
    OLLAMA_NUM_PREDICT = ollama.num_predict if ollama else _env_int("OLLAMA_NUM_PREDICT", "512")
    OLLAMA_NUM_CTX = ollama.num_ctx if ollama else _env_int("OLLAMA_NUM_CTX", "4096")
    OLLAMA_KEEP_ALIVE = ollama.keep_alive if ollama else _env("OLLAMA_KEEP_ALIVE", "30m")
    OLLAMA_TIMEOUT = ollama.timeout if ollama else _env_float("OLLAMA_TIMEOUT", "90")
    OLLAMA_CHAT_TIMEOUT = ollama.chat_timeout if ollama else _env_float("LA_OLLAMA_CHAT_TIMEOUT", "12")
    OLLAMA_CHAT_STREAM = ollama.chat_stream if ollama else _env_bool("OLLAMA_CHAT_STREAM", "1")

    minimax = get_model_server("minimax")
    MINIMAX_API_KEY = minimax.api_key if minimax else _env("MINIMAX_API_KEY")
    MINIMAX_MODEL = minimax.model if minimax else _env("MINIMAX_MODEL", "MiniMax-M3")
    MINIMAX_BASE_URL = minimax.base_url if minimax else _env("MINIMAX_BASE_URL", "https://api.minimax.io/v1")
    MINIMAX_TIMEOUT = minimax.timeout if minimax else _env_float("MINIMAX_TIMEOUT", "120")

    openrouter = get_model_server("openrouter")
    OPENROUTER_API_KEY = openrouter.api_key if openrouter else _env("OPENROUTER_API_KEY")
    OPENROUTER_MODEL = openrouter.model if openrouter else _env("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
    OPENROUTER_BASE_URL = (
        openrouter.base_url if openrouter else _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    )

    cursor = get_model_server("cursor")
    CURSOR_API_KEY = cursor.api_key if cursor else _env("CURSOR_API_KEY")
    CURSOR_MODEL = cursor.model if cursor else _env("CURSOR_MODEL", "composer-2.5")
    CURSOR_CWD = cursor.cwd if cursor and cursor.cwd else _env("CURSOR_CWD", str(PROJECT_ROOT))
    CURSOR_MAX_RETRIES = cursor.max_retries if cursor else max(0, _env_int("LA_CURSOR_MAX_RETRIES", "2"))


_sync_legacy_shortcuts()


def normalize_provider_choice(value: str | None) -> str:
    """Return auto or a valid provider name."""
    if not value or value.strip().lower() == DEFAULT_MODEL_PROVIDER:
        return DEFAULT_MODEL_PROVIDER
    name = value.strip().lower()
    if name in VALID_PROVIDERS:
        return name
    raise ValueError(
        f"invalid provider {value!r}; choose auto or one of: {', '.join(VALID_PROVIDERS)}"
    )


# --- Web search ---
TAVILY_API_KEY = _env("TAVILY_API_KEY")

# --- Retrieval tuning ---
SEMANTIC_WEIGHT = _env_float("LA_SEMANTIC_WEIGHT", "0.75")
TIME_DECAY_HALFLIFE_DAYS = _env_float("LA_TIME_HALFLIFE_DAYS", "90")

# --- Ingest memory ---
INGEST_USE_LLM = _env_bool("LA_INGEST_USE_LLM", "0")
INGEST_MEMORY_MAX_SECTION_CHARS = _env_int("LA_INGEST_MEMORY_MAX_CHARS", "1500")
INGEST_MEMORY_MAX_FACTS = _env_int("LA_INGEST_MEMORY_MAX_FACTS", "50")

# --- Memory enrichment ---
MEMORY_ENRICH_USE_LLM = _env_bool("LA_MEMORY_ENRICH_LLM", "0")
MEMORY_BACKEND = _env("LA_MEMORY_BACKEND", "auto").lower()

# --- Hindsight LLM (fact extraction during retain) ---
HINDSIGHT_LLM_PROVIDER = _env("LA_HINDSIGHT_LLM_PROVIDER").lower()
HINDSIGHT_LLM_MODEL = _env("LA_HINDSIGHT_LLM_MODEL")
HINDSIGHT_LLM_BASE_URL = _env("LA_HINDSIGHT_LLM_BASE_URL")
HINDSIGHT_LLM_API_KEY = _env("LA_HINDSIGHT_LLM_API_KEY")
HINDSIGHT_RETAIN_JSON_FALLBACK = _env_bool("LA_HINDSIGHT_RETAIN_JSON_FALLBACK", "1")
HINDSIGHT_EXTRACTION_MODE = _env("LA_HINDSIGHT_EXTRACTION_MODE", "auto").lower()

# --- Agent intent clarification ---
INTENT_CLARIFY_ENABLED = _env_bool("LA_INTENT_CLARIFY", "1")


def ensure_data_dirs() -> None:
    """Create runtime data directories if missing."""
    for path in (DATA_DIR, KB_DIR, CONVERSATIONS_DIR, CHATGPT_DATA_DIR, CHROMA_DIR, TASK_LOGS_DIR, AUDIT_DIR):
        path.mkdir(parents=True, exist_ok=True)
