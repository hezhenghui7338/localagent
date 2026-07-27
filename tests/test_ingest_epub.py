"""Tests for EPUB ingest and summarize support."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from localagent.i18n import reset_lang_cache
from localagent.ingest.ebook import explain_epub_load_failure, load_epub
from localagent.ingest.loader import explain_load_failure, load_file
from localagent.summarize.document import SummarizeError, summarize_path


@pytest.fixture(autouse=True)
def _force_zh_ui_lang(monkeypatch):
    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    yield
    reset_lang_cache()


def _write_minimal_epub(
    path: Path,
    *,
    title: str = "第一章",
    body: str = "Hello EPUB world.",
    include_chapter: bool = True,
) -> None:
    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    opf_xml = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="BookId">
  <manifest>
    <item id="chapter1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chapter1"/>
  </spine>
</package>"""
    chapter_html = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <h1>{title}</h1>
    <p>{body}</p>
  </body>
</html>"""
    empty_chapter_html = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body></body></html>"""

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", opf_xml)
        if include_chapter:
            zf.writestr("OEBPS/chapter1.xhtml", chapter_html)
        else:
            zf.writestr("OEBPS/chapter1.xhtml", empty_chapter_html)


def test_load_file_epub_extracts_chapter_markers(tmp_path: Path):
    epub_path = tmp_path / "book.epub"
    _write_minimal_epub(epub_path)

    doc = load_file(epub_path)
    assert doc is not None
    assert "## [§第一章]" in doc.text
    assert "Hello EPUB world." in doc.text
    assert doc.metadata.get("ebook_format") == "epub"
    assert doc.metadata.get("chapter_markers") == 1


def test_load_epub_direct(tmp_path: Path):
    epub_path = tmp_path / "direct.epub"
    _write_minimal_epub(epub_path, title="简介", body="正文段落。")

    text, meta = load_epub(epub_path)
    assert "## [§简介]" in text
    assert "正文段落。" in text
    assert meta.get("ebook_format") == "epub"


def test_summarize_path_accepts_epub(tmp_path: Path):
    epub_path = tmp_path / "novel.epub"
    _write_minimal_epub(
        epub_path,
        title="简介",
        body="LocalAgent 速读测试正文。",
    )

    result = summarize_path(epub_path, use_llm=False)
    assert "## 总结" in result.markdown
    assert "§" in result.markdown or "〔" in result.markdown


def test_empty_epub_returns_none(tmp_path: Path):
    epub_path = tmp_path / "empty.epub"
    _write_minimal_epub(epub_path, include_chapter=False)

    assert load_file(epub_path) is None
    hint = explain_load_failure(epub_path)
    assert "EPUB" in hint or "正文为空" in hint


def test_explain_epub_load_failure_on_bad_zip(tmp_path: Path):
    epub_path = tmp_path / "bad.epub"
    epub_path.write_bytes(b"not-a-zip")

    hint = explain_epub_load_failure(epub_path)
    assert "EPUB" in hint or "损坏" in hint or "zip" in hint.lower()


def test_summarize_path_rejects_unknown_suffix(tmp_path: Path):
    path = tmp_path / "book.azw3"
    path.write_bytes(b"x")
    with pytest.raises(SummarizeError, match="不支持的文件类型"):
        summarize_path(path, use_llm=False)
