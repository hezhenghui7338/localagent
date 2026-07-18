"""Bridge news ReadResult into DocumentChatREPL / SummarizeResult."""

from __future__ import annotations

from pathlib import Path

from localagent import config
from localagent.news.read import ReadResult
from localagent.summarize.document import SummarizeResult


def read_result_to_summarize(result: ReadResult) -> SummarizeResult:
    """Build a SummarizeResult so DocumentChatREPL can deep-chat an article."""
    art = result.article
    cache = Path(art.fetched_text_path) if art.fetched_text_path else (
        config.NEWS_CACHE_DIR / f"{art.id}.md"
    )
    annotated = ""
    if cache.exists():
        annotated = cache.read_text(encoding="utf-8")
    title = art.title or art.id or "article"
    # Strip link chrome from read markdown for the "速读卡" section if needed
    card = (result.markdown or "").strip()
    session_key = (result.session_source_key or "").strip()
    if not session_key and art.id:
        session_key = f"news:{art.id}"
    return SummarizeResult(
        markdown=card,
        path=cache if cache.exists() else Path(art.url or title),
        filename=title,
        char_count=len(annotated) or len(card),
        page_count=None,
        kept=result.kept,
        keep_target=result.keep_target,
        used_llm=True,
        warnings=list(result.warnings or []),
        annotated_text=annotated,
        session_source_key=session_key,
    )


def run_article_chat(result: ReadResult, *, provider: str = "auto") -> int:
    """Enter document chat scoped to the article; returns DocumentChatREPL exit code."""
    from localagent.summarize.repl import run_document_chat
    from localagent.summarize.session_index import index_document_session, news_source_key

    if result.error or not result.markdown:
        print(f"[news] 无法进入深聊: {result.error or '无内容'}")
        return 1
    summary = read_result_to_summarize(result)
    # Ensure session index exists even if read_article skipped indexing.
    if summary.annotated_text.strip():
        key = summary.session_source_key or news_source_key(result.article.id)
        try:
            index_document_session(
                key,
                summary.annotated_text,
                title=summary.filename,
            )
            summary.session_source_key = key
        except Exception as exc:
            print(f"[news] 会话向量化跳过: {exc}")
    print()
    print(result.markdown.rstrip())
    print()
    if result.body_complete is False:
        print("[news] 注意：正文可能不完整，深聊依据有限")
    print("[news] 进入文章深聊（与 la summarize 相同）；/exit 返回简报浏览器")
    return run_document_chat(summary, provider=provider)
