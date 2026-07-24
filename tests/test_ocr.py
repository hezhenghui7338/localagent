"""Tests for local OCR integration (mocked RapidOCR; no optional deps required)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from localagent import config
from localagent.cli import main
from localagent.i18n import reset_lang_cache
from localagent.ingest.loader import explain_load_failure, load_file
from localagent.ingest.ocr import OcrDocumentResult, OcrPageResult, ocr_install_hint, ocr_metadata_from_result
from localagent.ocr_cmd import run_ocr
from localagent.summarize.document import SummarizeError, summarize_path


@pytest.fixture(autouse=True)
def _force_zh_ui_lang(monkeypatch):
    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    yield
    reset_lang_cache()


def _empty_pdf(path: Path) -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)


def _fake_ocr_pdf(_path: Path, **_kwargs) -> OcrDocumentResult:
    return OcrDocumentResult(
        text="## [p.1]\n扫描页一\n\n## [p.2]\n扫描页二",
        pages=[
            OcrPageResult(page_num=1, text="扫描页一", avg_confidence=0.95, low_confidence=False),
            OcrPageResult(page_num=2, text="扫描页二", avg_confidence=0.88, low_confidence=False),
        ],
        avg_confidence=0.915,
        warnings=[],
    )


def _fake_ocr_image(_path: Path, **_kwargs) -> OcrDocumentResult:
    return OcrDocumentResult(
        text="## [p.1]\n截图文字",
        pages=[OcrPageResult(page_num=1, text="截图文字", avg_confidence=0.99, low_confidence=False)],
        avg_confidence=0.99,
        warnings=[],
    )


def test_ocr_install_hint():
    assert "la-localagent[ocr]" in ocr_install_hint()
    assert "LA_OCR_ENABLED=1" in ocr_install_hint()


def test_explain_load_failure_scanned_pdf_without_ocr(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", False)
    pdf = tmp_path / "scan.pdf"
    _empty_pdf(pdf)
    message = explain_load_failure(pdf)
    assert "扫描版 PDF" in message
    assert "LA_OCR_ENABLED=1" in message


def test_load_scanned_pdf_with_mock_ocr(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    pdf = tmp_path / "scan.pdf"
    _empty_pdf(pdf)

    monkeypatch.setattr("localagent.ingest.ocr.ocr_pdf", _fake_ocr_pdf)

    doc = load_file(pdf)
    assert doc is not None
    assert "扫描页一" in doc.text
    assert doc.metadata.get("ocr_used") is True
    assert doc.metadata.get("ocr_pages") == 2
    assert doc.metadata.get("page_count") == 2


def test_load_image_with_mock_ocr(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    monkeypatch.setattr(config, "VL_ENABLED", False)
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    monkeypatch.setattr("localagent.ingest.ocr.ocr_image", _fake_ocr_image)

    doc = load_file(image)
    assert doc is not None
    assert "截图文字" in doc.text
    assert doc.metadata.get("ocr_used") is True


def test_load_image_without_ocr_or_vl_returns_none(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", False)
    monkeypatch.setattr(config, "VL_ENABLED", False)
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    assert load_file(image) is None


def test_ocr_metadata_from_result():
    result = _fake_ocr_pdf(Path("x.pdf"))
    meta = ocr_metadata_from_result(result)
    assert meta["ocr_used"] is True
    assert meta["ocr_pages"] == 2
    assert meta["ocr_confidence_avg"] == 0.915


def test_summarize_scanned_pdf_requires_ocr_hint(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", False)
    pdf = tmp_path / "scan.pdf"
    _empty_pdf(pdf)
    with pytest.raises(SummarizeError) as exc:
        summarize_path(pdf, keep=False, use_llm=False)
    assert "LA_OCR_ENABLED=1" in str(exc.value)


def test_summarize_scanned_pdf_with_mock_ocr(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    pdf = tmp_path / "scan.pdf"
    _empty_pdf(pdf)
    monkeypatch.setattr("localagent.ingest.ocr.ocr_pdf", _fake_ocr_pdf)

    result = summarize_path(pdf, keep=False, use_llm=False)
    assert result.ocr_used is True
    assert result.ocr_pages == 2
    assert result.ocr_confidence_avg == pytest.approx(0.915)
    assert "## 总结" in result.markdown


def test_summarize_rejects_image(tmp_path: Path):
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    with pytest.raises(SummarizeError) as exc:
        summarize_path(image, keep=False, use_llm=False)
    assert "la ocr" in str(exc.value)


def test_run_ocr_image_mock(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    image = tmp_path / "menu.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr("localagent.ocr_cmd.ocr_image", _fake_ocr_image)

    result = run_ocr(image)
    assert result.text == "截图文字"
    assert result.line_count == 1
    assert result.avg_confidence == pytest.approx(0.99)
    assert "## 总结" not in result.text


def test_cmd_ocr_prints_plain_text(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    image = tmp_path / "menu.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr("localagent.ocr_cmd.ocr_image", _fake_ocr_image)

    rc = main(["ocr", str(image)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "截图文字" in captured.out
    assert "## 总结" not in captured.out
    assert "[ocr]" in captured.out


def test_cmd_ocr_json_output(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(config, "OCR_ENABLED", True)
    image = tmp_path / "menu.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr("localagent.ocr_cmd.ocr_image", _fake_ocr_image)

    rc = main(["ocr", str(image), "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["text"] == "截图文字"
    assert payload["avg_confidence"] == pytest.approx(0.99)
