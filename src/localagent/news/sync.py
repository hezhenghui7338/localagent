"""Sync news from configured RSS sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from localagent import config
from localagent.news.rss import feed_items_to_articles, fetch_feed_bytes, parse_feed
from localagent.news.store import (
    NewsStore,
    mark_sync_error,
    mark_sync_success,
)


@dataclass
class SyncResult:
    source_url: str
    fetched: int
    inserted: int
    updated: int
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


def _append_sync_log(line: str) -> None:
    config.ensure_data_dirs()
    path: Path = config.NEWS_SYNC_LOG_FILE
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {line}\n")


def sync_news(
    *,
    rss_url: str | None = None,
    store: NewsStore | None = None,
) -> SyncResult:
    """Fetch RSS and upsert articles. Updates sync_state on success/failure."""
    url = (rss_url or config.NEWS_RSS_URL).strip()
    store = store or NewsStore()
    try:
        raw = fetch_feed_bytes(url)
        items = parse_feed(raw, source_url=url)
        articles = feed_items_to_articles(items, source_id="bestblogs_rss")
        inserted = 0
        updated = 0
        for art in articles:
            if store.upsert_article(art):
                inserted += 1
            else:
                updated += 1
        mark_sync_success(count=len(articles), source_url=url)
        _append_sync_log(
            f"OK source={url} fetched={len(articles)} inserted={inserted} updated={updated}"
        )
        return SyncResult(
            source_url=url,
            fetched=len(articles),
            inserted=inserted,
            updated=updated,
        )
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        mark_sync_error(msg)
        _append_sync_log(f"ERR source={url} {msg}")
        return SyncResult(
            source_url=url,
            fetched=0,
            inserted=0,
            updated=0,
            error=msg,
        )
