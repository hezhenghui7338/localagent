"""Local OCR via RapidOCR (PP-OCRv6) for scanned PDFs and images."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from localagent import config

logger = logging.getLogger(__name__)

OcrProgressCallback = Callable[[int, int, str], None]

_ENGINE = None
_OCR_EXTRA = "la-localagent[ocr]"


@dataclass
class OcrPageResult:
    page_num: int
    text: str
    avg_confidence: float
    low_confidence: bool


@dataclass
class OcrDocumentResult:
    text: str
    pages: list[OcrPageResult] = field(default_factory=list)
    avg_confidence: float = 0.0
    engine: str = "rapidocr/pp-ocrv6"
    warnings: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)


def ocr_install_hint() -> str:
    return (
        f"启用本地 OCR：pip install '{_OCR_EXTRA}' 并在 .env 设置 LA_OCR_ENABLED=1"
    )


def ocr_available() -> bool:
    """Return True when OCR is enabled and optional deps import cleanly."""
    if not config.OCR_ENABLED:
        return False
    try:
        _ensure_engine()
    except RuntimeError:
        return False
    return True


def _tier_model_type():
    from rapidocr import ModelType

    tier = (config.OCR_TIER or "medium").strip().lower()
    mapping = {
        "tiny": ModelType.TINY,
        "small": ModelType.SMALL,
        "medium": ModelType.MEDIUM,
    }
    if tier not in mapping:
        raise RuntimeError(f"invalid LA_OCR_TIER {tier!r}; expected tiny|small|medium")
    return mapping[tier]


def _ensure_engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    if not config.OCR_ENABLED:
        raise RuntimeError(f"OCR disabled (LA_OCR_ENABLED=0). {ocr_install_hint()}")
    try:
        from rapidocr import OCRVersion, RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            f"OCR dependencies missing ({exc}). {ocr_install_hint()}"
        ) from exc

    model_type = _tier_model_type()
    tier = (config.OCR_TIER or "medium").strip().lower()
    _ENGINE = RapidOCR(
        params={
            "Det.model_type": model_type,
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Det.lang_type": config.OCR_LANG,
            "Rec.model_type": model_type,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Rec.lang_type": config.OCR_LANG,
        }
    )
    logger.info("OCR engine ready (PP-OCRv6 %s, lang=%s)", tier, config.OCR_LANG)
    return _ENGINE


def _format_page_section(page_num: int, text: str) -> str:
    body = text.strip()
    if not body:
        return ""
    return f"## [p.{page_num}]\n{body}"


def _lines_from_ocr_output(result) -> tuple[list[str], list[float]]:
    txts = list(getattr(result, "txts", None) or ())
    scores = list(getattr(result, "scores", None) or ())
    if not txts:
        return [], []
    if len(scores) < len(txts):
        scores.extend([0.0] * (len(txts) - len(scores)))
    return [str(t).strip() for t in txts if str(t).strip()], [float(s) for s in scores[: len(txts)]]


def _run_image_ocr(engine, image) -> tuple[str, float]:
    output = engine(image, use_det=True, use_cls=True, use_rec=True)
    if output is None:
        return "", 0.0
    lines, scores = _lines_from_ocr_output(output)
    if not lines:
        return "", 0.0
    text = "\n".join(lines)
    avg = sum(scores) / len(scores) if scores else 0.0
    return text, avg


def _default_progress(current: int, total: int, message: str) -> None:
    if total <= 1:
        return
    print(f"[ocr] {message}", file=sys.stderr, flush=True)


def ocr_image(path: Path, *, on_progress: OcrProgressCallback | None = None) -> OcrDocumentResult:
    """OCR a single image file."""
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"image not found: {path}")

    engine = _ensure_engine()
    progress = on_progress or _default_progress
    progress(1, 1, f"识别图片 {path.name}")

    text, avg = _run_image_ocr(engine, str(path.resolve()))
    warnings: list[str] = []
    low = avg < config.OCR_MIN_CONF and bool(text)
    if low:
        warnings.append(
            f"OCR 置信度偏低 ({avg:.2f})，建议人工核对原文"
        )
    page = OcrPageResult(page_num=1, text=text, avg_confidence=avg, low_confidence=low)
    sections = [_format_page_section(1, text)] if text else []
    return OcrDocumentResult(
        text="\n\n".join(sections),
        pages=[page] if text else [],
        avg_confidence=avg,
        warnings=warnings,
    )


def ocr_pdf(
    path: Path,
    *,
    dpi: int | None = None,
    on_progress: OcrProgressCallback | None = None,
) -> OcrDocumentResult:
    """Render each PDF page and OCR it."""
    path = Path(path)
    if not path.is_file():
        raise RuntimeError(f"PDF not found: {path}")

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            f"PyMuPDF missing ({exc}). {ocr_install_hint()}"
        ) from exc

    render_dpi = dpi if dpi is not None else config.OCR_PDF_DPI
    engine = _ensure_engine()
    progress = on_progress or _default_progress

    doc = fitz.open(str(path))
    try:
        page_count = doc.page_count
        pages: list[OcrPageResult] = []
        sections: list[str] = []
        confidences: list[float] = []
        warnings: list[str] = []

        for index in range(page_count):
            page_num = index + 1
            progress(page_num, page_count, f"扫描版 PDF · 正在识别 {page_num}/{page_count} 页…")
            page = doc.load_page(index)
            pix = page.get_pixmap(dpi=render_dpi, alpha=False)
            samples = memoryview(pix.samples)
            image = np.frombuffer(samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                image = image[:, :, :3]

            text, avg = _run_image_ocr(engine, image)
            confidences.append(avg)
            low = avg < config.OCR_MIN_CONF and bool(text)
            if low:
                warnings.append(
                    f"p.{page_num} OCR 置信度偏低 ({avg:.2f})，建议人工核对原文"
                )
            pages.append(
                OcrPageResult(
                    page_num=page_num,
                    text=text,
                    avg_confidence=avg,
                    low_confidence=low,
                )
            )
            section = _format_page_section(page_num, text)
            if section:
                sections.append(section)
    finally:
        doc.close()

    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return OcrDocumentResult(
        text="\n\n".join(sections),
        pages=pages,
        avg_confidence=avg_conf,
        warnings=warnings,
    )


def ocr_metadata_from_result(result: OcrDocumentResult) -> dict:
    """Map OCR output into LoadedDoc.metadata keys."""
    return {
        "ocr_used": True,
        "ocr_engine": result.engine,
        "ocr_confidence_avg": round(result.avg_confidence, 4),
        "ocr_pages": result.page_count,
        "ocr_warnings": list(result.warnings),
        "page_count": result.page_count,
        "pages_with_text": sum(1 for page in result.pages if page.text.strip()),
    }
