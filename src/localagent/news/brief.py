"""Format daily news brief markdown."""

from __future__ import annotations

from datetime import date

from localagent.news.links import format_article_link_block, hyperlink
from localagent.news.profile import NewsProfile, load_news_profile
from localagent.news.rank import RankedArticle, rank_articles
from localagent.news.store import Article, NewsStore


def format_brief(
    ranked: list[RankedArticle],
    *,
    brief_date: str | None = None,
    plain_links: bool = False,
) -> str:
    day = brief_date or date.today().isoformat()
    lines = [
        f"# 今日新闻简报 · {day}",
        "",
        f"共 {len(ranked)} 条 · `la news read <id>` 精读 · 点击标题或原文链接打开浏览器",
        "",
    ]
    if not ranked:
        lines.append("_暂无条目。先运行 `la news sync`。_")
        lines.append("")
        return "\n".join(lines)

    for i, item in enumerate(ranked, 1):
        art = item.article
        summary = art.display_summary()
        if len(summary) > 220:
            summary = summary[:219] + "…"
        reason = "；".join(item.reasons[:3]) if item.reasons else "候选"
        title_link = hyperlink(art.title or art.url, art.url, force_plain=plain_links)
        lines.append(f"## {i}. {title_link}")
        lines.append(f"- id: `{art.id}`")
        if summary:
            lines.append(f"- 一句话: {summary}")
        lines.append(f"- 为何入选: {reason}")
        if art.published_at:
            lines.append(f"- 发布: {art.published_at[:10]}")
        lines.append(f"- 原文: {art.url}")
        lines.append("")
    lines.append("---")
    lines.append("提示: `la news skim <id>` 速读 · `la news mark <id> bookmark|skip`")
    lines.append("")
    return "\n".join(lines)


def build_brief(
    *,
    since_date: str | None = None,
    limit: int | None = None,
    store: NewsStore | None = None,
    profile: NewsProfile | None = None,
    plain_links: bool = False,
) -> tuple[str, list[RankedArticle]]:
    store = store or NewsStore()
    profile = profile or load_news_profile()
    day = since_date or date.today().isoformat()
    # Pull a wider pool then rank down
    pool_limit = max(80, (limit or profile.daily_brief_size) * 4)
    articles = store.list_recent(since_date=day, limit=pool_limit)
    # If today empty, fall back to last sync batch (any recent)
    if not articles:
        articles = store.list_recent(since_date=None, limit=pool_limit)
    ranked = rank_articles(articles, profile=profile, limit=limit)
    for item in ranked:
        if item.article.status == "new":
            store.set_status(item.article.id, "briefed")
    text = format_brief(ranked, brief_date=day, plain_links=plain_links)
    return text, ranked


def format_skim_card(article: Article, *, plain_links: bool = False) -> str:
    summary = article.display_summary() or "（暂无摘要）"
    points = (article.structured_skim or "").strip()
    lines = [
        f"# 速读 · {article.title or article.id}",
        "",
        format_article_link_block(
            title=article.title or "打开原文",
            url=article.url,
            plain=plain_links,
        ),
        "",
        "## 一句话",
        summary,
        "",
    ]
    if points:
        lines.extend(["## 结构化要点", points, ""])
    else:
        # Derive light bullets from rss summary sentences
        sentences = [
            s.strip()
            for s in summary.replace("。", "。\n").splitlines()
            if s.strip() and len(s.strip()) > 8
        ][:5]
        if sentences:
            lines.append("## 要点（来自摘要）")
            for s in sentences:
                lines.append(f"- {s}")
            lines.append("")
    lines.extend(
        [
            f"id: `{article.id}`",
            f"状态: {article.status}",
            "",
            "精读: `la news read " + article.id + "`",
            f"原文: {article.url}",
            "",
        ]
    )
    return "\n".join(lines)
