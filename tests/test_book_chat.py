"""Tests for full-book chat context and REPL scope."""

from __future__ import annotations

from pathlib import Path

import pytest

from localagent import config
from localagent.summarize.document import SummarizeResult
from localagent.summarize.repl import DocumentChatREPL
from localagent.summarize.segment_reader import (
    DocumentSegment,
    ReadingProgress,
    build_book_context,
    build_segments,
    format_book_context,
    resolve_book_context_budget,
)


def _progress_with_summaries(
    summaries: list[str],
    *,
    headings: list[str] | None = None,
) -> ReadingProgress:
    headings = headings or [f"段{i + 1}" for i in range(len(summaries))]
    segments = [
        DocumentSegment(
            index=i,
            heading=headings[i],
            text=f"body {i}",
            char_count=100,
            cite_range=f"§{headings[i]}",
        )
        for i in range(len(summaries))
    ]
    progress = ReadingProgress(
        segments=segments,
        segment_summaries=list(summaries),
    )
    progress.init_statuses()
    return progress


def test_build_book_context_within_budget():
    summaries = [
        "## 总结（最多三句话）\n第一句。\n\n## 结构化要点\n- **点**：细节 〔§A〕",
        "## 总结（最多三句话）\n第二句。\n\n## 结构化要点\n- **点**：更多 〔§B〕",
    ]
    progress = _progress_with_summaries(summaries)
    budget = resolve_book_context_budget("auto")
    block = build_book_context(progress, budget=budget, filename="t.md")
    assert "全书阅读进度" in block
    assert "2/2" in block
    assert len(block) <= budget + 400
    assert progress.book_context_done_count == 2


def test_build_book_context_hierarchical_when_many_segments(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "SUMMARIZE_BOOK_GROUP_MIN", 3)
    summaries = [
        f"## 总结（最多三句话）\n段{i}。\n\n## 结构化要点\n- **点**：细节 〔§{i}〕"
        for i in range(6)
    ]
    progress = _progress_with_summaries(summaries)
    budget = 800
    block = build_book_context(progress, budget=budget, filename="big.md")
    assert "分层压缩" in block or "段 1" in block
    assert "6/6" in block


def test_build_book_context_cache_invalidation():
    summaries = ["## 总结（最多三句话）\n一。\n\n## 结构化要点\n- **点**：a"]
    progress = _progress_with_summaries(summaries)
    first = build_book_context(progress, budget=2000, filename="t.md")
    second = build_book_context(progress, budget=2000, filename="t.md")
    assert first == second
    progress.segment_summaries.append("## 总结（最多三句话）\n二。")
    progress.segments.append(
        DocumentSegment(
            index=1,
            heading="段2",
            text="body",
            char_count=50,
            cite_range="§段2",
        )
    )
    progress.set_segment_status(1, "done")
    third = build_book_context(progress, budget=2000, filename="t.md")
    assert third != first
    assert "2/2" in third


def test_format_book_context_includes_rag_and_progress(tmp_path: Path):
    summaries = ["## 总结（最多三句话）\n内容。"]
    progress = _progress_with_summaries(summaries)
    result = SummarizeResult(
        markdown=summaries[0],
        path=tmp_path / "book.md",
        filename="book.md",
        char_count=1000,
        annotated_text="text",
        session_source_key="sum:book:abc",
        segment_mode=True,
        reading_progress=progress,
    )
    block = format_book_context(
        result,
        progress,
        retrieval_block="## 检索\n片段",
        provider="auto",
    )
    assert "全书对话" in block
    assert "检索" in block
    assert "1/1" in block


def test_document_chat_repl_book_scope_context(tmp_path: Path):
    summaries = [
        "## 总结（最多三句话）\n段一。",
        "## 总结（最多三句话）\n段二。",
    ]
    progress = _progress_with_summaries(summaries)
    result = SummarizeResult(
        markdown=summaries[0],
        path=tmp_path / "book.md",
        filename="book.md",
        char_count=1000,
        annotated_text="text",
        session_source_key="sum:book:abc",
        segment_mode=True,
        reading_progress=progress,
    )
    repl = DocumentChatREPL(
        result,
        chat_scope="book",
        no_prefetch=True,
    )
    ctx = repl._document_context("这本书的主线是什么？")
    assert "全书对话" in ctx
    assert repl._book_mode_active()
    assert not repl._segment_nav_enabled()


def test_build_segments_still_works():
    text = "# A\n\n" + "x" * 1200 + "\n\n# B\n\n" + "y" * 1200
    segments = build_segments(text, target_chars=800, segment_max=2000, filename="t.md")
    assert len(segments) >= 2


def test_enter_summarize_interactive_routes_to_book_when_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    summaries = ["## 总结\n一。", "## 总结\n二。"]
    progress = _progress_with_summaries(summaries)
    result = SummarizeResult(
        markdown=summaries[0],
        path=tmp_path / "book.md",
        filename="book.md",
        char_count=1000,
        annotated_text="text",
        segment_mode=True,
        reading_progress=progress,
    )
    calls: list[str] = []

    def fake_book(*args, **kwargs):
        calls.append("book")
        return 0

    def fake_browser(*args, **kwargs):
        calls.append("browser")
        return 0

    monkeypatch.setattr(
        "localagent.summarize.chat_bridge.run_book_chat",
        fake_book,
    )
    monkeypatch.setattr(
        "localagent.summarize.browser.run_segment_browser",
        fake_browser,
    )
    from localagent.summarize.repl import enter_summarize_interactive

    enter_summarize_interactive(result, no_ui=False, book_chat_entered=False)
    assert calls == ["book"]


def test_prefetch_on_complete_fires_when_all_done():
    from concurrent.futures import Future

    from localagent.summarize.document import SummarizeResult
    from localagent.summarize.segment_prefetch import SegmentPrefetchWorker

    summaries = ["sum0", "sum1"]
    progress = _progress_with_summaries(summaries)
    result = SummarizeResult(
        markdown="sum0",
        path=Path("/tmp/x.md"),
        filename="x.md",
        char_count=100,
        segment_mode=True,
        reading_progress=progress,
    )
    completed: list[bool] = []

    worker = SegmentPrefetchWorker(
        result,
        on_complete=lambda: completed.append(True),
    )
    fut: Future[str | None] = Future()
    fut.set_result("sum1")
    worker._finish_future(progress, 1, fut)
    assert completed == [True]
