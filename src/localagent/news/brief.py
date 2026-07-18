"""Format daily news brief markdown and article detail panels."""

from __future__ import annotations

from datetime import date

from localagent.news.links import hyperlink
from localagent.news.profile import NewsProfile, load_news_profile
from localagent.news.rank import RankedArticle, rank_articles
from localagent.news.store import Article, NewsStore


def _truncate_chars(text: str, limit: int) -> str:
    raw = (text or "").strip()
    if limit <= 0 or len(raw) <= limit:
        return raw
    return raw[: limit - 1] + "…"


def _indent_block(text: str, *, indent: str = "  ") -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    # Keep as single flowing paragraph; terminal wrap_lines handles width.
    return [f"{indent}{raw}"]


def format_article_detail(
    article: Article,
    *,
    mode: str = "summary",
    reasons: list[str] | None = None,
    rule_width: int = 60,
) -> str:
    """Shared detail panel for interactive brief and skim card.

    mode:
      - summary: compact detail (truncated), fewer viewpoints
      - skim: full detail + all viewpoints (notes indented)
    """
    is_skim = mode == "skim"
    title = (article.title or article.id or "").strip() or article.url
    prefix = "【速读】" if is_skim else "【当前】"
    one = article.display_summary() or "（暂无摘要）"
    detail = article.resolved_detail()
    viewpoints = article.resolved_viewpoints()
    notes = article.resolved_viewpoint_notes() if is_skim else []
    quotes = article.resolved_quotes() if is_skim else []
    meta = article.resolved_meta()

    detail_limit = 0 if is_skim else 360
    vp_limit = 0 if is_skim else 5
    if detail_limit and detail:
        detail = _truncate_chars(detail, detail_limit)
    if vp_limit and viewpoints:
        viewpoints = viewpoints[:vp_limit]
        notes = notes[:vp_limit] if notes else []

    lines: list[str] = [f"{prefix}{title}", "", one]

    if detail:
        lines.append("")
        lines.append("详细摘要")
        lines.extend(_indent_block(detail))

    if viewpoints:
        lines.append("")
        lines.append("主要观点")
        for i, claim in enumerate(viewpoints):
            lines.append(f"  · {claim}")
            if is_skim and i < len(notes):
                note = (notes[i] or "").strip()
                if note:
                    lines.append(f"    {note}")

    if quotes:
        lines.append("")
        lines.append("金句")
        for q in quotes[:6]:
            lines.append(f"  · {q}")

    lines.append("")
    lines.append("─" * max(20, min(rule_width, 60)))

    if reasons:
        lines.append(f"入选  {' · '.join(reasons[:3])}")
    elif not is_skim:
        lines.append("入选  候选")

    pub_bits: list[str] = []
    if article.published_at:
        pub_bits.append(article.published_at[:10])
    if meta.get("ai_score"):
        pub_bits.append(f"AI初评 {meta['ai_score']}")
    if meta.get("read_mins"):
        pub_bits.append(f"{meta['read_mins']}分钟")
    source = meta.get("source") or meta.get("author") or article.author
    if source:
        pub_bits.append(source)
    if pub_bits:
        lines.append(f"发布  {' · '.join(pub_bits)}")

    lines.append(f"编号  {article.id}")
    lines.append(f"原文  {article.url}")
    return "\n".join(lines)


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


def format_skim_card(
    article: Article,
    *,
    plain_links: bool = False,
    reasons: list[str] | None = None,
) -> str:
    """Skim card for CLI and interactive browser (shared layout with summary)."""
    del plain_links  # URL is always bare at the bottom; no title link.
    return format_article_detail(article, mode="skim", reasons=reasons)
