"""Mark / feedback actions for news articles."""

from __future__ import annotations

from localagent.news.profile import add_mute_keyword
from localagent.news.store import Article, NewsStore


def mark_article(
    id_or_url: str,
    action: str,
    *,
    store: NewsStore | None = None,
) -> tuple[Article | None, str]:
    """Apply bookmark|skip|read. Returns (article, message)."""
    store = store or NewsStore()
    art = store.resolve(id_or_url)
    if not art:
        return None, f"未找到文章: {id_or_url}"
    act = (action or "").strip().lower()
    if act in ("bookmark", "star", "save"):
        store.set_status(art.id, "bookmarked")
        return store.get(art.id), f"已收藏 {art.id}"
    if act in ("skip", "mute", "not_interested"):
        store.set_status(art.id, "skipped")
        # Weak mute: first meaningful token from title
        token = ""
        for part in (art.title or "").replace("-", " ").split():
            if len(part) >= 2:
                token = part
                break
        if token:
            add_mute_keyword(token)
            return store.get(art.id), f"已跳过 {art.id}，并弱屏蔽关键词「{token}」"
        return store.get(art.id), f"已跳过 {art.id}"
    if act in ("read", "done", "deep_read"):
        store.set_status(art.id, "deep_read")
        return store.get(art.id), f"已标记已读 {art.id}"
    return art, f"未知动作 {action!r}；可用 bookmark|skip|read"
