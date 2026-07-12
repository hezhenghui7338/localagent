"""Hindsight client with JSON store fallback and unified memory backend."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Protocol

from localagent import config
from localagent.memory.enrich import enrich_memory
from localagent.memory.store import MemoryFact, get_memory_store
from localagent.memory.temporal import memory_effective_time, resolve_memory_times
from localagent.memory.value_filter import is_valuable

logger = logging.getLogger(__name__)


def _is_hindsight_transient_error(exc: BaseException) -> bool:
    """True when retain failed due to a dropped daemon/HTTP connection (retryable)."""
    exc_name = type(exc).__name__
    if exc_name in (
        "ServerDisconnectedError",
        "ClientConnectorError",
        "ConnectionResetError",
        "BrokenPipeError",
    ):
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in ("disconnected", "connection reset", "broken pipe", "reset by peer")
    )


def _is_hindsight_retain_error(exc: BaseException) -> bool:
    """True when Hindsight retain failed due to LLM/service issues (recoverable)."""
    if _is_hindsight_transient_error(exc):
        return True
    exc_name = type(exc).__name__
    if exc_name in ("ServiceException", "ApiException", "ApiTypeError"):
        return True
    text = str(exc).lower()
    markers = (
        "fact extraction failed",
        "404 not found",
        "connection",
        "timeout",
        "internal server error",
        "llm connection verification failed",
        "client error",
    )
    return any(marker in text for marker in markers)


def _ollama_openai_base_url(base_url: str | None) -> str | None:
    """Normalize Ollama host URL for Hindsight's OpenAI-compatible client."""
    if not base_url:
        return base_url
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        return url
    return f"{url}/v1"


def resolve_hindsight_llm_settings() -> dict[str, str | None]:
    """Pick LLM settings for Hindsight fact extraction."""
    from localagent.models.router import get_model_router

    router = get_model_router()

    if config.HINDSIGHT_LLM_PROVIDER:
        provider = config.HINDSIGHT_LLM_PROVIDER
        model = config.HINDSIGHT_LLM_MODEL or config.OLLAMA_MODEL
        base_url = config.HINDSIGHT_LLM_BASE_URL or None
        api_key = config.HINDSIGHT_LLM_API_KEY or None
        if provider == "ollama":
            base_url = _ollama_openai_base_url(base_url or config.OLLAMA_BASE_URL)
            if not config.HINDSIGHT_LLM_MODEL:
                model = router.resolve_ollama_model()
        elif provider in ("openai", "openrouter") and not api_key:
            from localagent.model_servers import first_usable_openai_server

            cloud = first_usable_openai_server(config.MODEL_SERVERS)
            if cloud:
                api_key = cloud.api_key
                base_url = base_url or cloud.base_url
                model = model or cloud.model
        return {
            "provider": "openai" if provider == "openrouter" else provider,
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
        }

    ollama = config.get_model_server("ollama")
    ollama_base = _ollama_openai_base_url(
        ollama.base_url if ollama else config.OLLAMA_BASE_URL
    )
    if router.is_ollama_available() and router.list_completion_models():
        resolved = router.resolve_ollama_model()
        if resolved:
            return {
                "provider": "ollama",
                "model": resolved,
                "base_url": ollama_base,
                "api_key": None,
            }

    from localagent.model_servers import first_usable_openai_server

    cloud = first_usable_openai_server(config.MODEL_SERVERS)
    if cloud:
        return {
            "provider": "openai",
            "model": cloud.model,
            "base_url": cloud.base_url,
            "api_key": cloud.api_key,
        }
    return {
        "provider": "ollama",
        "model": router.resolve_ollama_model() if router.is_ollama_available() else config.OLLAMA_MODEL,
        "base_url": ollama_base,
        "api_key": None,
    }


def hindsight_llm_available() -> bool:
    """Whether Hindsight retain can reach an LLM backend."""
    settings = resolve_hindsight_llm_settings()
    if settings["provider"] == "ollama":
        from localagent.models.router import get_model_router

        router = get_model_router()
        return router.is_ollama_available() and bool(router.list_completion_models())
    return bool(settings.get("api_key"))


def _stop_hindsight_daemon(profile: str) -> None:
    """Stop an existing Hindsight embed daemon so the next start picks up fresh LLM config."""
    try:
        from hindsight_embed import daemon_client  # type: ignore

        daemon_client.stop_daemon(profile)
    except Exception:
        logger.debug("Could not stop Hindsight daemon for profile %s", profile, exc_info=True)


def resolve_hindsight_extraction_mode() -> str:
    """Pick Hindsight retain extraction mode.

    Local Ollama models often fail structured JSON fact extraction; ``chunks`` stores
    raw text with embeddings and skips the LLM extraction step.
    """
    explicit = config.HINDSIGHT_EXTRACTION_MODE
    valid = {"concise", "verbose", "custom", "chunks", "verbatim"}
    if explicit and explicit != "auto":
        if explicit in valid:
            return explicit
        logger.warning("Unknown LA_HINDSIGHT_EXTRACTION_MODE=%s; using auto", explicit)

    settings = resolve_hindsight_llm_settings()
    if settings["provider"] == "ollama":
        return "chunks"
    return "concise"


def hindsight_usable() -> bool:
    """Whether Hindsight backend can be initialized."""
    if not _hindsight_importable():
        return False
    if resolve_hindsight_extraction_mode() == "chunks":
        return True
    return hindsight_llm_available()


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


def _parse_retain_ids(result: Any) -> list[str]:
    """Extract memory IDs from a Hindsight retain response (if present)."""
    if result is None:
        return []
    if isinstance(result, str):
        return [result]
    if isinstance(result, dict):
        for key in ("memory_ids", "ids", "memory_id", "id"):
            value = result.get(key)
            if value:
                return [str(item) for item in value] if isinstance(value, list) else [str(value)]
    for key in ("memory_ids", "ids", "memory_id", "id"):
        value = getattr(result, key, None)
        if value:
            return [str(item) for item in value] if isinstance(value, list) else [str(value)]
    # RetainResponse (v0.8+) returns operation_id(s), not memory unit ids.
    return []


def _iter_recall_results(results: Any) -> list[Any]:
    if results is None:
        return []
    if isinstance(results, list):
        return results
    items = getattr(results, "results", None)
    if items is not None:
        return list(items)
    return []


def _recall_item_id(item: Any) -> str:
    for key in ("id", "memory_id"):
        value = getattr(item, key, None)
        if value:
            return str(value)
    if isinstance(item, dict):
        for key in ("id", "memory_id"):
            if item.get(key):
                return str(item[key])
    return ""


def _recall_item_text(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or item.get("content") or item)
    return str(getattr(item, "text", None) or getattr(item, "content", None) or item)


def _recall_item_score(item: Any, *, index: int) -> float:
    for key in ("score", "relevance", "rank"):
        value = getattr(item, key, None)
        if value is None and isinstance(item, dict):
            value = item.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass
    return max(0.05, 1.0 - index * 0.04)


def _is_hindsight_indexed(fact: MemoryFact) -> bool:
    """True when this fact was retained into the Hindsight engine."""
    meta = fact.metadata or {}
    if meta.get("backend") == "hindsight":
        return True
    if meta.get("hindsight_id"):
        return True
    hindsight_ids = meta.get("hindsight_ids")
    return isinstance(hindsight_ids, list) and bool(hindsight_ids)


def _local_only_facts() -> list[MemoryFact]:
    """Facts kept only in the JSON registry (ingest / JSON fallback retain)."""
    return [fact for fact in get_memory_store().all_facts() if not _is_hindsight_indexed(fact)]


def _dedupe_recall_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for hit in hits:
        hit_id = str(hit.get("id") or "")
        if hit_id:
            if hit_id in seen:
                continue
            seen.add(hit_id)
        merged.append(hit)
    return merged


def _resolve_store_fact(store: Any, *, memory_id: str, text: str) -> Any | None:
    """Match a Hindsight recall item to the local enrichment registry."""
    if memory_id:
        fact = store.get(memory_id)
        if fact is not None:
            return fact
        fact = store.find_by_hindsight_id(memory_id)
        if fact is not None:
            return fact
    return store.find_by_text(text)


def _merge_recall_hit(
    item: Any,
    *,
    index: int,
    store_fact: MemoryFact | None,
) -> dict[str, Any]:
    memory_id = _recall_item_id(item)
    text = _recall_item_text(item)
    score = _recall_item_score(item, index=index)

    if store_fact is not None:
        meta = dict(store_fact.metadata or {})
        meta.setdefault("backend", "hindsight")
        effective_at = memory_effective_time(metadata=meta, created_at=store_fact.created_at)
        return {
            "id": store_fact.id,
            "text": store_fact.text or text,
            "score": score,
            "source_file": store_fact.source_file,
            "section_heading": store_fact.section_heading,
            "created_at": effective_at,
            "metadata": meta,
            "source": "hindsight",
        }

    return {
        "id": memory_id or f"hindsight-{index}",
        "text": text,
        "score": score,
        "source_file": "",
        "section_heading": "",
        "created_at": "",
        "metadata": {"backend": "hindsight"},
        "source": "hindsight",
    }


def _save_registry_fact(
    *,
    fact_id: str,
    content: str,
    enriched,
    metadata: dict[str, Any],
) -> MemoryFact | None:
    """Persist enrichment metadata locally (registry for CLI browse/forget)."""
    store = get_memory_store()
    meta = dict(metadata)
    meta.update(enriched.to_metadata())
    meta["backend"] = "hindsight"
    meta["hindsight_id"] = fact_id

    times = resolve_memory_times(
        text=content,
        occurred_at=meta.pop("occurred_at", None),
        recorded_at=meta.pop("recorded_at", None),
        indexed_at=meta.pop("indexed_at", None),
        legacy_created_at=meta.pop("created_at", None),
        extract_occurred_from_text=bool(meta.get("extract_occurred_from_text", True)),
    )
    meta.update(times)

    fact = store.retain_from_section(
        filename=meta.get("source_file", "manual"),
        heading=meta.get("section_heading", meta.get("source", "direct")),
        text=content,
        chunk_id=meta.get("chunk_id", str(uuid.uuid4())[:8]),
        enrichment=enriched,
        extra_metadata=meta,
        fact_id=fact_id,
    )
    store.save()
    return fact


def _invalidate_hindsight_memory(client: Any, *, bank_id: str, memory_id: str) -> bool:
    """Soft-delete a memory in Hindsight (append-only; invalidate instead of hard delete)."""
    if not memory_id:
        return False

    try:
        memory_api = getattr(client, "memory", None)
        if memory_api is not None and hasattr(memory_api, "update_memory"):
            update_request = {"state": "invalidated", "reason": "LA forget"}
            try:
                from hindsight_client.models import UpdateMemoryRequest  # type: ignore

                update_request = UpdateMemoryRequest(state="invalidated", reason="LA forget")
            except Exception:
                pass
            memory_api.update_memory(
                bank_id=bank_id,
                memory_id=memory_id,
                update_memory_request=update_request,
            )
            return True
    except Exception as exc:
        logger.warning("Hindsight invalidate failed for %s: %s", memory_id, exc)

    return False


class JsonMemoryBackend:
    """JSON file store with scoped_recall (fallback when Hindsight unavailable)."""

    def backend_name(self) -> str:
        return "json"

    def retain(self, content: str, *, metadata: dict[str, Any] | None = None) -> str:
        if not is_valuable(content):
            return ""
        store = get_memory_store()
        meta = dict(metadata or {})
        enriched = enrich_memory(
            content,
            heading=meta.get("section_heading", meta.get("source", "direct")),
            context=meta.get("source_file", "manual"),
        )
        fact = store.retain_from_section(
            filename=meta.get("source_file", "manual"),
            heading=meta.get("section_heading", meta.get("source", "direct")),
            text=content,
            chunk_id=meta.get("chunk_id", str(uuid.uuid4())[:8]),
            enrichment=enriched,
            extra_metadata={**meta, "backend": "json"},
        )
        store.save()
        return fact.id if fact else ""

    def retain_batch(self, items: list[str], *, metadata: dict[str, Any] | None = None) -> list[str]:
        ids: list[str] = []
        for item in items:
            fact_id = self.retain(item, metadata=metadata)
            if fact_id:
                ids.append(fact_id)
        return ids

    def recall(self, query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
        from localagent.memory.scoped_recall import scoped_recall

        return scoped_recall(query, max_results=max_results)

    def reflect(self, query: str) -> str | None:
        return None

    def delete(self, fact_id: str) -> bool:
        store = get_memory_store()
        removed = store.delete(fact_id)
        if removed is None:
            return False
        store.save()
        return True

    def remove_by_source_file(self, filename: str) -> int:
        store = get_memory_store()
        removed = store.remove_by_source_file(filename)
        if removed:
            store.save()
        return removed

    def clear(self) -> int:
        store = get_memory_store()
        count = store.count()
        store.clear()
        store.save()
        return count

    def count(self) -> int:
        return get_memory_store().count()


def _apply_hindsight_reflect_llm_override(client: Any, llm: dict[str, str | None]) -> None:
    """Send reflect to a cloud LLM when the primary backend is local Ollama."""
    if llm.get("provider") != "ollama":
        return
    from localagent.model_servers import first_usable_openai_server

    cloud = first_usable_openai_server(config.MODEL_SERVERS)
    if cloud is None:
        return
    client.config["HINDSIGHT_API_REFLECT_LLM_PROVIDER"] = "openai"
    client.config["HINDSIGHT_API_REFLECT_LLM_MODEL"] = cloud.model
    client.config["HINDSIGHT_API_REFLECT_LLM_BASE_URL"] = cloud.base_url
    client.config["HINDSIGHT_API_REFLECT_LLM_API_KEY"] = cloud.api_key
    logger.info(
        "Hindsight reflect using cloud LLM %s/%s (primary retain LLM: ollama/%s)",
        "openai",
        cloud.model,
        llm.get("model"),
    )


class HindsightBackend:
    """Hindsight embedded client — primary Warm-layer engine when available."""

    def __init__(self) -> None:
        from hindsight import HindsightEmbedded  # type: ignore

        llm = resolve_hindsight_llm_settings()
        init_kwargs: dict[str, Any] = {
            "profile": config.hindsight_profile(),
            "llm_provider": llm["provider"],
            "llm_model": llm["model"],
        }
        if llm.get("base_url"):
            init_kwargs["llm_base_url"] = llm["base_url"]
        if llm.get("api_key"):
            init_kwargs["llm_api_key"] = llm["api_key"]
        profile = init_kwargs["profile"]
        # Stop any running daemon first — ensure_running() reuses a live daemon and
        # would keep stale LLM env (e.g. wrong Ollama model name).
        _stop_hindsight_daemon(profile)
        self._client = HindsightEmbedded(**init_kwargs)
        if llm.get("provider") == "ollama":
            # qwen3.x thinking tokens can exhaust the reflect budget via OpenAI API.
            self._client.config["HINDSIGHT_API_LLM_EXTRA_BODY"] = json.dumps({"think": False})
        _apply_hindsight_reflect_llm_override(self._client, llm)
        self._bank_id = config.default_bank_id()
        self._llm_settings = llm
        self._ensure_bank()
        if llm.get("provider") == "ollama" and llm.get("model") != config.OLLAMA_MODEL:
            logger.info(
                "Hindsight using resolved Ollama model %s (configured: %s)",
                llm["model"],
                config.OLLAMA_MODEL,
            )

    def backend_name(self) -> str:
        return "hindsight"

    def _json_fallback_retain(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None,
        reason: str,
    ) -> str:
        meta = dict(metadata or {})
        meta["hindsight_retain_failed"] = reason[:240]
        logger.warning("Hindsight retain failed, saved to JSON store: %s", reason[:120])
        return JsonMemoryBackend().retain(content, metadata=meta)

    def _ensure_bank(self) -> None:
        try:
            if hasattr(self._client, "create_bank"):
                mode = resolve_hindsight_extraction_mode()
                bank_kwargs: dict[str, Any] = {
                    "bank_id": self._bank_id,
                    "background": "LocalAgent personal assistant long-term memory",
                    "retain_extraction_mode": mode,
                }
                if mode == "chunks":
                    bank_kwargs["enable_observations"] = False
                self._client.create_bank(**bank_kwargs)
                if mode == "chunks":
                    logger.info(
                        "Hindsight retain_extraction_mode=chunks (no LLM JSON extraction; "
                        "set LA_HINDSIGHT_EXTRACTION_MODE=concise for cloud LLM fact extraction)"
                    )
        except Exception:
            pass

    def retain(self, content: str, *, metadata: dict[str, Any] | None = None) -> str:
        if not is_valuable(content):
            return ""
        meta = dict(metadata or {})
        enriched = enrich_memory(
            content,
            heading=meta.get("section_heading", meta.get("source", "direct")),
            context=meta.get("source_file", "manual"),
        )
        retain_meta = dict(meta)
        retain_meta.update(enriched.to_metadata())
        tags = [f"topic:{tag}" for tag in enriched.tags]
        if retain_meta.get("source"):
            tags.append(f"source:{retain_meta['source']}")

        context = meta.get("source_file") or meta.get("source") or "manual"
        local_id = str(uuid.uuid4())
        document_id = str(meta.get("document_id") or local_id)

        retain_kwargs: dict[str, Any] = {
            "bank_id": self._bank_id,
            "content": content,
            "context": context,
            "document_id": document_id,
        }
        string_meta = {k: str(v) for k, v in retain_meta.items() if v is not None}
        if string_meta:
            retain_kwargs["metadata"] = string_meta
        if tags:
            retain_kwargs["tags"] = tags

        result = None
        retain_exc: BaseException | None = None
        for attempt in range(2):
            try:
                result = self._client.retain(**retain_kwargs)
                retain_exc = None
                break
            except Exception as exc:
                retain_exc = exc
                if attempt == 0 and _is_hindsight_transient_error(exc):
                    logger.warning(
                        "Hindsight retain connection lost, retrying after daemon restart: %s",
                        exc,
                    )
                    continue
                break
        if retain_exc is not None:
            if config.HINDSIGHT_RETAIN_JSON_FALLBACK and _is_hindsight_retain_error(retain_exc):
                return self._json_fallback_retain(
                    content, metadata=meta, reason=str(retain_exc)
                )
            raise retain_exc

        memory_ids = _parse_retain_ids(result)
        primary_id = memory_ids[0] if memory_ids else local_id
        if len(memory_ids) > 1:
            retain_meta["hindsight_ids"] = memory_ids

        fact = _save_registry_fact(
            fact_id=primary_id,
            content=content,
            enriched=enriched,
            metadata=retain_meta,
        )
        return fact.id if fact else primary_id

    def retain_batch(self, items: list[str], *, metadata: dict[str, Any] | None = None) -> list[str]:
        ids: list[str] = []
        for item in items:
            fact_id = self.retain(item, metadata=metadata)
            if fact_id:
                ids.append(fact_id)
        return ids

    def recall(self, query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
        from localagent.memory.scoped_recall import rerank_hits_temporally, scoped_recall

        prefetch = max(max_results * 3, 20)
        local_only = _local_only_facts()

        hindsight_hits: list[dict[str, Any]] = []
        try:
            results = self._client.recall(
                bank_id=self._bank_id,
                query=query,
                max_tokens=4096,
            )
            store = get_memory_store()
            for index, item in enumerate(_iter_recall_results(results)):
                memory_id = _recall_item_id(item)
                text = _recall_item_text(item)
                store_fact = _resolve_store_fact(store, memory_id=memory_id, text=text)
                hindsight_hits.append(_merge_recall_hit(item, index=index, store_fact=store_fact))
        except Exception as exc:
            logger.warning("Hindsight recall failed (%s), falling back to local registry", exc)
            return JsonMemoryBackend().recall(query, max_results=max_results)

        local_hits = (
            scoped_recall(query, max_results=prefetch, facts=local_only)
            if local_only
            else []
        )
        merged = _dedupe_recall_hits(hindsight_hits + local_hits)
        if not merged:
            return JsonMemoryBackend().recall(query, max_results=max_results)

        return rerank_hits_temporally(query, merged, max_results=max_results)

    def reflect(self, query: str) -> str | None:
        try:
            response = self._client.reflect(
                bank_id=self._bank_id,
                query=query,
                include_facts=True,
            )
        except Exception as exc:
            logger.warning("Hindsight reflect failed: %s", exc)
            return None
        text = getattr(response, "text", None)
        if text:
            return str(text)
        if isinstance(response, dict):
            return str(response.get("text") or "")
        return str(response) if response else None

    def delete(self, fact_id: str) -> bool:
        store = get_memory_store()
        fact = store.get(fact_id)
        if fact is None:
            return False

        hindsight_id = str((fact.metadata or {}).get("hindsight_id") or fact.id)
        _invalidate_hindsight_memory(self._client, bank_id=self._bank_id, memory_id=hindsight_id)
        store.delete(fact_id)
        store.save()
        return True

    def remove_by_source_file(self, filename: str) -> int:
        store = get_memory_store()
        targets = [fact for fact in store.all_facts() if fact.source_file == filename]
        removed = 0
        for fact in targets:
            if self.delete(fact.id):
                removed += 1
        return removed

    def clear(self) -> int:
        count = self.count()
        try:
            if hasattr(self._client, "clear_memories"):
                self._client.clear_memories(bank_id=self._bank_id)
            elif hasattr(self._client, "delete_bank"):
                self._client.delete_bank(bank_id=self._bank_id)
                self._ensure_bank()
        except Exception as exc:
            logger.warning("Hindsight clear failed: %s", exc)

        store = get_memory_store()
        store.clear()
        store.save()
        return count

    def count(self) -> int:
        try:
            if hasattr(self._client, "list_memories"):
                response = self._client.list_memories(bank_id=self._bank_id, limit=1000)
                items = getattr(response, "items", None)
                if items is None and isinstance(response, dict):
                    items = response.get("items")
                if items is not None:
                    return len(items)
            memory_api = getattr(self._client, "memory", None)
            if memory_api is not None and hasattr(memory_api, "list_memories"):
                response = memory_api.list_memories(bank_id=self._bank_id, state="valid")
                items = getattr(response, "items", None)
                if items is not None:
                    return len(items)
        except Exception:
            pass
        return get_memory_store().count()


_backend: MemoryBackend | None = None


def _hindsight_importable() -> bool:
    try:
        import hindsight  # noqa: F401

        return True
    except Exception:
        return False


def get_memory_backend() -> MemoryBackend:
    global _backend
    if _backend is not None:
        return _backend

    preference = config.MEMORY_BACKEND
    if preference == "json":
        _backend = JsonMemoryBackend()
        logger.info("using JSON memory backend (LA_MEMORY_BACKEND=json)")
        return _backend

    if preference == "hindsight":
        if not _hindsight_importable():
            raise RuntimeError(
                "LA_MEMORY_BACKEND=hindsight but hindsight is not installed. "
                "Use Python 3.11+ and: pip install -e '.[hindsight]'"
            )
        if not hindsight_usable():
            raise RuntimeError(
                "LA_MEMORY_BACKEND=hindsight but Hindsight is not ready. "
                "Start Ollama, set LA_HINDSIGHT_LLM_PROVIDER + API key, "
                "or use LA_HINDSIGHT_EXTRACTION_MODE=chunks."
            )
        _backend = HindsightBackend()
        logger.info("using Hindsight memory backend (forced)")
        return _backend

    if _hindsight_importable() and hindsight_usable():
        try:
            _backend = HindsightBackend()
            logger.info("using Hindsight memory backend")
            return _backend
        except Exception as exc:
            logger.warning("Hindsight init failed (%s), using JSON fallback", exc)
    elif _hindsight_importable():
        logger.warning(
            "Hindsight installed but not ready (Ollama down / no API key); using JSON backend"
        )

    _backend = JsonMemoryBackend()
    logger.info("using JSON memory backend")
    return _backend


def reset_memory_backend() -> None:
    global _backend
    _backend = None


def describe_memory_backend() -> dict[str, Any]:
    """Return diagnostic info about the active or preferred memory backend."""
    import sys

    hindsight_installed = _hindsight_importable()
    llm_available = hindsight_llm_available() if hindsight_installed else False
    extraction_mode = resolve_hindsight_extraction_mode() if hindsight_installed else None
    llm_settings = resolve_hindsight_llm_settings() if hindsight_installed else {}
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

    return {
        "active_backend": active,
        "preference": config.MEMORY_BACKEND,
        "hindsight_installed": hindsight_installed,
        "hindsight_llm_available": llm_available,
        "hindsight_extraction_mode": extraction_mode,
        "hindsight_llm_provider": llm_settings.get("provider"),
        "hindsight_llm_model": llm_settings.get("model"),
        "ollama_model_configured": config.OLLAMA_MODEL,
        "retain_json_fallback": config.HINDSIGHT_RETAIN_JSON_FALLBACK,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "python_ok_for_hindsight": sys.version_info >= (3, 11),
        "memory_count": count,
        "bank_id": config.default_bank_id(),
        "store_file": str(config.MEMORY_STORE_FILE),
        "error": error,
        "backend_class": backend.__class__.__name__ if backend else None,
    }
