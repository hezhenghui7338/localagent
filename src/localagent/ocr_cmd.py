"""Standalone OCR command: extract visible text without LLM summarize."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from localagent import config
from localagent.audit.security import is_sensitive_path, sensitive_path_reason
from localagent.config import IMAGE_SUFFIXES
from localagent.ingest.ocr import OcrDocumentResult, ocr_image, ocr_install_hint, ocr_pdf


class OcrCommandError(ValueError):
    """User-facing OCR failure."""


@dataclass
class OcrCommandResult:
    path: Path
    filename: str
    text: str
    line_count: int
    page_count: int
    avg_confidence: float
    engine: str
    warnings: list[str] = field(default_factory=list)
    kept: bool = False
    keep_target: Path | None = None

    def to_json(self) -> dict:
        return {
            "path": str(self.path),
            "filename": self.filename,
            "text": self.text,
            "line_count": self.line_count,
            "page_count": self.page_count,
            "avg_confidence": round(self.avg_confidence, 4),
            "engine": self.engine,
            "warnings": list(self.warnings),
            "kept": self.kept,
            "keep_target": str(self.keep_target) if self.keep_target else None,
        }


def _supported_suffix(path: Path) -> bool:
    suffix = path.suffix.lower()
    return suffix == ".pdf" or suffix in IMAGE_SUFFIXES


def _display_text(result: OcrDocumentResult, suffix: str) -> str:
    if suffix == ".pdf" or result.page_count > 1:
        return result.text.strip()
    if len(result.pages) == 1:
        return result.pages[0].text.strip()
    return result.text.strip()


def _line_count(text: str) -> int:
    lines = [line for line in text.splitlines() if line.strip()]
    return len(lines)


def run_ocr(path: str | Path, *, keep: bool = False) -> OcrCommandResult:
    source = Path(path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise OcrCommandError(f"文件不存在: {source}")
    if is_sensitive_path(source):
        raise OcrCommandError(sensitive_path_reason(source) or "敏感路径，拒绝读取")
    if not _supported_suffix(source):
        supported = ", ".join(sorted({".pdf", *IMAGE_SUFFIXES}))
        raise OcrCommandError(f"不支持的文件类型 {source.suffix!r}；支持: {supported}")

    if not config.OCR_ENABLED:
        raise OcrCommandError(f"OCR 未启用。{ocr_install_hint()}")

    suffix = source.suffix.lower()
    try:
        if suffix == ".pdf":
            ocr_result = ocr_pdf(source)
        else:
            ocr_result = ocr_image(source)
    except RuntimeError as exc:
        raise OcrCommandError(str(exc)) from exc

    text = _display_text(ocr_result, suffix)
    if not text:
        raise OcrCommandError(f"OCR 未识别到文字: {source}")

    result = OcrCommandResult(
        path=source,
        filename=source.name,
        text=text,
        line_count=_line_count(text),
        page_count=ocr_result.page_count,
        avg_confidence=ocr_result.avg_confidence,
        engine=ocr_result.engine,
        warnings=list(ocr_result.warnings),
    )

    if keep:
        from localagent.ingest.add_file import add_file

        target, _ingest = add_file(source)
        result.kept = True
        result.keep_target = target

    return result


def render_ocr_result(result: OcrCommandResult, *, as_json: bool = False) -> str:
    from localagent.i18n import t

    if as_json:
        return json.dumps(result.to_json(), ensure_ascii=False, indent=2)

    meta_bits = [
        t("ocr.meta_file", filename=result.filename),
        t("ocr.meta_conf", conf=f"{result.avg_confidence:.2f}"),
        t("ocr.meta_lines", n=result.line_count),
    ]
    if result.page_count > 1:
        meta_bits.append(t("ocr.meta_pages", n=result.page_count))
    parts = [t("ocr.meta_prefix", meta=" · ".join(meta_bits)), "---", result.text, "---"]
    if result.warnings:
        parts.extend(t("ocr.warning", warning=warning) for warning in result.warnings)
    if result.kept and result.keep_target is not None:
        parts.append(t("ocr.kept", target=result.keep_target))
    return "\n".join(parts)
