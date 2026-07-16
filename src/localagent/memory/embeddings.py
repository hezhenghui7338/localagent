"""Shared OpenAI-compatible embedding client for Warm/Cold semantic recall."""

from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_HASH_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _is_hash_embedder(settings: dict[str, Any]) -> bool:
    provider = str(settings.get("provider") or settings.get("source_provider") or "").lower()
    base_url = str(settings.get("base_url") or "").lower()
    model = str(settings.get("model") or "").lower()
    return (
        provider in {"hash", "local_hash", "deterministic"}
        or base_url.startswith("hash://")
        or model in {"hash", "local_hash"}
    )


def hash_embed_text(text: str, *, dims: int = 64) -> list[float]:
    """Deterministic bag-of-tokens embedding (offline / e2e; no network)."""
    dims = max(8, int(dims or 64))
    vec = [0.0] * dims
    tokens = _HASH_TOKEN_RE.findall((text or "").lower())
    if not tokens:
        # Empty text still needs a unit vector for cosine math.
        vec[0] = 1.0
        return vec
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % dims
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed_texts(texts: list[str], *, settings: dict[str, Any] | None = None) -> list[list[float]]:
    """Embed texts via the shared Mem0 embedder settings (OpenAI-compatible API)."""
    if not texts:
        return []
    if settings is None:
        from localagent.memory.backends.mem0_backend import resolve_mem0_embedder_settings

        settings = resolve_mem0_embedder_settings()

    if _is_hash_embedder(settings):
        dims = int(settings.get("embedding_dims") or 64)
        return [hash_embed_text(text, dims=dims) for text in texts]

    model = str(settings.get("model") or "")
    base_url = str(settings.get("base_url") or "").rstrip("/")
    api_key = str(settings.get("api_key") or "not-needed")
    if not model or not base_url:
        raise RuntimeError("embedder settings incomplete (model/base_url)")

    url = f"{base_url}/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"model": model, "input": texts}
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    items = data.get("data") or []
    # OpenAI returns objects with index; sort to preserve order.
    ordered = sorted(items, key=lambda item: int(item.get("index", 0)))
    vectors = [list(map(float, item.get("embedding") or [])) for item in ordered]
    if len(vectors) != len(texts):
        raise RuntimeError(f"embedder returned {len(vectors)} vectors for {len(texts)} texts")
    return vectors


def embed_query(query: str, *, settings: dict[str, Any] | None = None) -> list[float]:
    vectors = embed_texts([query], settings=settings)
    return vectors[0] if vectors else []
