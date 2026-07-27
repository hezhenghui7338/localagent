"""Tests for MOBI ingest and summarize support."""

from __future__ import annotations

from pathlib import Path

import pytest

from localagent.i18n import reset_lang_cache
from localagent.ingest.ebook import explain_mobi_load_failure, html_to_chapter_text, load_mobi
from localagent.ingest.loader import explain_load_failure, load_file
from localagent.summarize.document import SummarizeError, summarize_path


@pytest.fixture(autouse=True)
def _force_zh_ui_lang(monkeypatch):
    monkeypatch.setenv("LA_LANG", "zh")
    reset_lang_cache()
    yield
    reset_lang_cache()


def test_html_to_chapter_text_injects_section_markers():
    html = """
    <html><body>
    <h1>第一回 甄士隐梦幻识通灵</h1>
    <p>此开卷第一回也。</p>
    <h2>第二回</h2>
    <p>却说封氏闻得此信，<b>哭个死去活来</b>。</p>
    </body></html>
    """
    text = html_to_chapter_text(html)
    assert "## [§第一回 甄士隐梦幻识通灵]" in text
    assert "此开卷第一回也。" in text
    assert "## [§第二回]" in text
    assert "哭个死去活来" in text
    assert "<" not in text


def test_load_file_mobi_via_mock_extract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mobi_path = tmp_path / "book.mobi"
    mobi_path.write_bytes(b"fake-mobi")

    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    html_path = extract_dir / "extracted.html"
    html_path.write_text(
        "<html><body><h1>Chapter One</h1><p>Hello MOBI world.</p></body></html>",
        encoding="utf-8",
    )

    def fake_extract(path: str):
        return str(extract_dir), str(html_path)

    monkeypatch.setattr("mobi.extract", fake_extract)

    doc = load_file(mobi_path)
    assert doc is not None
    assert "## [§Chapter One]" in doc.text
    assert "Hello MOBI world." in doc.text
    assert doc.metadata.get("mobi_extract_type") == "html"
    assert doc.metadata.get("chapter_markers") == 1


def test_summarize_path_accepts_mobi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mobi_path = tmp_path / "novel.mobi"
    mobi_path.write_bytes(b"fake-mobi")

    extract_dir = tmp_path / "extract"
    extract_dir.mkdir()
    html_path = extract_dir / "out.html"
    html_path.write_text(
        "<html><body><h1>简介</h1><p>LocalAgent 速读测试正文。</p></body></html>",
        encoding="utf-8",
    )

    monkeypatch.setattr("mobi.extract", lambda _p: (str(extract_dir), str(html_path)))

    result = summarize_path(mobi_path, use_llm=False)
    assert "## 总结" in result.markdown
    assert "§" in result.markdown or "〔" in result.markdown


def test_summarize_path_rejects_unknown_suffix(tmp_path: Path):
    path = tmp_path / "book.azw3"
    path.write_bytes(b"x")
    with pytest.raises(SummarizeError, match="不支持的文件类型"):
        summarize_path(path, use_llm=False)


def test_empty_mobi_html_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mobi_path = tmp_path / "empty.mobi"
    mobi_path.write_bytes(b"fake")

    extract_dir = tmp_path / "extract"
    html_path = extract_dir / "blank.html"

    def fake_extract(_p):
        extract_dir.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<html><body></body></html>", encoding="utf-8")
        return str(extract_dir), str(html_path)

    monkeypatch.setattr("mobi.extract", fake_extract)

    assert load_file(mobi_path) is None
    hint = explain_load_failure(mobi_path)
    assert "MOBI" in hint or "正文为空" in hint


def test_explain_mobi_load_failure_on_extract_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mobi_path = tmp_path / "bad.mobi"
    mobi_path.write_bytes(b"bad")

    def boom(_path: str):
        raise RuntimeError("encrypted DRM content")

    monkeypatch.setattr("mobi.extract", boom)

    with pytest.raises(ValueError, match="DRM"):
        load_mobi(mobi_path)

    hint = explain_mobi_load_failure(mobi_path)
    assert "DRM" in hint or "加密" in hint
