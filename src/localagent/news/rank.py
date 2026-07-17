"""Interest ranking for news brief."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from localagent.news.profile import NewsProfile, load_news_profile
from localagent.news.store import Article


@dataclass
class RankedArticle:
    article: Article
    score: float
    reasons: list[str]


def _parse_ts(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        if "T" in s:
            return datetime.fromisoformat(s)
        return datetime.fromisoformat(s[:10]).replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _freshness_boost(article: Article, *, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    ts = _parse_ts(article.published_at) or _parse_ts(article.synced_at)
    if not ts:
        return 0.0
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - ts).total_seconds() / 3600.0)
    if hours <= 24:
        return 3.0
    if hours <= 72:
        return 1.5
    if hours <= 168:
        return 0.5
    return 0.0


def score_article(
    article: Article,
    profile: NewsProfile,
    *,
    now: datetime | None = None,
) -> RankedArticle:
    blob = " ".join(
        [
            article.title or "",
            article.rss_summary or "",
            article.one_liner or "",
            article.author or "",
        ]
    ).lower()
    score = 0.0
    reasons: list[str] = []

    for kw in profile.mute_keywords:
        if kw and kw.lower() in blob:
            return RankedArticle(article=article, score=-1000.0, reasons=[f"mute:{kw}"])

    for interest in profile.interests:
        if interest and interest.lower() in blob:
            score += 2.0
            reasons.append(f"兴趣:{interest}")

    for kw in profile.boost_keywords:
        if kw and kw.lower() in blob:
            score += 1.5
            reasons.append(f"加权:{kw}")

    fresh = _freshness_boost(article, now=now)
    if fresh:
        score += fresh
        reasons.append("新鲜")

    if article.status == "bookmarked":
        score += 2.0
        reasons.append("已收藏来源偏好")

    if article.score_hint is not None:
        # Upstream quality hint (0-100) → small additive
        score += float(article.score_hint) / 50.0
        reasons.append(f"质量提示:{int(article.score_hint)}")

    if not reasons:
        reasons.append("默认候选")

    return RankedArticle(article=article, score=score, reasons=reasons)


def rank_articles(
    articles: list[Article],
    *,
    profile: NewsProfile | None = None,
    limit: int | None = None,
) -> list[RankedArticle]:
    profile = profile or load_news_profile()
    ranked = [score_article(a, profile) for a in articles]
    ranked = [r for r in ranked if r.score > -500]
    ranked.sort(
        key=lambda r: (r.score, r.article.published_at or "", r.article.title),
        reverse=True,
    )
    cap = limit if limit is not None else profile.daily_brief_size
    return ranked[: max(0, cap)]
