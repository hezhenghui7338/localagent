"""RSS intake helpers (BestBlogs and generic feeds)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

from localagent.news.store import Article, article_id_for_url, normalize_url

_HTML_TAG = re.compile(r"<[^>]+>")
_SCORE_RE = re.compile(r"(?:score|评分|分)[:\s]*(\d{1,3})", re.I)


@dataclass
class FeedItem:
    url: str
    title: str
    summary: str
    author: str
    published_at: str
    score_hint: float | None = None


def _strip_html(text: str) -> str:
    cleaned = _HTML_TAG.sub(" ", text or "")
    return " ".join(cleaned.split()).strip()


def _parse_published(entry: Any) -> str:
    for key in ("published", "updated", "created"):
        raw = getattr(entry, key, None) or entry.get(key) if hasattr(entry, "get") else None
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(str(raw))
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            # Already ISO-ish
            s = str(raw).strip()
            if len(s) >= 10:
                return s[:19] + ("Z" if "T" in s and not s.endswith("Z") else "")
    published_parsed = getattr(entry, "published_parsed", None) or entry.get(
        "published_parsed"
    )
    if published_parsed:
        try:
            from time import struct_time, mktime
            from datetime import datetime, timezone

            if isinstance(published_parsed, struct_time):
                ts = mktime(published_parsed)
                return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
        except Exception:
            pass
    return ""


def _guess_score(*texts: str) -> float | None:
    for text in texts:
        m = _SCORE_RE.search(text or "")
        if m:
            val = int(m.group(1))
            if 0 <= val <= 100:
                return float(val)
    return None


def fetch_feed_bytes(url: str, *, timeout: float = 30.0) -> bytes:
    headers = {
        "User-Agent": "LocalAgent-news/1.0 (+https://github.com/hezhenghui7338/localagent)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content


def parse_feed(content: bytes | str, *, source_url: str = "") -> list[FeedItem]:
    parsed = feedparser.parse(content)
    items: list[FeedItem] = []
    for entry in parsed.entries or []:
        link = ""
        if getattr(entry, "link", None):
            link = str(entry.link).strip()
        elif entry.get("links"):
            for cand in entry.links:
                href = cand.get("href") if isinstance(cand, dict) else None
                if href:
                    link = str(href).strip()
                    break
        url = normalize_url(link)
        if not url:
            continue
        title = _strip_html(str(getattr(entry, "title", "") or ""))
        summary = _strip_html(
            str(
                getattr(entry, "summary", None)
                or getattr(entry, "description", None)
                or ""
            )
        )
        author = _strip_html(str(getattr(entry, "author", "") or ""))
        published = _parse_published(entry)
        score = _guess_score(title, summary)
        items.append(
            FeedItem(
                url=url,
                title=title or url,
                summary=summary,
                author=author,
                published_at=published,
                score_hint=score,
            )
        )
    return items


def feed_items_to_articles(
    items: list[FeedItem], *, source_id: str = "bestblogs_rss"
) -> list[Article]:
    articles: list[Article] = []
    for item in items:
        articles.append(
            Article(
                id=article_id_for_url(item.url),
                source_id=source_id,
                url=item.url,
                title=item.title,
                author=item.author,
                published_at=item.published_at,
                rss_summary=item.summary,
                score_hint=item.score_hint,
                status="new",
            )
        )
    return articles
