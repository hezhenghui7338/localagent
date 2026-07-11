"""Path and runtime configuration."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_OVERRIDE = os.getenv("LA_DATA_DIR", "").strip()
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

# Workspace root for git/file/todo context (defaults to process cwd)
LA_WORKSPACE = os.getenv("LA_WORKSPACE", "").strip()

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".xlsx"}
DEFAULT_USER_ID = "default_user"
DEFAULT_BANK_ID = "localagent"

# Model routing
VALID_PROVIDERS = ("ollama", "openrouter", "cursor")
DEFAULT_MODEL_PROVIDER = "auto"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")
# Qwen3 等推理模型默认会生成大量 thinking token，chat 极慢；默认关闭
OLLAMA_THINK = os.getenv("OLLAMA_THINK", "0").lower() in ("1", "true", "yes")
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "512"))
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "90"))
# auto 模式下 Ollama 首 token 超过此秒数则降级到 OpenRouter 等
OLLAMA_CHAT_TIMEOUT = float(os.getenv("LA_OLLAMA_CHAT_TIMEOUT", "12"))
OLLAMA_CHAT_STREAM = os.getenv("OLLAMA_CHAT_STREAM", "1").lower() in ("1", "true", "yes")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
CURSOR_API_KEY = os.getenv("CURSOR_API_KEY", "")
CURSOR_MODEL = os.getenv("CURSOR_MODEL", "composer-2.5")
CURSOR_CWD = os.getenv("CURSOR_CWD", str(PROJECT_ROOT))


def parse_provider_priority() -> list[str]:
    """Parse LA_MODEL_PROVIDER_PRIORITY (comma-separated, auto mode fallback order)."""
    valid = set(VALID_PROVIDERS)
    raw = os.getenv("LA_MODEL_PROVIDER_PRIORITY", "ollama,openrouter,cursor")
    ordered: list[str] = []
    for part in raw.split(","):
        name = part.strip().lower()
        if name in valid and name not in ordered:
            ordered.append(name)
    for provider in VALID_PROVIDERS:
        if provider not in ordered:
            ordered.append(provider)
    return ordered


MODEL_PROVIDER_PRIORITY = parse_provider_priority()


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

# Web search
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Retrieval tuning
SEMANTIC_WEIGHT = float(os.getenv("LA_SEMANTIC_WEIGHT", "0.75"))
TIME_DECAY_HALFLIFE_DAYS = float(os.getenv("LA_TIME_HALFLIFE_DAYS", "90"))

# Ingest memory: heuristic by default; set LA_INGEST_USE_LLM=1 for LLM fact extraction (slow)
INGEST_USE_LLM = os.getenv("LA_INGEST_USE_LLM", "0").lower() in ("1", "true", "yes")
INGEST_MEMORY_MAX_SECTION_CHARS = int(os.getenv("LA_INGEST_MEMORY_MAX_CHARS", "1500"))
INGEST_MEMORY_MAX_FACTS = int(os.getenv("LA_INGEST_MEMORY_MAX_FACTS", "50"))

# Memory enrichment at write time (title / tags / summary; Hindsight & Mem0 pattern)
MEMORY_ENRICH_USE_LLM = os.getenv("LA_MEMORY_ENRICH_LLM", "0").lower() in ("1", "true", "yes")


def ensure_data_dirs() -> None:
    """Create runtime data directories if missing."""
    for path in (DATA_DIR, KB_DIR, CONVERSATIONS_DIR, CHATGPT_DATA_DIR, CHROMA_DIR, TASK_LOGS_DIR, AUDIT_DIR):
        path.mkdir(parents=True, exist_ok=True)
