"""SQLite store for news articles + sync metadata helpers."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from localagent import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    rss_summary TEXT NOT NULL DEFAULT '',
    one_liner TEXT NOT NULL DEFAULT '',
    structured_skim TEXT NOT NULL DEFAULT '',
    score_hint REAL,
    status TEXT NOT NULL DEFAULT 'new',
    fetched_text_path TEXT NOT NULL DEFAULT '',
    synced_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_synced ON articles(synced_at);
"""


def normalize_url(url: str) -> str:
    """Canonicalize URL for dedup (strip fragment, trailing slash, lowercase host)."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "https").lower()
    netloc = (parsed.netloc or "").lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    # Drop tracking query noise lightly
    query = parsed.query
    if query:
        parts = [
            p
            for p in query.split("&")
            if p
            and not p.lower().startswith(
                ("utm_", "fbclid=", "gclid=", "mc_cid=", "mc_eid=")
            )
        ]
        query = "&".join(parts)
    return urlunparse((scheme, netloc, path, "", query, ""))


def article_id_for_url(url: str) -> str:
    canon = normalize_url(url)
    digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
    return f"n_{digest}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_local() -> str:
    return date.today().isoformat()


@dataclass
class Article:
    id: str
    source_id: str
    url: str
    title: str = ""
    author: str = ""
    published_at: str = ""
    rss_summary: str = ""
    one_liner: str = ""
    structured_skim: str = ""
    score_hint: float | None = None
    status: str = "new"
    fetched_text_path: str = ""
    synced_at: str = ""
    updated_at: str = ""

    def _parsed_summary(self):
        from localagent.news.summary_parse import parse_rss_summary

        return parse_rss_summary(self.rss_summary or "")

    def display_summary(self) -> str:
        """One-liner only (never the full RSS blob)."""
        if (self.one_liner or "").strip():
            return self.one_liner.strip()
        parsed = self._parsed_summary()
        if parsed.one_liner:
            return parsed.one_liner
        return ""

    def resolved_detail(self) -> str:
        parsed = self._parsed_summary()
        if parsed.detail:
            return parsed.detail
        return ""

    def resolved_viewpoints(self) -> list[str]:
        if (self.structured_skim or "").strip():
            lines: list[str] = []
            for raw in self.structured_skim.splitlines():
                s = raw.strip()
                if not s:
                    continue
                if s.startswith(("·", "-", "*")):
                    s = s.lstrip("·-* ").strip()
                if s and not s.startswith(" "):
                    lines.append(s)
            if lines:
                return lines
        return list(self._parsed_summary().viewpoints)

    def resolved_viewpoint_notes(self) -> list[str]:
        return list(self._parsed_summary().viewpoint_notes)

    def resolved_quotes(self) -> list[str]:
        return list(self._parsed_summary().quotes)

    def resolved_meta(self) -> dict[str, str]:
        return dict(self._parsed_summary().meta)


class NewsStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else config.NEWS_DB_FILE
        config.ensure_data_dirs()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def upsert_article(self, article: Article) -> bool:
        """Insert or refresh; returns True if newly inserted."""
        now = _utc_now()
        article.updated_at = now
        if not article.synced_at:
            article.synced_at = now
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM articles WHERE url = ? OR id = ?",
                (article.url, article.id),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE articles SET
                        title = COALESCE(NULLIF(?, ''), title),
                        author = COALESCE(NULLIF(?, ''), author),
                        published_at = COALESCE(NULLIF(?, ''), published_at),
                        rss_summary = COALESCE(NULLIF(?, ''), rss_summary),
                        one_liner = COALESCE(NULLIF(?, ''), one_liner),
                        structured_skim = COALESCE(NULLIF(?, ''), structured_skim),
                        score_hint = COALESCE(?, score_hint),
                        synced_at = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        article.title,
                        article.author,
                        article.published_at,
                        article.rss_summary,
                        article.one_liner,
                        article.structured_skim,
                        article.score_hint,
                        now,
                        now,
                        existing["id"],
                    ),
                )
                return False
            conn.execute(
                """
                INSERT INTO articles (
                    id, source_id, url, title, author, published_at,
                    rss_summary, one_liner, structured_skim, score_hint,
                    status, fetched_text_path, synced_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article.id,
                    article.source_id,
                    article.url,
                    article.title,
                    article.author,
                    article.published_at,
                    article.rss_summary,
                    article.one_liner,
                    article.structured_skim,
                    article.score_hint,
                    article.status,
                    article.fetched_text_path,
                    article.synced_at,
                    article.updated_at,
                ),
            )
            return True

    def get(self, article_id: str) -> Article | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM articles WHERE id = ?", (article_id,)
            ).fetchone()
        return _row_to_article(row) if row else None

    def get_by_url(self, url: str) -> Article | None:
        canon = normalize_url(url)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM articles WHERE url = ?", (canon,)
            ).fetchone()
            if row:
                return _row_to_article(row)
            # Fallback: match by id hash
            aid = article_id_for_url(url)
            row = conn.execute(
                "SELECT * FROM articles WHERE id = ?", (aid,)
            ).fetchone()
        return _row_to_article(row) if row else None

    def resolve(self, id_or_url: str) -> Article | None:
        raw = (id_or_url or "").strip()
        if not raw:
            return None
        if raw.startswith("n_") or re.fullmatch(r"[0-9a-f]{16}", raw):
            art = self.get(raw if raw.startswith("n_") else f"n_{raw}")
            if art:
                return art
        if "://" in raw or raw.startswith("www."):
            return self.get_by_url(raw if "://" in raw else f"https://{raw}")
        return self.get(raw)

    def list_recent(
        self,
        *,
        since_date: str | None = None,
        limit: int = 100,
        exclude_statuses: tuple[str, ...] = ("skipped",),
    ) -> list[Article]:
        clauses = ["1=1"]
        params: list[Any] = []
        if since_date:
            clauses.append(
                "(date(substr(published_at, 1, 10)) >= date(?) OR date(substr(synced_at, 1, 10)) >= date(?))"
            )
            params.extend([since_date, since_date])
        if exclude_statuses:
            placeholders = ",".join("?" * len(exclude_statuses))
            clauses.append(f"status NOT IN ({placeholders})")
            params.extend(exclude_statuses)
        params.append(limit)
        sql = (
            f"SELECT * FROM articles WHERE {' AND '.join(clauses)} "
            "ORDER BY published_at DESC, synced_at DESC LIMIT ?"
        )
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_article(r) for r in rows]

    def count_by_status(self, status: str) -> int:
        """Count articles with the given status (e.g. bookmarked)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM articles WHERE status = ?",
                (status,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def set_status(self, article_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE articles SET status = ?, updated_at = ? WHERE id = ?",
                (status, _utc_now(), article_id),
            )

    def update_fields(self, article_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "one_liner",
            "structured_skim",
            "rss_summary",
            "status",
            "fetched_text_path",
            "score_hint",
            "title",
        }
        cols = []
        vals: list[Any] = []
        for key, val in fields.items():
            if key in allowed:
                cols.append(f"{key} = ?")
                vals.append(val)
        if not cols:
            return
        cols.append("updated_at = ?")
        vals.append(_utc_now())
        vals.append(article_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE articles SET {', '.join(cols)} WHERE id = ?",
                vals,
            )


def _row_to_article(row: sqlite3.Row) -> Article:
    return Article(
        id=row["id"],
        source_id=row["source_id"],
        url=row["url"],
        title=row["title"] or "",
        author=row["author"] or "",
        published_at=row["published_at"] or "",
        rss_summary=row["rss_summary"] or "",
        one_liner=row["one_liner"] or "",
        structured_skim=row["structured_skim"] or "",
        score_hint=row["score_hint"],
        status=row["status"] or "new",
        fetched_text_path=row["fetched_text_path"] or "",
        synced_at=row["synced_at"] or "",
        updated_at=row["updated_at"] or "",
    )


# --- sync state (JSON) ---


def load_sync_state() -> dict[str, Any]:
    path = config.NEWS_SYNC_STATE_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_sync_state(state: dict[str, Any]) -> None:
    config.ensure_data_dirs()
    config.NEWS_SYNC_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def mark_sync_success(*, count: int, source_url: str) -> None:
    state = load_sync_state()
    now = _utc_now()
    state["last_sync_at"] = now
    state["last_sync_date"] = _today_local()
    state["last_sync_count"] = count
    state["last_source_url"] = source_url
    state["last_error"] = ""
    save_sync_state(state)


def mark_sync_error(message: str) -> None:
    state = load_sync_state()
    state["last_error"] = message
    state["last_error_at"] = _utc_now()
    save_sync_state(state)


def mark_ready_notified() -> None:
    state = load_sync_state()
    state["ready_notified_date"] = _today_local()
    save_sync_state(state)


def today_synced() -> bool:
    return load_sync_state().get("last_sync_date") == _today_local()


def ready_already_notified() -> bool:
    return load_sync_state().get("ready_notified_date") == _today_local()
