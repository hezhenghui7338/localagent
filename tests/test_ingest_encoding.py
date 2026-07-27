"""Tests for text encoding detection in ingest loaders."""

from __future__ import annotations

from pathlib import Path

from localagent.ingest.encoding import (
    decode_text_bytes,
    detect_text_encoding,
    encoding_quality_warning,
)
from localagent.ingest.loader import load_file


def test_detect_utf8_chinese():
    raw = "LocalAgent 是本地助手。\n".encode("utf-8")
    encoding, confidence = detect_text_encoding(raw)
    assert encoding == "utf-8"
    assert confidence == "high"


def test_detect_gbk_chinese():
    raw = "售票处和小件寄存的窗口都被背后的木板堵个严实。".encode("gbk")
    encoding, confidence = detect_text_encoding(raw)
    assert encoding in {"gb18030", "gbk"}
    text, enc, conf = decode_text_bytes(raw)
    assert "售票处" in text
    assert enc in {"gb18030", "gbk"}
    assert conf in {"high", "medium"}


def test_detect_utf8_bom():
    raw = b"\xef\xbb\xbf" + "中文正文。".encode("utf-8")
    encoding, confidence = detect_text_encoding(raw)
    assert encoding == "utf-8-sig"
    assert confidence == "high"
    text, enc, _conf = decode_text_bytes(raw)
    assert enc == "utf-8-sig"
    assert text == "中文正文。"


def test_load_file_utf8_metadata(tmp_path: Path):
    path = tmp_path / "utf8.txt"
    path.write_text("你好，世界。\n", encoding="utf-8")
    doc = load_file(path)
    assert doc is not None
    assert "你好" in doc.text
    assert doc.metadata.get("text_encoding") == "utf-8"
    assert doc.metadata.get("encoding_confidence") == "high"
    assert doc.text.count("\ufffd") == 0


def test_load_file_gbk_metadata(tmp_path: Path):
    path = tmp_path / "legacy.txt"
    path.write_bytes("乌伊居然出现在这路线的终点。".encode("gbk"))
    doc = load_file(path)
    assert doc is not None
    assert "乌伊" in doc.text
    assert doc.metadata.get("text_encoding") in {"gb18030", "gbk"}
    assert doc.text.count("\ufffd") == 0


def test_encoding_quality_warning_on_low_confidence():
    assert encoding_quality_warning("abc", confidence="low") is not None


def test_encoding_quality_warning_clean_utf8():
    assert encoding_quality_warning("正常中文文本。" * 20, confidence="high") is None
