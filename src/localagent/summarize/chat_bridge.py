"""Bridge segment browser into DocumentChatREPL deep chat."""

from __future__ import annotations

from localagent.summarize.document import SummarizeResult
from localagent.summarize.repl import DocumentChatREPL


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
    ).run()
