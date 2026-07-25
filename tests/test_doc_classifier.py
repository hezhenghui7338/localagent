"""Tests for document type classification."""

from __future__ import annotations

from localagent.ingest.doc_classifier import DocType, classify_document, extract_html_title


def test_classify_resume_by_filename():
    assert classify_document(filename="简历-张三.html", text="plain text") == DocType.RESUME
    assert classify_document(filename="John_CV.pdf", text="") == DocType.RESUME


def test_classify_resume_by_headings():
    text = "个人简介\n工作经历\n项目经验\n教育背景"
    assert classify_document(filename="doc.txt", text=text) == DocType.RESUME


def test_classify_resume_by_h1_and_heading():
    text = "<h1>张三</h1>\n<h2>工作经历</h2>\n<p>某公司</p>"
    assert classify_document(filename="page.html", text=text) == DocType.RESUME


def test_classify_notes():
    text = "# 笔记\n\n今日学习 Python。"
    assert classify_document(filename="daily.md", text=text) == DocType.NOTES
    assert classify_document(filename="log.txt", text="\n# journal\nentry") == DocType.NOTES


def test_classify_general():
    text = "这是一份普通的技术文档，没有简历或笔记特征。"
    assert classify_document(filename="readme.md", text=text) == DocType.GENERAL


def test_extract_html_title():
    html = "<html><head><title>  何征辉 · 简历  </title></head><body></body></html>"
    assert extract_html_title(html) == "何征辉 · 简历"
    assert extract_html_title("<html><body>no title</body></html>") == ""
