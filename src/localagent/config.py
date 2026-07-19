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

DEFAULT_USER_HOME = Path.home() / ".localagent"


def resolve_project_root() -> Path:
    """Runtime home for .env / config / data.

    Priority:
    1. ``LA_HOME`` or ``LA_PROJECT_ROOT``
    2. Source / editable checkout (repo root with ``pyproject.toml`` + ``src/localagent``)
    3. ``~/.localagent`` after a normal ``pip install`` / ``pipx install``
    """
    override = os.getenv("LA_HOME", "").strip() or os.getenv("LA_PROJECT_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    package_dir = Path(__file__).resolve().parent
    # Editable / source: <repo>/src/localagent/config.py
    src_root = package_dir.parents[1]
    if (src_root / "pyproject.toml").is_file() and (src_root / "src" / "localagent").is_dir():
        return src_root

    # Flat layout fallback: <repo>/localagent/config.py
    flat_root = package_dir.parent
    if (flat_root / "pyproject.toml").is_file() and (flat_root / "localagent").is_dir():
        return flat_root

    return DEFAULT_USER_HOME.resolve()


PROJECT_ROOT = resolve_project_root()
IS_SOURCE_CHECKOUT = (PROJECT_ROOT / "src" / "localagent").is_dir()

_env_override = os.getenv("LA_ENV_FILE", "").strip()
if _env_override:
    load_dotenv(_env_override)
else:
    load_dotenv(PROJECT_ROOT / ".env")
    # 兼容从子目录或已安装 CLI 启动：cwd 向上查找 .env
    load_dotenv(override=False)

# Local-first: disable Mem0→PostHog telemetry unless the user opts in via .env.
# Must run before any ``import mem0`` (mem0 reads MEM0_TELEMETRY at import time).
os.environ.setdefault("MEM0_TELEMETRY", "False")

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
MEMORY_PENDING_QUEUE_FILE = DATA_DIR / "pending_queue.json"
MEMORY_GRAPH_FILE = DATA_DIR / "memory_graph.db"
KNOWLEDGE_STORE_FILE = DATA_DIR / "knowledge_store.json"
CORE_PROFILE_FILE = DATA_DIR / "core_profile.json"
CONVERSATIONS_DIR = DATA_DIR / "conversations"
CHATGPT_DATA_DIR = DATA_DIR / "chatGPTdata"
CHATGPT_IMPORT_INDEX_FILE = DATA_DIR / "chatgpt_import_index.json"
CHAT_INGEST_INDEX_FILE = DATA_DIR / "chat_ingest_index.json"
SESSIONS_DB = DATA_DIR / "sessions.db"
CHROMA_DIR = DATA_DIR / "chroma"
BM25_PATH = DATA_DIR / "bm25.pkl"
INGEST_TASKS_FILE = DATA_DIR / "ingest_tasks.json"
TASK_LOGS_DIR = DATA_DIR / "task_logs"
AUDIT_DIR = DATA_DIR / "audit"
USAGE_LOG_FILE = AUDIT_DIR / "usage.jsonl"
EVENTS_LOG_FILE = AUDIT_DIR / "events.jsonl"
LOGS_DIR = DATA_DIR / "logs"
APP_LOG_FILE = LOGS_DIR / "localagent.log"
SUMMARIZE_SESSIONS_DIR = DATA_DIR / "summarize_sessions"
SUMMARIZE_SESSIONS_INDEX = SUMMARIZE_SESSIONS_DIR / "index.json"

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
# Text / tabular / PDF for RAG + one-click summarize.
# Images stay in SUPPORTED_SUFFIXES but only load when LA_VL_ENABLED=1.
SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".xlsx", ".pdf"} | IMAGE_SUFFIXES
SUMMARIZE_SUFFIXES = {".md", ".markdown", ".txt", ".xlsx", ".pdf"}
DEFAULT_USER_ID = "default_user"
# One-click summarize: short-doc path (chars of annotated text).
SUMMARIZE_SHORT_MAX_CHARS = _env_int("LA_SUMMARIZE_SHORT_MAX_CHARS", "12000")
SUMMARIZE_LLM_INPUT_CHARS = _env_int("LA_SUMMARIZE_LLM_INPUT_CHARS", "10000")
# Document deep-chat: retrieve this many Cold chunks when body exceeds prompt stuffing.
DOC_SESSION_RETRIEVE_TOP_K = _env_int("LA_DOC_SESSION_RETRIEVE_TOP_K", "8")

# --- Language (LA_LANG=auto|en|zh; default auto → system locale → en) ---
from localagent.i18n import default_news_rss_url, resolve_lang  # noqa: E402

LANG = resolve_lang()

# --- News sniff (BestBlogs RSS → daily brief → deep read) ---
DEFAULT_NEWS_RSS_URL = default_news_rss_url(LANG)
NEWS_DIR = Path(_env("LA_NEWS_DIR")) if _env("LA_NEWS_DIR") else DATA_DIR / "news"
NEWS_DB_FILE = NEWS_DIR / "articles.sqlite"
NEWS_PROFILE_FILE = NEWS_DIR / "news_profile.json"
NEWS_SYNC_STATE_FILE = NEWS_DIR / "sync_state.json"
NEWS_SYNC_LOG_FILE = NEWS_DIR / "sync.log"
NEWS_CACHE_DIR = NEWS_DIR / "cache"
_NEWS_RSS_OVERRIDE = _env("LA_NEWS_RSS_URL")
NEWS_RSS_URL = _NEWS_RSS_OVERRIDE or DEFAULT_NEWS_RSS_URL
NEWS_BRIEF_SIZE = _env_int("LA_NEWS_BRIEF_SIZE", "30")
NEWS_AUTO_SYNC = _env_bool("LA_NEWS_AUTO_SYNC", "1")
NEWS_AUTO_SYNC_HOUR = _env_int("LA_NEWS_AUTO_SYNC_HOUR", "8")
NEWS_AUTO_SYNC_MINUTE = _env_int("LA_NEWS_AUTO_SYNC_MINUTE", "0")
# Fetch quality: reject stubs shorter than this (chars of extracted body).
NEWS_FETCH_MIN_CHARS = _env_int("LA_NEWS_FETCH_MIN_CHARS", "500")
# Optional Jina Reader HTTP fallback for JS-heavy pages (no browser dependency).
NEWS_FETCH_USE_JINA = _env_bool("LA_NEWS_FETCH_USE_JINA", "1")
# Phase 2 reserved
BESTBLOGS_API_KEY = _env("LA_BESTBLOGS_API_KEY")
NEWS_OPENAPI = _env_bool("LA_NEWS_OPENAPI", "0")

# --- Aware (opt-in local world sensors → events / whitelist actions) ---
AWARE_DIR = Path(_env("LA_AWARE_DIR")) if _env("LA_AWARE_DIR") else DATA_DIR / "aware"
AWARE_PROFILE_FILE = AWARE_DIR / "profile.json"
AWARE_CURSORS_FILE = AWARE_DIR / "cursors.json"
AWARE_EVENTS_FILE = AWARE_DIR / "events.jsonl"
AWARE_INPUT_ACTIVITY_FILE = AWARE_DIR / "input_activity.json"
AWARE_INPUT_ACTIVITY_KEEP_DAYS = _env_int("LA_AWARE_INPUT_ACTIVITY_KEEP_DAYS", "30")
AWARE_SUGGESTIONS_FILE = AWARE_DIR / "suggestions.json"
AWARE_EPISODES_FILE = AWARE_DIR / "episodes.jsonl"
AWARE_SESSIONS_DIR = AWARE_DIR / "sessions"
AWARE_NOW_DIR = AWARE_DIR / "now"
AWARE_CONTEXT_DIR = AWARE_DIR / "context"
AWARE_HOT_FILE = AWARE_CONTEXT_DIR / "hot.json"
AWARE_DIFF_FILE = AWARE_CONTEXT_DIR / "diff.json"
AWARE_ROLLUPS_FILE = AWARE_DIR / "rollups.jsonl"
AWARE_ROLLUP_KEEP_DAYS = _env_int("LA_AWARE_ROLLUP_KEEP_DAYS", "180")
AWARE_TICK_LOG_FILE = AWARE_DIR / "tick.log"
AWARE_TICK_INTERVAL_MINUTES = _env_int("LA_AWARE_TICK_INTERVAL_MINUTES", "15")
AWARE_TICK_LOCK_FILE = AWARE_DIR / "tick.lock"
AWARE_ACTIVE_HOURS_WELLNESS = _env_int("LA_AWARE_ACTIVE_HOURS_WELLNESS", "10")
AWARE_EPISODES_MAX_BYTES = _env_int("LA_AWARE_EPISODES_MAX_BYTES", str(3 * 1024 * 1024))
# Hard budgets so periodic ticks cannot freeze the host.
AWARE_FS_MAX_SCAN_FILES = _env_int("LA_AWARE_FS_MAX_SCAN_FILES", "5000")
AWARE_FS_MAX_DEPTH = _env_int("LA_AWARE_FS_MAX_DEPTH", "8")
AWARE_TICK_DEADLINE_SEC = _env_float("LA_AWARE_TICK_DEADLINE_SEC", "20")
AWARE_BROWSER_DB_MAX_BYTES = _env_int("LA_AWARE_BROWSER_DB_MAX_BYTES", str(64 * 1024 * 1024))
AWARE_HISTORY_MAX_BYTES = _env_int("LA_AWARE_HISTORY_MAX_BYTES", str(8 * 1024 * 1024))
AWARE_EVENTS_MAX_BYTES = _env_int("LA_AWARE_EVENTS_MAX_BYTES", str(5 * 1024 * 1024))
# Document-like suffixes that may become suggestions (never auto-ingest into kb/Cold).
AWARE_SUGGEST_SUFFIXES = {
    ".pdf",
    ".md",
    ".markdown",
    ".txt",
    ".docx",
    ".doc",
    ".rtf",
    ".html",
    ".htm",
    ".csv",
}
AWARE_NOISE_SUFFIXES = {
    ".crdownload",
    ".tmp",
    ".part",
    ".download",
    ".dmg",
    ".pkg",
    ".zip",
    ".rar",
    ".7z",
    ".exe",
    ".msi",
    ".iso",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".mp4",
    ".mov",
    ".mkv",
    ".mp3",
    ".wav",
    ".icloud",
}
AWARE_SUGGEST_PER_TICK = _env_int("LA_AWARE_SUGGEST_PER_TICK", "10")

# --- Vision (image → text for Cold RAG; off by default — temporarily unsupported) ---
VL_ENABLED = _env_bool("LA_VL_ENABLED", "0")
VL_MODEL = _env("LA_VL_MODEL", "qwen3-vl:4b") or "qwen3-vl:4b"
VL_TIMEOUT = _env_float("LA_VL_TIMEOUT", "120")
VL_NUM_PREDICT = _env_int("LA_VL_NUM_PREDICT", "1024")


def memory_user_id() -> str:
    """Mem0 user_id / bank isolation key; isolated per LA_DATA_DIR override."""
    if not _DATA_OVERRIDE:
        return "localagent"
    digest = hashlib.sha256(str(Path(_DATA_OVERRIDE).resolve()).encode()).hexdigest()[:16]
    return f"la-{digest}"


def default_bank_id() -> str:
    """Warm-layer memory scope id (Mem0 user_id)."""
    return memory_user_id()


# Back-compat alias (prefer default_bank_id() when LA_DATA_DIR may be set)
DEFAULT_BANK_ID = "localagent"


def mem0_dir() -> Path:
    return DATA_DIR / "mem0"


def mem0_qdrant_path() -> Path:
    return mem0_dir() / "qdrant"


def mem0_history_db() -> Path:
    return mem0_dir() / "history.db"

# --- Workspace ---
LA_WORKSPACE = _env("LA_WORKSPACE")
WORKSPACE_DIR = DATA_DIR / "workspace"
WORKSPACE_TASKS_FILE = WORKSPACE_DIR / "tasks.json"
WORKSPACE_TASK_TTL_DAYS = _env_int("LA_WORKSPACE_TASK_TTL_DAYS", "7")
WORKSPACE_TASK_AGENT_DAILY_LIMIT = _env_int("LA_WORKSPACE_TASK_AGENT_DAILY_LIMIT", "3")
WORKSPACE_TASK_MIN_TITLE_LEN = _env_int("LA_WORKSPACE_TASK_MIN_TITLE_LEN", "2")
WORKSPACE_TASK_MIN_RATIONALE_LEN = _env_int("LA_WORKSPACE_TASK_MIN_RATIONALE_LEN", "8")

# --- Agent shell tool ---
SHELL_TIMEOUT = _env_float("LA_SHELL_TIMEOUT", "30")
SHELL_MAX_OUTPUT = _env_int("LA_SHELL_MAX_OUTPUT", "12000")
# always = 每次 run_shell / write_file / edit_file 都需确认；dangerous = 仅危险操作；off = 关闭
TOOL_APPROVAL = _env("LA_TOOL_APPROVAL", "always").lower()
# Observe-phase heuristic compression (no extra LLM) for small local models.
OBSERVE_BUDGET_CHARS = _env_int("LA_OBSERVE_BUDGET_CHARS", "1200")
PREFETCH_BUDGET_CHARS = _env_int("LA_PREFETCH_BUDGET_CHARS", "1500")
OBSERVE_KEEP_HITS = _env_int("LA_OBSERVE_KEEP_HITS", "6")
# STM rolling window (hours). Session-recall loads conversations in this window.
_STM_WINDOW_RAW = _env_float("LA_STM_WINDOW_HOURS", "24")
STM_WINDOW_HOURS = _STM_WINDOW_RAW if _STM_WINDOW_RAW > 0 else 24.0

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
    global OLLAMA_CHAT_TIMEOUT, OLLAMA_CHAT_STREAM, OPENAI_API_KEY, OPENAI_MODEL
    global OPENAI_BASE_URL, OPENAI_TIMEOUT, OPENROUTER_API_KEY, OPENROUTER_MODEL
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
    global OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL, OPENAI_TIMEOUT
    global OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_BASE_URL
    global CURSOR_API_KEY, CURSOR_MODEL, CURSOR_CWD, CURSOR_MAX_RETRIES

    ollama = _ollama_server()
    OLLAMA_BASE_URL = ollama.base_url if ollama else _env("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = ollama.model if ollama else _env("OLLAMA_MODEL", "qwen3.5:4b")
    OLLAMA_THINK = ollama.think if ollama else _env_bool("OLLAMA_THINK", "0")
    OLLAMA_NUM_PREDICT = ollama.num_predict if ollama else _env_int("OLLAMA_NUM_PREDICT", "2048")
    OLLAMA_NUM_CTX = ollama.num_ctx if ollama else _env_int("OLLAMA_NUM_CTX", "8192")
    OLLAMA_KEEP_ALIVE = ollama.keep_alive if ollama else _env("OLLAMA_KEEP_ALIVE", "30m")
    OLLAMA_TIMEOUT = ollama.timeout if ollama else _env_float("OLLAMA_TIMEOUT", "90")
    OLLAMA_CHAT_TIMEOUT = ollama.chat_timeout if ollama else _env_float("LA_OLLAMA_CHAT_TIMEOUT", "12")
    OLLAMA_CHAT_STREAM = ollama.chat_stream if ollama else _env_bool("OLLAMA_CHAT_STREAM", "1")

    openai = get_model_server("openai")
    OPENAI_API_KEY = (
        openai.api_key if openai else (_env("OPENAI_API_KEY") or _env("MINIMAX_API_KEY"))
    )
    OPENAI_MODEL = (
        openai.model
        if openai
        else (_env("OPENAI_MODEL") or _env("MINIMAX_MODEL") or "gpt-4o-mini")
    )
    OPENAI_BASE_URL = (
        openai.base_url
        if openai
        else (
            _env("OPENAI_BASE_URL")
            or _env("MINIMAX_BASE_URL")
            or "https://api.openai.com/v1"
        )
    )
    OPENAI_TIMEOUT = (
        openai.timeout
        if openai
        else _env_float("OPENAI_TIMEOUT", _env("MINIMAX_TIMEOUT") or "120")
    )

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
# auto: Tavily (if key) → SearXNG (if URL) → ddgs (free, no key)
TAVILY_API_KEY = _env("TAVILY_API_KEY")
SEARXNG_URL = _env("LA_SEARXNG_URL")
_raw_web_search = _env("LA_WEB_SEARCH_PROVIDER", "auto").lower() or "auto"
WEB_SEARCH_PROVIDER = (
    _raw_web_search
    if _raw_web_search in ("auto", "ddgs", "tavily", "searxng")
    else "auto"
)

# --- Retrieval tuning ---
SEMANTIC_WEIGHT = _env_float("LA_SEMANTIC_WEIGHT", "0.75")
TIME_DECAY_HALFLIFE_DAYS = _env_float("LA_TIME_HALFLIFE_DAYS", "90")
# When the query has no explicit time intent, bias recall toward recently stored facts.
RECENCY_HALFLIFE_DAYS = _env_float("LA_RECENCY_HALFLIFE_DAYS", "14")
# Mem0 recall: fuse vector search with full-registry BM25/lexical + optional query expand.
MEMORY_RECALL_HYBRID = _env_bool("LA_MEMORY_RECALL_HYBRID", "1")
MEMORY_RECALL_QUERY_EXPAND = _env_bool("LA_MEMORY_RECALL_QUERY_EXPAND", "1")
MEMORY_RECALL_NEIGHBOR_WINDOW = _env_int("LA_MEMORY_RECALL_NEIGHBOR_WINDOW", "0")
# Auto ±N dialog neighbors for WHEN/duration questions when NEIGHBOR_WINDOW is 0.
MEMORY_RECALL_WHEN_EVENT_NEIGHBOR_WINDOW = _env_int(
    "LA_MEMORY_RECALL_WHEN_EVENT_NEIGHBOR_WINDOW", "1"
)
MEMORY_RECALL_RRF_K = _env_int("LA_MEMORY_RECALL_RRF_K", "60")
# Multi-hop / compound questions → rule-based sub-queries fused via RRF.
MEMORY_RECALL_DECOMPOSE = _env_bool("LA_MEMORY_RECALL_DECOMPOSE", "1")
MEMORY_RECALL_DECOMPOSE_MAX = _env_int("LA_MEMORY_RECALL_DECOMPOSE_MAX", "3")
# How many expanded query variants to embed on the vector path (1 = original only).
MEMORY_RECALL_VECTOR_VARIANTS = _env_int("LA_MEMORY_RECALL_VECTOR_VARIANTS", "2")
# Soft-boost hits whose entities overlap the query.
MEMORY_RECALL_ENTITY_BOOST = _env_bool("LA_MEMORY_RECALL_ENTITY_BOOST", "1")
# Soft-boost by cognitive class (semantic / episodic / procedural) vs query intent.
MEMORY_RECALL_CLASS_BOOST = _env_bool("LA_MEMORY_RECALL_CLASS_BOOST", "1")
MEMORY_CLASS_WEIGHT = _env_float("LA_MEMORY_CLASS_WEIGHT", "0.10")
# Local SQLite relation graph overlay (entity/slot edges + hop expansion).
MEMORY_GRAPH = _env_bool("LA_MEMORY_GRAPH", "0")
MEMORY_GRAPH_HOPS = _env_int("LA_MEMORY_GRAPH_HOPS", "2")
# Graph hits expand the candidate pool; default 0 so they do not steal hybrid rank.
MEMORY_GRAPH_BOOST = _env_float("LA_MEMORY_GRAPH_BOOST", "0")
MEMORY_GRAPH_MAX_EXTRAS = _env_int("LA_MEMORY_GRAPH_MAX_EXTRAS", "8")
# After expand+rerank, pin the top-N seed-only winners at the front (Hit@1 stable).
MEMORY_GRAPH_PROTECT_TOP = _env_int("LA_MEMORY_GRAPH_PROTECT_TOP", "1")
# Force-insert up to N graph extras into slots after the protected prefix (Hit@5/8).
MEMORY_GRAPH_FORCE_IN_TOP = _env_int("LA_MEMORY_GRAPH_FORCE_IN_TOP", "3")
# Optional Neo4j precise graph queries (counts / aggregations / multi-hop).
# Independent of LA_MEMORY_GRAPH (SQLite hop expand). Default off.
NEO4J = _env_bool("LA_NEO4J", "0")
NEO4J_URI = _env("LA_NEO4J_URI", "bolt://localhost:7687") or "bolt://localhost:7687"
NEO4J_USER = _env("LA_NEO4J_USER", "neo4j") or "neo4j"
NEO4J_PASSWORD = _env("LA_NEO4J_PASSWORD", "password") or "password"
NEO4J_DATABASE = _env("LA_NEO4J_DATABASE", "neo4j") or "neo4j"
# LLM Text2Cypher (Phase 2); MVP keeps templates only when 0.
NEO4J_TEXT2CYPHER = _env_bool("LA_NEO4J_TEXT2CYPHER", "0")
NEO4J_MAX_ROWS = _env_int("LA_NEO4J_MAX_ROWS", "50")
NEO4J_MIN_CONFIDENCE = _env_float("LA_NEO4J_MIN_CONFIDENCE", "0.5")
# Post-hybrid rerank over a larger candidate pool (cross-encoder / embed / llm).
MEMORY_RERANK = _env_bool("LA_MEMORY_RERANK", "1")
MEMORY_RERANK_BACKEND = _env("LA_MEMORY_RERANK_BACKEND", "auto").lower() or "auto"
MEMORY_RERANK_MODEL = _env(
    "LA_MEMORY_RERANK_MODEL",
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
)
MEMORY_RERANK_CANDIDATES = _env_int("LA_MEMORY_RERANK_CANDIDATES", "24")
# Soft scope: days outside [scope_start, scope_end] still get a medium boost.
MEMORY_SCOPE_NEAR_DAYS = _env_float("LA_MEMORY_SCOPE_NEAR_DAYS", "30")
# Keyword scan of kb/ files — last-resort only after embedding+BM25 miss.
DOC_KEYWORD_FALLBACK = _env_bool("LA_DOC_KEYWORD_FALLBACK", "1")

# --- Ingest memory ---
# Prefer LLM fact extraction; when off, sections go to Cold only (not whole-section Warm).
INGEST_USE_LLM = _env_bool("LA_INGEST_USE_LLM", "1")
INGEST_MEMORY_MAX_SECTION_CHARS = _env_int("LA_INGEST_MEMORY_MAX_CHARS", "1500")
INGEST_MEMORY_MAX_FACTS = _env_int("LA_INGEST_MEMORY_MAX_FACTS", "50")
INGEST_WHOLE_SECTION_WARM = _env_bool("LA_INGEST_WHOLE_SECTION_WARM", "0")
# Long documents: write Warm summary facts (Cold RAG still indexes full text).
INGEST_WARM_SUMMARY = _env_bool("LA_INGEST_WARM_SUMMARY", "1")
INGEST_SUMMARY_MIN_CHARS = _env_int("LA_INGEST_SUMMARY_MIN_CHARS", "800")
INGEST_SUMMARY_MAX_SECTIONS = _env_int("LA_INGEST_SUMMARY_MAX_SECTIONS", "8")
# Shared summarizer (documents + session memorize tasks).
MEMORY_SUMMARY_MAX_CHARS = _env_int("LA_MEMORY_SUMMARY_MAX_CHARS", "600")
MEMORY_SUMMARY_USE_LLM = _env_bool("LA_MEMORY_SUMMARY_USE_LLM", "0")
# Conversation archives (LA chat + ChatGPT export) → Cold RAG.
COLD_CONVERSATION = _env_bool("LA_COLD_CONVERSATION", "1")
COLD_CONVERSATION_SUMMARY = _env_bool("LA_COLD_CONVERSATION_SUMMARY", "1")
# Session exit extract: also write a session-level summary fact.
MEMORY_SESSION_SUMMARY = _env_bool("LA_MEMORY_SESSION_SUMMARY", "1")
# Reflect: limited multi-hop follow-up searches before synthesizing.
MEMORY_REFLECT_MAX_HOPS = _env_int("LA_MEMORY_REFLECT_MAX_HOPS", "2")
MEMORY_REFLECT_TOP_K = _env_int("LA_MEMORY_REFLECT_TOP_K", "8")
# Write-time consolidation (ADD/UPDATE/DELETE/NOOP) against related memories.
MEMORY_CONSOLIDATE = _env_bool("LA_MEMORY_CONSOLIDATE", "1")
MEMORY_CONSOLIDATE_ON_MEMORIZE = _env_bool("LA_MEMORY_CONSOLIDATE_ON_MEMORIZE", "1")
MEMORY_CONSOLIDATE_RELATED_K = _env_int("LA_MEMORY_CONSOLIDATE_RELATED_K", "5")
# Warm write gate: when required and not auto, non-interactive extracts enqueue to pending_queue.json.
MEMORY_APPROVAL_REQUIRED = _env_bool("LA_MEMORY_APPROVAL_REQUIRED", "1")
# Skip queue / prompts and retain immediately (CI, benchmarks, advanced users).
MEMORY_APPROVAL_AUTO = _env_bool("LA_MEMORY_APPROVAL_AUTO", "0")

# --- Memory enrichment ---
MEMORY_ENRICH_USE_LLM = _env_bool("LA_MEMORY_ENRICH_LLM", "0")
MEMORY_BACKEND = _env("LA_MEMORY_BACKEND", "mem0").lower()

# --- Hot-layer profile pin ---
# LLM decides durable identity fields; regex is fallback when LLM fails/unavailable.
PROFILE_PIN_LLM = _env_bool("LA_PROFILE_PIN_LLM", "1")
PROFILE_PIN_REGEX_FALLBACK = _env_bool("LA_PROFILE_PIN_REGEX_FALLBACK", "1")
PROFILE_PIN_MIN_CONFIDENCE = _env_float("LA_PROFILE_PIN_MIN_CONFIDENCE", "0.6")

# --- Mem0 (Warm-layer semantic index) ---
MEM0_INFER = _env_bool("LA_MEM0_INFER", "0")
MEM0_RETAIN_JSON_FALLBACK = _env_bool("LA_MEM0_RETAIN_JSON_FALLBACK", "1")
MEM0_LLM_PROVIDER = _env("LA_MEM0_LLM_PROVIDER").lower()
MEM0_LLM_MODEL = _env("LA_MEM0_LLM_MODEL")
MEM0_LLM_BASE_URL = _env("LA_MEM0_LLM_BASE_URL")
MEM0_LLM_API_KEY = _env("LA_MEM0_LLM_API_KEY")
MEM0_EMBEDDER_PROVIDER = _env("LA_MEM0_EMBEDDER_PROVIDER").lower()
MEM0_EMBEDDER_MODEL = _env("LA_MEM0_EMBEDDER_MODEL")
MEM0_EMBEDDER_BASE_URL = _env("LA_MEM0_EMBEDDER_BASE_URL")
MEM0_EMBEDDER_API_KEY = _env("LA_MEM0_EMBEDDER_API_KEY")
MEM0_EMBEDDER_DIMS = _env_int("LA_MEM0_EMBEDDER_DIMS", "0")

def ensure_data_dirs() -> None:
    """Create runtime data directories if missing."""
    for path in (
        DATA_DIR,
        KB_DIR,
        CONVERSATIONS_DIR,
        CHATGPT_DATA_DIR,
        CHROMA_DIR,
        mem0_dir(),
        mem0_qdrant_path(),
        TASK_LOGS_DIR,
        AUDIT_DIR,
        LOGS_DIR,
        NEWS_DIR,
        NEWS_CACHE_DIR,
        SUMMARIZE_SESSIONS_DIR,
        AWARE_DIR,
        AWARE_NOW_DIR,
        AWARE_CONTEXT_DIR,
        AWARE_SESSIONS_DIR,
        WORKSPACE_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
