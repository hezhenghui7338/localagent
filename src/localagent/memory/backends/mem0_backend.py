"""Mem0 open-source backend — primary Warm-layer semantic memory engine."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from localagent import config
from localagent.memory.enrich import enrich_memory
from localagent.memory.store import MemoryFact, get_memory_store
from localagent.memory.temporal import memory_effective_time, resolve_memory_times
from localagent.memory.value_filter import is_valuable

logger = logging.getLogger(__name__)

_KNOWN_EMBED_DIMS: dict[str, int] = {
    "bge-m3": 1024,
    "bge-m3:latest": 1024,
    "nomic-embed-text": 768,
    "nomic-embed-text:latest": 768,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

_OLLAMA_EMBED_HINTS = ("embed", "bge", "nomic", "e5", "minilm", "mxbai")


def _ollama_openai_base_url(base_url: str | None) -> str | None:
    if not base_url:
        return base_url
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        return url
    return f"{url}/v1"


def _looks_like_embed_model(name: str) -> bool:
    lower = name.lower()
    return any(hint in lower for hint in _OLLAMA_EMBED_HINTS)


def _guess_embed_dims(model: str) -> int:
    if model in _KNOWN_EMBED_DIMS:
        return _KNOWN_EMBED_DIMS[model]
    base = model.split(":")[0].lower()
    for key, dims in _KNOWN_EMBED_DIMS.items():
        if key.split(":")[0] == base or base.startswith(key.split(":")[0]):
            return dims
    if "bge-m3" in base:
        return 1024
    if "nomic" in base:
        return 768
    return 1536


def resolve_mem0_llm_settings() -> dict[str, str | None]:
    """Pick LLM settings for Mem0 (used when infer=True or unused otherwise)."""
    from localagent.models.router import get_model_router

    router = get_model_router()

    if config.MEM0_LLM_PROVIDER:
        provider = config.MEM0_LLM_PROVIDER
        model = config.MEM0_LLM_MODEL or config.OLLAMA_MODEL
        base_url = config.MEM0_LLM_BASE_URL or None
        api_key = config.MEM0_LLM_API_KEY or None
        if provider == "ollama":
            base_url = _ollama_openai_base_url(base_url or config.OLLAMA_BASE_URL)
            api_key = api_key or "ollama"
            if not config.MEM0_LLM_MODEL:
                model = router.resolve_ollama_model()
        elif provider in ("openai", "openrouter") and not api_key:
            from localagent.model_servers import first_usable_openai_server

            cloud = first_usable_openai_server(config.MODEL_SERVERS)
            if cloud:
                api_key = cloud.api_key
                base_url = base_url or cloud.base_url
                model = model or cloud.model
        return {
            "provider": "openai" if provider in ("openrouter", "ollama") else provider,
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "source_provider": provider,
        }

    if router.is_ollama_available() and router.list_completion_models():
        resolved = router.resolve_ollama_model()
        if resolved:
            return {
                "provider": "openai",
                "model": resolved,
                "base_url": _ollama_openai_base_url(config.OLLAMA_BASE_URL),
                "api_key": "ollama",
                "source_provider": "ollama",
            }

    from localagent.model_servers import first_usable_openai_server

    cloud = first_usable_openai_server(config.MODEL_SERVERS)
    if cloud:
        return {
            "provider": "openai",
            "model": cloud.model,
            "base_url": cloud.base_url,
            "api_key": cloud.api_key,
            "source_provider": cloud.provider,
        }
    return {
        "provider": "openai",
        "model": config.OLLAMA_MODEL,
        "base_url": _ollama_openai_base_url(config.OLLAMA_BASE_URL),
        "api_key": "ollama",
        "source_provider": "ollama",
    }


def resolve_mem0_embedder_settings() -> dict[str, Any]:
    """Pick embedder settings for Mem0 vector search."""
    from localagent.models.router import get_model_router

    router = get_model_router()

    if config.MEM0_EMBEDDER_PROVIDER or config.MEM0_EMBEDDER_MODEL:
        provider = config.MEM0_EMBEDDER_PROVIDER or "openai"
        model = config.MEM0_EMBEDDER_MODEL or "text-embedding-3-small"
        base_url = config.MEM0_EMBEDDER_BASE_URL or None
        api_key = config.MEM0_EMBEDDER_API_KEY or None
        source = provider
        if provider == "ollama":
            provider = "openai"
            base_url = _ollama_openai_base_url(base_url or config.OLLAMA_BASE_URL)
            api_key = api_key or "ollama"
            source = "ollama"
        elif provider in ("openai", "openrouter") and not api_key:
            from localagent.model_servers import first_usable_openai_server

            cloud = first_usable_openai_server(config.MODEL_SERVERS)
            if cloud:
                api_key = cloud.api_key
                base_url = base_url or cloud.base_url
                source = cloud.provider
        dims = config.MEM0_EMBEDDER_DIMS or _guess_embed_dims(model)
        return {
            "provider": "openai" if provider == "openrouter" else provider,
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "embedding_dims": dims,
            "source_provider": source,
        }

    if router.is_ollama_available():
        embed_model = _pick_ollama_embed_model(router)
        if embed_model:
            dims = config.MEM0_EMBEDDER_DIMS or _guess_embed_dims(embed_model)
            return {
                "provider": "openai",
                "model": embed_model,
                "base_url": _ollama_openai_base_url(config.OLLAMA_BASE_URL),
                "api_key": "ollama",
                "embedding_dims": dims,
                "source_provider": "ollama",
            }

    from localagent.model_servers import first_usable_openai_server

    cloud = first_usable_openai_server(config.MODEL_SERVERS)
    if cloud:
        model = "text-embedding-3-small"
        dims = config.MEM0_EMBEDDER_DIMS or _guess_embed_dims(model)
        return {
            "provider": "openai",
            "model": model,
            "base_url": cloud.base_url,
            "api_key": cloud.api_key,
            "embedding_dims": dims,
            "source_provider": cloud.provider,
        }

    # Last resort: point at local Ollama even if probe failed.
    model = config.MEM0_EMBEDDER_MODEL or "nomic-embed-text"
    return {
        "provider": "openai",
        "model": model,
        "base_url": _ollama_openai_base_url(config.OLLAMA_BASE_URL),
        "api_key": "ollama",
        "embedding_dims": config.MEM0_EMBEDDER_DIMS or _guess_embed_dims(model),
        "source_provider": "ollama",
    }


def _pick_ollama_embed_model(router: Any) -> str | None:
    """Prefer an Ollama embedding-capable tag when available."""
    try:
        models = router._list_ollama_models()  # noqa: SLF001 — shared Ollama tag probe
    except Exception:
        models = []
    names: list[str] = []
    for item in models or []:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("model") or "")
        else:
            name = str(item)
        if name:
            names.append(name)
    embed_names = [n for n in names if _looks_like_embed_model(n)]
    if embed_names:
        for preferred in ("bge-m3", "nomic-embed-text"):
            for name in embed_names:
                if name.startswith(preferred):
                    return name
        return embed_names[0]
    return None


def build_mem0_config() -> dict[str, Any]:
    """Build ``Memory.from_config`` dict rooted under ``LA_DATA_DIR/mem0``."""
    config.ensure_data_dirs()
    llm = resolve_mem0_llm_settings()
    embedder = resolve_mem0_embedder_settings()
    dims = int(embedder["embedding_dims"])
    qdrant_path = str(config.mem0_qdrant_path())
    history_db = str(config.mem0_history_db())

    llm_cfg: dict[str, Any] = {
        "model": llm["model"],
        "api_key": llm.get("api_key") or "not-needed",
    }
    if llm.get("base_url"):
        llm_cfg["openai_base_url"] = llm["base_url"]

    embed_cfg: dict[str, Any] = {
        "model": embedder["model"],
        "api_key": embedder.get("api_key") or "not-needed",
        "embedding_dims": dims,
    }
    if embedder.get("base_url"):
        embed_cfg["openai_base_url"] = embedder["base_url"]

    return {
        "llm": {"provider": "openai", "config": llm_cfg},
        "embedder": {"provider": "openai", "config": embed_cfg},
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": config.default_bank_id(),
                "path": qdrant_path,
                "embedding_model_dims": dims,
                "on_disk": True,
            },
        },
        "history_db_path": history_db,
    }


def _is_engine_indexed(fact: MemoryFact) -> bool:
    meta = fact.metadata or {}
    if meta.get("backend") in ("mem0", "hindsight"):
        return True
    if meta.get("mem0_id") or meta.get("external_id") or meta.get("hindsight_id"):
        return True
    extra = meta.get("mem0_ids") or meta.get("hindsight_ids") or []
    return isinstance(extra, list) and bool(extra)


def _local_only_facts() -> list[MemoryFact]:
    return [fact for fact in get_memory_store().all_facts() if not _is_engine_indexed(fact)]


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


def _parse_add_ids(result: Any) -> list[str]:
    if result is None:
        return []
    if isinstance(result, str):
        return [result]
    if isinstance(result, dict):
        results = result.get("results")
        if isinstance(results, list):
            ids: list[str] = []
            for item in results:
                if isinstance(item, dict) and item.get("id"):
                    ids.append(str(item["id"]))
                elif isinstance(item, str):
                    ids.append(item)
            if ids:
                return ids
        for key in ("memory_ids", "ids", "memory_id", "id"):
            value = result.get(key)
            if value:
                return [str(item) for item in value] if isinstance(value, list) else [str(value)]
    return []


def _iter_search_results(results: Any) -> list[Any]:
    if results is None:
        return []
    if isinstance(results, list):
        return results
    if isinstance(results, dict):
        items = results.get("results")
        if items is not None:
            return list(items)
    items = getattr(results, "results", None)
    if items is not None:
        return list(items)
    return []


def _resolve_store_fact(store: Any, *, memory_id: str, text: str) -> MemoryFact | None:
    if memory_id:
        fact = store.get(memory_id)
        if fact is not None:
            return fact
        fact = store.find_by_external_id(memory_id)
        if fact is not None:
            return fact
    return store.find_by_text(text)


def _merge_recall_hit(
    item: Any,
    *,
    index: int,
    store_fact: MemoryFact | None,
) -> dict[str, Any]:
    if isinstance(item, dict):
        memory_id = str(item.get("id") or item.get("memory_id") or "")
        text = str(item.get("memory") or item.get("text") or item.get("content") or "")
        raw_score = item.get("score")
    else:
        memory_id = str(getattr(item, "id", None) or getattr(item, "memory_id", None) or "")
        text = str(
            getattr(item, "memory", None)
            or getattr(item, "text", None)
            or getattr(item, "content", None)
            or item
        )
        raw_score = getattr(item, "score", None)

    try:
        score = float(raw_score) if raw_score is not None else max(0.05, 1.0 - index * 0.04)
    except (TypeError, ValueError):
        score = max(0.05, 1.0 - index * 0.04)

    if store_fact is not None:
        meta = dict(store_fact.metadata or {})
        meta.setdefault("backend", "mem0")
        effective_at = memory_effective_time(metadata=meta, created_at=store_fact.created_at)
        return {
            "id": store_fact.id,
            "text": store_fact.text or text,
            "score": score,
            "source_file": store_fact.source_file,
            "section_heading": store_fact.section_heading,
            "created_at": effective_at,
            "metadata": meta,
            "source": "mem0",
        }

    return {
        "id": memory_id or f"mem0-{index}",
        "text": text,
        "score": score,
        "source_file": "",
        "section_heading": "",
        "created_at": "",
        "metadata": {"backend": "mem0"},
        "source": "mem0",
    }


def _save_registry_fact(
    *,
    fact_id: str,
    content: str,
    enriched: Any,
    metadata: dict[str, Any],
) -> MemoryFact | None:
    store = get_memory_store()
    meta = dict(metadata)
    meta.update(enriched.to_metadata())
    meta["backend"] = "mem0"
    meta["mem0_id"] = fact_id
    meta["external_id"] = fact_id

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


def _is_mem0_retain_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    markers = (
        "connection",
        "timeout",
        "not found",
        "unavailable",
        "internal server error",
        "embedding",
        "api",
        "client error",
        "failed",
    )
    return any(marker in text for marker in markers)


class Mem0Backend:
    """Self-hosted Mem0 Memory() with JSON enrichment registry dual-write."""

    def __init__(self, memory: Any | None = None) -> None:
        self._user_id = config.default_bank_id()
        self._llm_settings = resolve_mem0_llm_settings()
        self._embedder_settings = resolve_mem0_embedder_settings()
        if memory is not None:
            self._memory = memory
        else:
            from localagent.memory.backend import ensure_mem0_telemetry_disabled

            ensure_mem0_telemetry_disabled()
            from mem0 import Memory

            ensure_mem0_telemetry_disabled()
            self._memory = Memory.from_config(build_mem0_config())
        logger.info(
            "Mem0 backend ready (user_id=%s, embedder=%s/%s, infer=%s)",
            self._user_id,
            self._embedder_settings.get("source_provider"),
            self._embedder_settings.get("model"),
            config.MEM0_INFER,
        )

    def backend_name(self) -> str:
        return "mem0"

    def close(self) -> None:
        """Release Qdrant / SQLite before interpreter shutdown.

        QdrantClient.__del__ imports portalocker during close; if that runs after
        ``sys.meta_path`` is torn down, Python prints a noisy ignored ImportError.
        """
        memory = getattr(self, "_memory", None)
        if memory is None:
            return
        vector_store = getattr(memory, "vector_store", None)
        client = getattr(vector_store, "client", None)
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        close_fn = getattr(memory, "close", None)
        if callable(close_fn):
            try:
                close_fn()
            except Exception:
                pass
        self._memory = None

    def _infer(self) -> bool:
        return bool(config.MEM0_INFER)

    def _json_fallback_retain(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None,
        reason: str,
    ) -> str:
        from localagent.memory.backends.json_backend import JsonMemoryBackend

        meta = dict(metadata or {})
        meta["mem0_retain_failed"] = reason[:240]
        logger.warning("Mem0 retain failed, saved to JSON store: %s", reason[:120])
        return JsonMemoryBackend().retain(content, metadata=meta)

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
        # Mem0 metadata should be JSON-serializable scalars.
        string_meta = {
            k: (v if isinstance(v, (str, int, float, bool)) else str(v))
            for k, v in retain_meta.items()
            if v is not None and k not in ("occurred_at", "recorded_at", "indexed_at", "created_at")
        }

        try:
            result = self._memory.add(
                content,
                user_id=self._user_id,
                metadata=string_meta or None,
                infer=self._infer(),
            )
        except Exception as exc:
            if config.MEM0_RETAIN_JSON_FALLBACK and _is_mem0_retain_error(exc):
                return self._json_fallback_retain(content, metadata=meta, reason=str(exc))
            raise

        memory_ids = _parse_add_ids(result)
        primary_id = memory_ids[0] if memory_ids else str(uuid.uuid4())
        if len(memory_ids) > 1:
            retain_meta["mem0_ids"] = memory_ids

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
        from localagent.memory.backends.json_backend import JsonMemoryBackend
        from localagent.memory.scoped_recall import rerank_hits_temporally, scoped_recall

        prefetch = max(max_results * 3, 20)
        local_only = _local_only_facts()

        engine_hits: list[dict[str, Any]] = []
        try:
            results = self._memory.search(
                query,
                filters={"user_id": self._user_id},
                top_k=prefetch,
                threshold=0.0,
            )
            store = get_memory_store()
            for index, item in enumerate(_iter_search_results(results)):
                if isinstance(item, dict):
                    memory_id = str(item.get("id") or "")
                    text = str(item.get("memory") or item.get("text") or "")
                else:
                    memory_id = str(getattr(item, "id", "") or "")
                    text = str(getattr(item, "memory", None) or getattr(item, "text", "") or "")
                store_fact = _resolve_store_fact(store, memory_id=memory_id, text=text)
                engine_hits.append(_merge_recall_hit(item, index=index, store_fact=store_fact))
        except Exception as exc:
            logger.warning("Mem0 recall failed (%s), falling back to local registry", exc)
            return JsonMemoryBackend().recall(query, max_results=max_results)

        local_hits = (
            scoped_recall(query, max_results=prefetch, facts=local_only) if local_only else []
        )
        merged = _dedupe_recall_hits(engine_hits + local_hits)
        if not merged:
            return JsonMemoryBackend().recall(query, max_results=max_results)

        return rerank_hits_temporally(query, merged, max_results=max_results)

    def reflect(self, query: str) -> str | None:
        """Simulate Hindsight reflect: search + LA LLM synthesis."""
        hits = self.recall(query, max_results=8)
        if not hits:
            return None
        evidence = "\n".join(
            f"- {hit.get('text', '').strip()}" for hit in hits if hit.get("text")
        )
        if not evidence.strip():
            return None
        prompt = (
            "你是 LocalAgent 的记忆推理模块。根据下列已召回的长期记忆，"
            f"回答用户问题。只依据记忆内容归纳，不要编造。\n\n"
            f"问题：{query}\n\n记忆：\n{evidence}\n\n请用简洁中文回答："
        )
        try:
            from localagent.models.router import ChatMessage, get_model_router

            router = get_model_router()
            answer = router.chat(
                [ChatMessage(role="user", content=prompt)],
                temperature=0.2,
                usage_command="reflect",
            )
            text = (answer or "").strip()
            return text or None
        except Exception as exc:
            logger.warning("Mem0 reflect LLM failed: %s", exc)
            return None

    def delete(self, fact_id: str) -> bool:
        store = get_memory_store()
        fact = store.get(fact_id)
        if fact is None:
            return False

        meta = fact.metadata or {}
        external_id = str(
            meta.get("mem0_id") or meta.get("external_id") or meta.get("hindsight_id") or fact.id
        )
        try:
            self._memory.delete(external_id)
        except Exception as exc:
            logger.warning("Mem0 delete failed for %s: %s", external_id, exc)

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
            self._memory.delete_all(user_id=self._user_id)
        except Exception as exc:
            logger.warning("Mem0 delete_all failed: %s", exc)
            try:
                self._memory.reset()
            except Exception as reset_exc:
                logger.warning("Mem0 reset failed: %s", reset_exc)

        store = get_memory_store()
        store.clear()
        store.save()
        return count

    def count(self) -> int:
        try:
            response = self._memory.get_all(filters={"user_id": self._user_id}, top_k=1000)
            items = _iter_search_results(response)
            return len(items)
        except Exception:
            return get_memory_store().count()

    def reindex_from_registry(self) -> int:
        """Clear Mem0 vectors and re-add every JSON registry fact (infer=False)."""
        facts = list(get_memory_store().all_facts())
        try:
            self._memory.delete_all(user_id=self._user_id)
        except Exception:
            try:
                self._memory.reset()
            except Exception as exc:
                logger.warning("Mem0 clear before reindex failed: %s", exc)

        restored = 0
        for fact in facts:
            text = (fact.text or "").strip()
            if not text:
                continue
            meta = dict(fact.metadata or {})
            meta.setdefault("source_file", fact.source_file)
            meta.setdefault("section_heading", fact.section_heading)
            try:
                result = self._memory.add(
                    text,
                    user_id=self._user_id,
                    metadata={
                        k: (v if isinstance(v, (str, int, float, bool)) else str(v))
                        for k, v in meta.items()
                        if v is not None
                    }
                    or None,
                    infer=False,
                )
                ids = _parse_add_ids(result)
                if ids:
                    meta["backend"] = "mem0"
                    meta["mem0_id"] = ids[0]
                    meta["external_id"] = ids[0]
                    fact.metadata = meta
                    restored += 1
            except Exception as exc:
                logger.warning("Reindex retain failed for %s: %s", fact.id, exc)
        get_memory_store().save()
        return restored
