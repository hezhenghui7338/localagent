"""Ollama VL: image → text caption for Cold RAG ingest."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import httpx

from localagent import config

logger = logging.getLogger(__name__)

_CAPTION_PROMPT = (
    "Describe this image for a personal knowledge base. "
    "Include colors, objects, scene, and any visible text. "
    "Be concrete and searchable; keep it under 200 words."
)


def caption_image(path: Path) -> str:
    """Return a searchable text caption via local Ollama VL.

    Raises ``RuntimeError`` when VL is disabled or the model call fails.
    """
    if not config.VL_ENABLED:
        raise RuntimeError("VL captioning disabled (LA_VL_ENABLED=0)")

    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"image not found: {path}")

    raw = path.read_bytes()
    if not raw:
        raise RuntimeError(f"empty image file: {path.name}")

    b64 = base64.b64encode(raw).decode("ascii")
    model = (config.VL_MODEL or "").strip() or "qwen3-vl:4b"
    base_url = (config.OLLAMA_BASE_URL or "http://localhost:11434").rstrip("/")
    url = f"{base_url}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": _CAPTION_PROMPT,
                "images": [b64],
            }
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.1,
            "num_predict": config.VL_NUM_PREDICT,
        },
    }

    try:
        with httpx.Client(timeout=config.VL_TIMEOUT) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 404:
                raise RuntimeError(
                    f"ollama VL model '{model}' not found; run: ollama pull {model}"
                )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"ollama VL request failed: {exc}") from exc

    caption = (data.get("message") or {}).get("content") or ""
    caption = str(caption).strip()
    if not caption:
        raise RuntimeError(f"ollama VL returned empty caption for {path.name}")

    logger.info("VL caption for %s (%d chars) via %s", path.name, len(caption), model)
    return f"[Image: {path.name}]\n{caption}"
