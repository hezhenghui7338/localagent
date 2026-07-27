"""Lightweight text encoding detection for .txt / .md loaders."""

from __future__ import annotations

import re

Confidence = str  # high | medium | low

_BOM_ENCODINGS: tuple[tuple[bytes, str, Confidence], ...] = (
    (b"\xef\xbb\xbf", "utf-8-sig", "high"),
    (b"\xff\xfe", "utf-16-le", "high"),
    (b"\xfe\xff", "utf-16-be", "high"),
)

_LEGACY_CJK_ENCODINGS: tuple[str, ...] = ("gb18030", "gbk", "big5")

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")


def _score_text(text: str) -> tuple[int, int, int]:
    """Return (cjk_count, replacement_count, printable_ratio_scaled)."""
    if not text:
        return 0, 0, 0
    sample = text[:20000]
    cjk = len(_CJK_RE.findall(sample))
    replacements = sample.count("\ufffd")
    printable = sum(1 for ch in sample if ch.isprintable() or ch in "\n\r\t")
    ratio_scaled = (printable * 1000) // max(len(sample), 1)
    return cjk, replacements, ratio_scaled


def _try_decode(raw: bytes, encoding: str) -> str | None:
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        return None


def detect_text_encoding(raw: bytes) -> tuple[str, Confidence]:
    """Return (encoding_name, confidence)."""
    if not raw:
        return "utf-8", "high"

    for bom, encoding, confidence in _BOM_ENCODINGS:
        if raw.startswith(bom):
            return encoding, confidence

    candidates: list[tuple[str, Confidence, int, int, int]] = []

    utf8_text = _try_decode(raw, "utf-8")
    if utf8_text is not None:
        cjk, repl, ratio = _score_text(utf8_text)
        candidates.append(("utf-8", "high", cjk, repl, ratio))

    for encoding in _LEGACY_CJK_ENCODINGS:
        text = _try_decode(raw, encoding)
        if text is None:
            continue
        cjk, repl, ratio = _score_text(text)
        conf: Confidence = "high" if encoding == "gb18030" else "medium"
        candidates.append((encoding, conf, cjk, repl, ratio))

    if not candidates:
        return "utf-8", "low"

    _enc, confidence, _cjk, _repl, _ratio = max(
        candidates,
        key=lambda item: (-item[3], item[2], item[4]),
    )
    return _enc, confidence


def decode_text_bytes(raw: bytes) -> tuple[str, str, Confidence]:
    """Decode bytes to text with detected encoding."""
    encoding, confidence = detect_text_encoding(raw)
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
        return text, "utf-8", "low"
    return text, encoding, confidence


def encoding_quality_warning(text: str, *, confidence: str) -> str | None:
    """Return a user-facing warning when decoded text looks corrupted."""
    if not text:
        return None
    sample = text[:20000]
    repl = sample.count("\ufffd")
    if confidence == "low" or (len(sample) >= 200 and repl / len(sample) > 0.05):
        return "文本编码可能不正确，建议确认原文件为 UTF-8 或 GBK"
    return None
