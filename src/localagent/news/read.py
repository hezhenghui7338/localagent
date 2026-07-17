"""Deep-read an article: fetch → summarize card (optional keep)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from localagent import config
from localagent.ingest.loader import LoadedDoc
from localagent.news.fetch import FetchResult, fetch_article
from localagent.news.links import format_article_link_block
from localagent.news.store import Article, NewsStore, article_id_for_url, normalize_url
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


def read_article(
    id_or_url: str,
    *,
    keep: bool = False,
    use_llm: bool = True,
    store: NewsStore | None = None,
    plain_links: bool = False,
) -> ReadResult:
    store = store or NewsStore()
    empty = Article(id="", source_id="", url="")
    try:
        article = _ensure_article(id_or_url, store)
    except SummarizeError as exc:
        return ReadResult(markdown="", article=empty, error=str(exc))

    cache_path = config.NEWS_CACHE_DIR / f"{article.id}.md"
    title = article.title
    text = ""
    if cache_path.exists():
        raw_body = cache_path.read_text(encoding="utf-8")
        # Strip leading markdown title / source lines if present
        text = raw_body
        for line in raw_body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip() or title
                break
    else:
        fetched: FetchResult = fetch_article(article.url)
        if not fetched.ok:
            return ReadResult(markdown="", article=article, error=fetched.error)
        text = fetched.text
        if fetched.title:
            title = fetched.title
        config.ensure_data_dirs()
        body = f"# {title}\n\n来源: {article.url}\n\n{text}"
        cache_path.write_text(body, encoding="utf-8")
        store.update_fields(
            article.id,
            title=title or article.title,
            fetched_text_path=str(cache_path),
        )

    # Prefer body without meta prefix for summarizer when cache has full file
    body_for_sum = text
    if body_for_sum.startswith("# "):
        parts = body_for_sum.split("\n\n", 2)
        if len(parts) == 3 and parts[1].startswith("来源:"):
            body_for_sum = parts[2]

    doc = LoadedDoc(
        text=f"# {title}\n\n{body_for_sum}",
        source=article.url,
        filename=f"{article.id}.md",
        metadata={"suffix": ".md", "url": article.url},
    )

    warnings: list[str] = []
    annotated_len = len(doc.text)
    if annotated_len > config.SUMMARIZE_SHORT_MAX_CHARS:
        doc.text = doc.text[: config.SUMMARIZE_SHORT_MAX_CHARS - 1] + "…"
        warnings.append(
            f"正文过长（约 {annotated_len} 字），已截断至短总结上限后生成卡片"
        )

    try:
        result = summarize_loaded(doc, use_llm=use_llm)
    except (DocumentTooLongError, SummarizeError) as exc:
        return ReadResult(markdown="", article=article, error=str(exc))

    warnings.extend(result.warnings)
    link_block = format_article_link_block(
        title=title or article.title or "打开原文",
        url=article.url,
        plain=plain_links,
    )
    markdown = (
        f"{link_block}\n\n"
        f"id: `{article.id}`\n\n"
        f"{result.markdown.rstrip()}\n\n"
        f"---\n原文: {article.url}\n"
    )
    if warnings:
        markdown += "\n（" + "；".join(warnings) + "）\n"

    kept = False
    keep_target: Path | None = None
    if keep:
        from localagent.ingest.add_file import add_file

        if not cache_path.exists():
            cache_path.write_text(
                f"# {title}\n\n来源: {article.url}\n\n{body_for_sum}",
                encoding="utf-8",
            )
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
    )
