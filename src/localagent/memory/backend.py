"""Unified memory backend protocol, factory, and diagnostics."""

from __future__ import annotations

import atexit
import logging
import os
import sys
from typing import Any, Protocol

from localagent import config
from localagent.memory.backends.json_backend import JsonMemoryBackend
from localagent.memory.store import get_memory_store

logger = logging.getLogger(__name__)

__all__ = [
    "MemoryBackend",
    "JsonMemoryBackend",
    "get_memory_backend",
    "reset_memory_backend",
    "shutdown_memory_backend",
    "describe_memory_backend",
    "ensure_mem0_telemetry_disabled",
]


class MemoryBackend(Protocol):
    def backend_name(self) -> str: ...
    def retain(self, content: str, *, metadata: dict[str, Any] | None = None) -> str: ...
    def retain_batch(self, items: list[str], *, metadata: dict[str, Any] | None = None) -> list[str]: ...
    def recall(self, query: str, *, max_results: int = 10) -> list[dict[str, Any]]: ...
    def reflect(self, query: str) -> str | None: ...
    def delete(self, fact_id: str) -> bool: ...
    def remove_by_source_file(self, filename: str) -> int: ...
    def clear(self) -> int: ...
    def count(self) -> int: ...


_backend: MemoryBackend | None = None
_atexit_registered = False


def ensure_mem0_telemetry_disabled() -> None:
    """Keep Mem0 PostHog off by default; honor explicit MEM0_TELEMETRY=True opt-in.

    Mem0 evaluates ``MEM0_TELEMETRY`` at import time and may already have opened a
    PostHog client. Call this before ``import mem0``, and again afterward if the
    module was imported earlier with telemetry still enabled.
    """
    os.environ.setdefault("MEM0_TELEMETRY", "False")
    enabled = os.environ.get("MEM0_TELEMETRY", "False").lower() in ("true", "1", "yes")

    telemetry = sys.modules.get("mem0.memory.telemetry")
    if telemetry is None:
        return

    telemetry.MEM0_TELEMETRY = enabled
    if enabled:
        return

    oss = getattr(telemetry, "_oss_telemetry_instance", None)
    if oss is not None:
        try:
            oss.close()
        except Exception:
            pass
        try:
            telemetry._oss_telemetry_instance = None
        except Exception:
            pass

    client = getattr(telemetry, "client_telemetry", None)
    if client is not None:
        try:
            client.close()
        except Exception:
            pass


def _mem0_importable() -> bool:
    try:
        ensure_mem0_telemetry_disabled()
        import mem0  # noqa: F401

        ensure_mem0_telemetry_disabled()
        return True
    except Exception:
        return False


def _ensure_shutdown_atexit() -> None:
    global _atexit_registered
    if _atexit_registered:
        return
    atexit.register(shutdown_memory_backend)
    _atexit_registered = True


def get_memory_backend() -> MemoryBackend:
    global _backend
    if _backend is not None:
        return _backend

    preference = config.MEMORY_BACKEND
    if preference in ("auto", ""):
        preference = "mem0"

    if preference == "json":
        _backend = JsonMemoryBackend()
        logger.info("using JSON memory backend (LA_MEMORY_BACKEND=json)")
        return _backend

    if preference == "mem0":
        if not _mem0_importable():
            raise RuntimeError(
                "LA_MEMORY_BACKEND=mem0 but mem0ai is not installed. "
                "Install with: pip install 'la-localagent' (mem0ai is a required dependency)."
            )
        from localagent.memory.backends.mem0_backend import Mem0Backend

        try:
            _backend = Mem0Backend()
            _ensure_shutdown_atexit()
            logger.info("using Mem0 memory backend")
            return _backend
        except Exception as exc:
            logger.warning("Mem0 init failed (%s), using JSON fallback", exc)
            _backend = JsonMemoryBackend()
            logger.info("using JSON memory backend (Mem0 init fallback)")
            return _backend

    raise RuntimeError(
        f"Unknown LA_MEMORY_BACKEND={config.MEMORY_BACKEND!r}; expected mem0 or json"
    )


def shutdown_memory_backend() -> None:
    """Close Warm-engine resources (Qdrant) before interpreter exit."""
    global _backend
    if _backend is None:
        return
    close = getattr(_backend, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
    _backend = None


def reset_memory_backend() -> None:
    shutdown_memory_backend()


def describe_memory_backend() -> dict[str, Any]:
    """Return diagnostic info about the active or preferred memory backend."""
    from localagent.memory.backends.mem0_backend import (
        resolve_mem0_embedder_settings,
        resolve_mem0_llm_settings,
    )

    mem0_installed = _mem0_importable()
    llm_settings: dict[str, Any] = {}
    embedder_settings: dict[str, Any] = {}
    if mem0_installed:
        try:
            llm_settings = resolve_mem0_llm_settings()
            embedder_settings = resolve_mem0_embedder_settings()
        except Exception as exc:
            logger.debug("Mem0 settings probe failed: %s", exc)

    try:
        backend = get_memory_backend()
        active = backend.backend_name()
        count = backend.count()
        error = None
    except Exception as exc:
        active = "error"
        count = get_memory_store().count()
        error = str(exc)
        backend = None

    store_count = get_memory_store().count()
    unindexed = 0
    if active == "mem0":
        from localagent.memory.backends.mem0_backend import _is_engine_indexed

        unindexed = sum(
            1 for fact in get_memory_store().all_facts() if not _is_engine_indexed(fact)
        )
    elif active == "json":
        # JSON has no separate vector engine; embedding is computed at recall time.
        unindexed = 0

    return {
        "active_backend": active,
        "preference": config.MEMORY_BACKEND,
        "mem0_installed": mem0_installed,
        "mem0_infer": config.MEM0_INFER,
        "mem0_llm_provider": llm_settings.get("source_provider") or llm_settings.get("provider"),
        "mem0_llm_model": llm_settings.get("model"),
        "mem0_embedder_provider": embedder_settings.get("source_provider")
        or embedder_settings.get("provider"),
        "mem0_embedder_model": embedder_settings.get("model"),
        "mem0_embedder_dims": embedder_settings.get("embedding_dims"),
        "retain_json_fallback": config.MEM0_RETAIN_JSON_FALLBACK,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "memory_count": count,
        "store_count": store_count,
        "unindexed_count": unindexed,
        "profile_pin_llm": config.PROFILE_PIN_LLM,
        "bank_id": config.default_bank_id(),
        "store_file": str(config.MEMORY_STORE_FILE),
        "mem0_dir": str(config.mem0_dir()),
        "error": error,
        "backend_class": backend.__class__.__name__ if backend else None,
    }
