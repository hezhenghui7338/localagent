"""Deep-read an article: fetch → summarize card (optional keep)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from localagent import config
from localagent.ingest.loader import LoadedDoc
from localagent.news.fetch import FetchResult, body_quality_ok, fetch_article
from localagent.news.links import format_article_link_block
from localagent.news.store import Article, NewsStore, article_id_for_url, normalize_url
from localagent.news.summary_parse import parse_rss_summary
from localagent.summarize.document import (
    DocumentTooLongError,
    SummarizeError,
    summarize_loaded,
)


@dataclass
class ReadResult:
    markdown: str
    article: Article
    kept: bool = False
    keep_target: Path | None = None
    warnings: list[str] | None = None
    error: str = ""
    body_complete: bool = True
    session_source_key: str = ""


def _ensure_article(id_or_url: str, store: NewsStore) -> Article:
    existing = store.resolve(id_or_url)
    if existing:
        return existing
    raw = (id_or_url or "").strip()
    if "://" not in raw and not raw.startswith("www."):
        raise SummarizeError(f"未找到文章: {id_or_url}")
    url = normalize_url(raw if "://" in raw else f"https://{raw}")
    art = Article(
        id=article_id_for_url(url),
        source_id="manual",
        url=url,
        title=url,
        status="new",
    )
    store.upsert_article(art)
    return store.get(art.id) or art


def _strip_cache_meta(raw: str) -> tuple[str, str]:
    """Return (title_from_heading, body_without_title/source_prefix)."""
    text = raw or ""
    title = ""
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    body = text
    if body.startswith("# "):
        parts = body.split("\n\n", 2)
        if len(parts) == 3 and parts[1].startswith("来源:"):
            body = parts[2]
        elif len(parts) >= 2:
            body = "\n\n".join(parts[1:])
    return title, body.strip()


def _expected_word_count(article: Article) -> int | None:
    parsed = parse_rss_summary(article.rss_summary or "")
    raw = (parsed.meta or {}).get("word_count") or ""
    try:
        val = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def _origin_hints(article: Article) -> list[str]:
    parsed = parse_rss_summary(article.rss_summary or "")
    source = (parsed.meta or {}).get("source") or ""
    hints: list[str] = []
    # Meta "来源" is often a site name, but sometimes a URL.
    if source.startswith(("http://", "https://")):
        hints.append(source.strip())
    return hints


def _rss_fallback_body(article: Article) -> tuple[str, list[str]]:
    """Build a chat-limited body from RSS structured summary."""
    parsed = parse_rss_summary(article.rss_summary or "")
    parts: list[str] = []
    if parsed.one_liner:
        parts.append(parsed.one_liner)
    if parsed.detail:
        parts.append(parsed.detail)
    if parsed.viewpoints:
        parts.append("主要观点：\n" + "\n".join(f"- {v}" for v in parsed.viewpoints))
    if parsed.quotes:
        parts.append("金句：\n" + "\n".join(f"- {q}" for q in parsed.quotes))
    body = "\n\n".join(p for p in parts if p.strip()).strip()
    warnings = [
        "未拿到完整正文，已用 RSS 摘要降级；深聊仅基于摘要，细节可能不足"
    ]
    return body, warnings


def _write_cache(cache_path: Path, title: str, url: str, body: str) -> None:
    config.ensure_data_dirs()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        f"# {title}\n\n来源: {url}\n\n{body}",
        encoding="utf-8",
    )


def _omit_misleading_asks(markdown: str, *, body_complete: bool) -> str:
    """Drop '接着问' section when body is incomplete (avoids inventing deep Qs)."""
    if body_complete or not markdown:
        return markdown
    lines = markdown.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith("## ") and "你可以接着问" in line:
            skipping = True
            continue
        if skipping and line.startswith("## "):
            skipping = False
        if skipping:
            continue
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def read_article(
    id_or_url: str,
    *,
    keep: bool = False,
    use_llm: bool = True,
    store: NewsStore | None = None,
    plain_links: bool = False,
    force_refetch: bool = False,
) -> ReadResult:
    store = store or NewsStore()
    empty = Article(id="", source_id="", url="")
    try:
        article = _ensure_article(id_or_url, store)
    except SummarizeError as exc:
        return ReadResult(markdown="", article=empty, error=str(exc))

    cache_path = config.NEWS_CACHE_DIR / f"{article.id}.md"
    title = article.title
    body_for_sum = ""
    warnings: list[str] = []
    body_complete = True
    expected = _expected_word_count(article)

    # --- Resolve body (cache / fetch / RSS fallback) ---
    use_cache = cache_path.exists() and not force_refetch
    if use_cache:
        raw_body = cache_path.read_text(encoding="utf-8")
        cached_title, cached_body = _strip_cache_meta(raw_body)
        if cached_title:
            title = cached_title
        if body_quality_ok(cached_body, expected_word_count=expected):
            body_for_sum = cached_body
        else:
            use_cache = False
            warnings.append("缓存正文过短，已重新抓取")

    if not body_for_sum:
        fetched: FetchResult = fetch_article(
            article.url,
            expected_word_count=expected,
            origin_hints=_origin_hints(article),
        )
        warnings.extend(fetched.warnings)
        if fetched.ok and body_quality_ok(fetched.text, expected_word_count=expected):
            body_for_sum = fetched.text
            if fetched.title:
                title = fetched.title
            _write_cache(cache_path, title or article.title, article.url, body_for_sum)
            store.update_fields(
                article.id,
                title=title or article.title,
                fetched_text_path=str(cache_path),
            )
        elif fetched.text and body_quality_ok(
            fetched.text, min_chars=max(200, config.NEWS_FETCH_MIN_CHARS // 2)
        ):
            # Soft accept: better than RSS, but warn.
            body_for_sum = fetched.text
            body_complete = False
            if fetched.title:
                title = fetched.title
            warnings.append(
                f"正文偏短（约 {len(fetched.text)} 字），可能不完整；{fetched.error or '质量门控未完全通过'}"
            )
            _write_cache(cache_path, title or article.title, article.url, body_for_sum)
            store.update_fields(
                article.id,
                title=title or article.title,
                fetched_text_path=str(cache_path),
            )
        else:
            rss_body, rss_warns = _rss_fallback_body(article)
            if not rss_body:
                err = fetched.error or "未能抽取正文"
                return ReadResult(markdown="", article=article, error=err, warnings=warnings)
            body_for_sum = rss_body
            body_complete = False
            warnings.extend(rss_warns)
            if fetched.error:
                warnings.append(fetched.error)
            _write_cache(cache_path, title or article.title, article.url, body_for_sum)
            store.update_fields(
                article.id,
                title=title or article.title,
                fetched_text_path=str(cache_path),
            )

    doc = LoadedDoc(
        text=f"# {title}\n\n{body_for_sum}",
        source=article.url,
        filename=f"{article.id}.md",
        metadata={"suffix": ".md", "url": article.url},
    )

    # Card generation may clip; full body stays in cache for indexing / deep chat.
    card_doc = doc
    annotated_len = len(doc.text)
    if annotated_len > config.SUMMARIZE_SHORT_MAX_CHARS:
        clipped = LoadedDoc(
            text=doc.text[: config.SUMMARIZE_SHORT_MAX_CHARS - 1] + "…",
            source=doc.source,
            filename=doc.filename,
            metadata=dict(doc.metadata),
        )
        card_doc = clipped
        warnings.append(
            f"正文过长（约 {annotated_len} 字），速读卡按截断文本生成；深聊可检索全文"
        )

    try:
        result = summarize_loaded(card_doc, use_llm=use_llm, allow_long=True)
    except (DocumentTooLongError, SummarizeError) as exc:
        return ReadResult(markdown="", article=article, error=str(exc), warnings=warnings)

    # Prefer full annotated text for deep chat / indexing.
    from localagent.summarize.document import _annotate_for_cite

    full_annotated = _annotate_for_cite(doc)
    result.annotated_text = full_annotated
    result.char_count = len(full_annotated)
    result.warnings = list(dict.fromkeys([*warnings, *result.warnings]))

    card_md = _omit_misleading_asks(result.markdown, body_complete=body_complete)
    result.markdown = card_md

    # Session Cold index (does not require /keep).
    session_key = ""
    try:
        from localagent.summarize.session_index import index_document_session, news_source_key

        session_key = news_source_key(article.id)
        index_document_session(
            session_key,
            full_annotated,
            title=title or article.title,
        )
        result.session_source_key = session_key
    except Exception as exc:  # pragma: no cover - indexing should not block read
        result.warnings.append(f"会话向量化跳过: {exc}")

    warnings = result.warnings
    link_block = format_article_link_block(
        title=title or article.title or "打开原文",
        url=article.url,
        plain=plain_links,
    )
    markdown = (
        f"{link_block}\n\n"
        f"id: `{article.id}`\n\n"
        f"{card_md.rstrip()}\n\n"
        f"---\n原文: {article.url}\n"
    )
    if warnings:
        markdown += "\n（" + "；".join(warnings) + "）\n"

    kept = False
    keep_target: Path | None = None
    if keep:
        from localagent.ingest.add_file import add_file

        if not cache_path.exists():
            _write_cache(cache_path, title or article.title, article.url, body_for_sum)
        target, _ = add_file(cache_path)
        kept = True
        keep_target = target
        markdown += f"\n已入库: {keep_target}\n"

    store.update_fields(
        article.id,
        status="deep_read",
        fetched_text_path=str(cache_path),
    )
    refreshed = store.get(article.id) or article
    return ReadResult(
        markdown=markdown,
        article=refreshed,
        kept=kept,
        keep_target=keep_target,
        warnings=warnings,
        body_complete=body_complete,
        session_source_key=session_key,
    )
