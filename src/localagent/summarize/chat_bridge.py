"""Bridge segment browser into DocumentChatREPL deep chat."""

from __future__ import annotations

from localagent.summarize.document import SummarizeResult
from localagent.summarize.repl import DocumentChatREPL
from localagent.summarize.segment_reader import build_book_context
from localagent.summarize.sessions import mark_book_chat_entered


def run_segment_chat(
    result: SummarizeResult,
    segment_index: int,
    *,
    provider: str = "auto",
    summarize_session_id: str | None = None,
    conversation_session_id: str | None = None,
    deep_segment_only: bool = True,
) -> int:
    """Enter document chat scoped to one segment; returns REPL exit code."""
    progress = result.reading_progress
    if progress is None:
        return 1
    if not progress.summary_ready(segment_index):
        return 1

    progress.select_segment(segment_index, provider=provider)
    seg = progress.current
    summary = progress.current_summary() or result.markdown
    result.markdown = summary.strip() or result.markdown

    history = [
        {
            "role": "user",
            "content": (
                f"请总结文档第 {progress.current_index + 1}/{progress.total} 段"
                f"（{seg.heading}）：{result.filename}"
            ),
        },
        {"role": "assistant", "content": summary},
    ]

    return DocumentChatREPL(
        result,
        provider=provider,
        summarize_session_id=summarize_session_id,
        conversation_session_id=conversation_session_id,
        history=history,
        deep_segment_only=deep_segment_only,
        chat_scope="segment",
    ).run()


def run_book_chat(
    result: SummarizeResult,
    *,
    provider: str = "auto",
    summarize_session_id: str | None = None,
    conversation_session_id: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> int:
    """Enter full-book chat grounded on segment summaries."""
    progress = result.reading_progress
    if progress is None:
        return 1
    if progress.done_count() <= 0:
        return 1

    preview = build_book_context(
        progress,
        filename=result.filename,
        provider=provider,
    )
    if history is None:
        history = [
            {
                "role": "user",
                "content": (
                    f"请基于全书各段摘要，围绕《{result.filename}》回答我的问题。"
                ),
            },
            {"role": "assistant", "content": preview or result.markdown},
        ]

    if summarize_session_id:
        mark_book_chat_entered(summarize_session_id)

    return DocumentChatREPL(
        result,
        provider=provider,
        summarize_session_id=summarize_session_id,
        conversation_session_id=conversation_session_id,
        history=history,
        deep_segment_only=True,
        no_prefetch=True,
        chat_scope="book",
    ).run()
