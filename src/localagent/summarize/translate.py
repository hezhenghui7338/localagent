"""Deep-translate integration for summarize (optional ``[translate]`` extra)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from localagent import config

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_MARKER_LINE_RE = re.compile(r"^#{1,6}\s*\[(?:§|p\.)")


@dataclass(frozen=True)
class TranslateConfig:
    enabled: bool
    source: str = "auto"
    target: str = "zh"
    provider: str = "google"

    @property
    def cache_key(self) -> dict[str, str | int]:
        return {
            "translate_enabled": int(self.enabled),
            "translate_target": self.target,
            "translate_source": self.source,
        }


class TranslateDependencyError(ImportError):
    """Raised when ``--deep-translate`` is used without the optional extra."""


def resolve_translate_config(
    *,
    deep_translate: bool | None = None,
    translate_to: str | None = None,
    translate_from: str | None = None,
) -> TranslateConfig:
    if deep_translate is None:
        enabled = config.SUMMARIZE_DEEP_TRANSLATE
    else:
        enabled = bool(deep_translate)
    target = (translate_to or config.SUMMARIZE_TRANSLATE_TARGET or "zh").strip() or "zh"
    source = (translate_from or config.SUMMARIZE_TRANSLATE_SOURCE or "auto").strip() or "auto"
    return TranslateConfig(enabled=enabled, source=source, target=target)


def is_mostly_chinese(text: str, *, threshold: float = 0.15) -> bool:
    sample = (text or "")[:20000]
    if not sample.strip():
        return True
    cjk = len(_CJK_RE.findall(sample))
    return (cjk / len(sample)) >= threshold


def needs_translation(text: str, cfg: TranslateConfig | None) -> bool:
    if cfg is None or not cfg.enabled:
        return False
    target = cfg.target.lower()
    if target in {"zh", "zh-cn", "chinese", "zh-tw"} and is_mostly_chinese(text):
        return False
    return True


def translate_config_dict(cfg: TranslateConfig | None) -> dict[str, str | int]:
    if cfg is None or not cfg.enabled:
        return {
            "translate_enabled": 0,
            "translate_target": "",
            "translate_source": "",
        }
    return cfg.cache_key


def _translator_for(cfg: TranslateConfig) -> Any:
    try:
        from deep_translator import GoogleTranslator
    except ImportError as exc:
        raise TranslateDependencyError(
            "deep-translator 未安装。请运行: pip install 'la-localagent[translate]'"
        ) from exc
    if cfg.provider != "google":
        raise ValueError(f"不支持的翻译后端: {cfg.provider}")
    return GoogleTranslator(source=cfg.source, target=cfg.target)


def _split_chunks(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        if end < len(text):
            split_at = text.rfind("\n\n", start, end)
            if split_at <= start:
                split_at = text.rfind("\n", start, end)
            if split_at <= start:
                split_at = text.rfind(" ", start, end)
            if split_at > start:
                end = split_at
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        start = max(end, start + 1)
    return chunks


def _translate_plain(text: str, cfg: TranslateConfig) -> str:
    stripped = (text or "").strip()
    if not stripped:
        return text
    translator = _translator_for(cfg)
    max_chars = max(500, int(config.SUMMARIZE_TRANSLATE_CHUNK_CHARS))
    chunks = _split_chunks(stripped, max_chars)
    if not chunks:
        return text
    if len(chunks) == 1:
        return str(translator.translate(chunks[0]))
    translated = translator.translate_batch(chunks)
    return "\n\n".join(str(part) for part in translated)


def _split_marker_blocks(text: str) -> list[tuple[str, str]]:
    """Return (kind, content) pairs: marker lines vs translatable body."""
    lines = (text or "").splitlines()
    blocks: list[tuple[str, str]] = []
    marker: str | None = None
    body_lines: list[str] = []

    def flush_body() -> None:
        nonlocal body_lines
        if body_lines:
            blocks.append(("body", "\n".join(body_lines)))
            body_lines = []

    for line in lines:
        if _MARKER_LINE_RE.match(line):
            flush_body()
            blocks.append(("marker", line))
            marker = line
        else:
            body_lines.append(line)
    flush_body()
    if not blocks and text:
        blocks.append(("body", text))
    return blocks


def translate_preserving_markers(text: str, cfg: TranslateConfig) -> tuple[str, list[str]]:
    """Translate body text while keeping ``## [§…]`` / ``## [p.N]`` marker lines intact."""
    warnings: list[str] = []
    blocks = _split_marker_blocks(text)
    out: list[str] = []
    for kind, content in blocks:
        if kind == "marker":
            out.append(content)
            continue
        if not content.strip():
            continue
        try:
            out.append(_translate_plain(content, cfg))
        except TranslateDependencyError:
            raise
        except Exception as exc:
            warnings.append(f"翻译失败，已使用原文: {exc}")
            out.append(content)
    if not out:
        return text, warnings
    return "\n\n".join(out), warnings


def apply_translate_for_summarize(
    text: str,
    cfg: TranslateConfig | None,
) -> tuple[str, list[str], bool]:
    """Return (text_for_summarize, warnings, was_translated)."""
    if not needs_translation(text, cfg):
        return text, [], False
    assert cfg is not None
    translated, warnings = translate_preserving_markers(text, cfg)
    return translated, warnings, True
