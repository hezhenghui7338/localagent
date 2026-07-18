"""Fetch article HTML and extract main text (multi-strategy + quality gate)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

from localagent import config
from localagent.ingest.loader import LoadedDoc

_USER_AGENT = (
    "Mozilla/5.0 (compatible; LocalAgent-news/1.0; "
    "+https://github.com/hezhenghui7338/localagent)"
)
_HREF_RE = re.compile(
    r"""href\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_ORIGIN_HINT_RE = re.compile(
    r"(?:阅读(?:完整)?(?:文章|原文)|查看原文|原文链接|原文地址|original\s*(?:article|link)|source\s*url)",
    re.IGNORECASE,
)
_ABS_URL_RE = re.compile(
    r"https?://[^\s<>\"']+",
    re.IGNORECASE,
)
# BestBlogs / aggregator hosts — prefer real publisher URLs when available.
_AGGREGATOR_HOSTS = frozenset(
    {
        "bestblogs.dev",
        "www.bestblogs.dev",
    }
)
# Common non-article hosts that appear in page chrome / JSON-LD.
_BLOCKED_ORIGIN_HOSTS = frozenset(
    {
        "schema.org",
        "www.schema.org",
        "w3.org",
        "www.w3.org",
        "purl.org",
        "creativecommons.org",
        "www.creativecommons.org",
        "github.com",
        "www.github.com",
        "twitter.com",
        "x.com",
        "facebook.com",
        "www.facebook.com",
        "linkedin.com",
        "www.linkedin.com",
        "youtube.com",
        "www.youtube.com",
        "google.com",
        "www.google.com",
        "fonts.googleapis.com",
        "cdn.jsdelivr.net",
    }
)


@dataclass
class FetchResult:
    url: str
    title: str
    text: str
    error: str = ""
    strategy: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.text) and not self.error


def body_quality_ok(
    text: str,
    *,
    expected_word_count: int | None = None,
    min_chars: int | None = None,
) -> bool:
    """True when extracted body looks like a real article, not a teaser stub."""
    body = (text or "").strip()
    floor = min_chars if min_chars is not None else config.NEWS_FETCH_MIN_CHARS
    if len(body) < floor:
        return False
    if expected_word_count and expected_word_count > 0:
        # Reject if we got less than ~30% of the advertised length.
        if len(body) < max(floor, int(expected_word_count * 0.3)):
            return False
    return True


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _is_aggregator(url: str) -> bool:
    host = _host(url)
    return host in _AGGREGATOR_HOSTS or host.endswith(".bestblogs.dev")


def _same_site(a: str, b: str) -> bool:
    ha, hb = _host(a), _host(b)
    if not ha or not hb:
        return False
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


def extract_origin_urls(html: str, *, page_url: str = "") -> list[str]:
    """Find likely publisher / original article URLs in aggregator HTML."""
    raw = html or ""
    hinted: list[str] = []
    others: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str, *, hinted_link: bool) -> None:
        href = (candidate or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            return
        abs_url = urljoin(page_url or "https://example.invalid/", href)
        if not abs_url.startswith(("http://", "https://")):
            return
        if page_url and _same_site(abs_url, page_url):
            return
        if _is_aggregator(abs_url):
            return
        host = _host(abs_url)
        if host in _BLOCKED_ORIGIN_HOSTS or any(
            host.endswith("." + blocked) for blocked in _BLOCKED_ORIGIN_HOSTS
        ):
            return
        parsed = urlparse(abs_url)
        path = (parsed.path or "").lower()
        if path.endswith(
            (".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".json")
        ):
            return
        # Require a real article-ish path (not bare domain root).
        path_parts = [p for p in path.split("/") if p]
        if len(path_parts) < 1 and not hinted_link:
            return
        if not path_parts:
            return
        key = abs_url.split("#", 1)[0].rstrip("/")
        if key in seen:
            return
        seen.add(key)
        if hinted_link:
            hinted.append(abs_url)
        else:
            others.append(abs_url)

    # Prefer anchors whose nearby text hints at "original article".
    for m in _HREF_RE.finditer(raw):
        start = max(0, m.start() - 160)
        end = min(len(raw), m.end() + 160)
        window = raw[start:end]
        if _ORIGIN_HINT_RE.search(window):
            _add(m.group(1), hinted_link=True)

    # Only take a small number of other external links if no hints found.
    if not hinted:
        for m in _HREF_RE.finditer(raw):
            if len(others) >= 3:
                break
            _add(m.group(1), hinted_link=False)

    return hinted + others


def _download_html(url: str, *, timeout: float) -> tuple[str, str]:
    """Return (final_url, html). Raises on HTTP failure."""
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return str(resp.url), resp.text


def _extract_with_trafilatura(html: str, *, url: str) -> tuple[str, str]:
    """Return (title, text)."""
    import trafilatura

    extracted = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
        url=url,
    )
    title = ""
    meta = trafilatura.extract_metadata(html)
    if meta and meta.title:
        title = meta.title
    return title, (extracted or "").strip()


def _fetch_direct(url: str, *, timeout: float) -> FetchResult:
    href = (url or "").strip()
    if not href:
        return FetchResult(url="", title="", text="", error="空 URL", strategy="direct")
    try:
        final_url, html = _download_html(href, timeout=timeout)
    except Exception as exc:
        return FetchResult(
            url=href, title="", text="", error=f"下载失败: {exc}", strategy="direct"
        )
    try:
        title, text = _extract_with_trafilatura(html, url=final_url or href)
    except Exception as exc:
        return FetchResult(
            url=href,
            title="",
            text="",
            error=f"正文抽取失败: {exc}",
            strategy="direct",
        )
    if not text:
        return FetchResult(
            url=href, title=title, text="", error="未能抽取正文", strategy="direct"
        )
    return FetchResult(url=final_url or href, title=title, text=text, strategy="direct")


def _fetch_jina(url: str, *, timeout: float) -> FetchResult:
    href = (url or "").strip()
    if not href:
        return FetchResult(url="", title="", text="", error="空 URL", strategy="jina")
    reader = f"https://r.jina.ai/{href}"
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/plain,text/markdown,*/*",
        "X-Return-Format": "markdown",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(reader, headers=headers)
            resp.raise_for_status()
            text = (resp.text or "").strip()
    except Exception as exc:
        return FetchResult(
            url=href, title="", text="", error=f"Jina Reader 失败: {exc}", strategy="jina"
        )
    if not text:
        return FetchResult(
            url=href, title="", text="", error="Jina Reader 返回空", strategy="jina"
        )
    title = ""
    for line in text.splitlines()[:20]:
        s = line.strip()
        if s.startswith("# "):
            title = s[2:].strip()
            break
        if s.startswith("Title:"):
            title = s[6:].strip()
            break
    return FetchResult(url=href, title=title, text=text, strategy="jina")


def fetch_article(
    url: str,
    *,
    timeout: float = 45.0,
    expected_word_count: int | None = None,
    origin_hints: list[str] | None = None,
) -> FetchResult:
    """Download URL and extract readable text via multi-strategy fallbacks.

    Order: direct trafilatura → origin URLs from page/hints → Jina Reader.
    Rejects stub-length bodies via ``body_quality_ok``.
    """
    href = (url or "").strip()
    if not href:
        return FetchResult(url="", title="", text="", error="空 URL")

    attempts: list[str] = []
    best_stub: FetchResult | None = None
    page_html = ""
    page_final = href

    # --- Strategy A: direct ---
    try:
        page_final, page_html = _download_html(href, timeout=timeout)
        title, text = _extract_with_trafilatura(page_html, url=page_final or href)
        direct = FetchResult(
            url=page_final or href, title=title, text=text, strategy="direct"
        )
        if text and body_quality_ok(text, expected_word_count=expected_word_count):
            return direct
        if text:
            best_stub = direct
            attempts.append(f"direct: stub ({len(text)} chars)")
        else:
            attempts.append("direct: empty")
    except Exception as exc:
        attempts.append(f"direct: {exc}")
        # Fall back to full _fetch_direct for consistent error surfaces
        direct = _fetch_direct(href, timeout=timeout)
        if direct.ok and body_quality_ok(direct.text, expected_word_count=expected_word_count):
            return direct
        if direct.ok:
            best_stub = direct
        elif direct.error:
            attempts.append(direct.error)

    # --- Collect origin candidates (hinted links only when possible) ---
    origins: list[str] = []
    seen: set[str] = set()

    def _push(u: str) -> None:
        key = (u or "").strip().split("#", 1)[0].rstrip("/")
        if not key or key in seen:
            return
        if key.rstrip("/") == href.rstrip("/"):
            return
        seen.add(key)
        origins.append(u.strip())

    for hint in origin_hints or []:
        if hint.startswith(("http://", "https://")):
            _push(hint)
    if page_html:
        for cand in extract_origin_urls(page_html, page_url=page_final or href):
            _push(cand)

    # --- Strategy B: Jina Reader on the page itself (before speculative origins) ---
    if config.NEWS_FETCH_USE_JINA:
        result = _fetch_jina(href, timeout=timeout)
        if result.ok and body_quality_ok(result.text, expected_word_count=expected_word_count):
            result.warnings.append(f"已通过 Jina Reader 获取: {href}")
            return result
        if result.ok:
            if best_stub is None or len(result.text) > len(best_stub.text):
                best_stub = result
            attempts.append(f"jina {href}: stub ({len(result.text)} chars)")
        else:
            attempts.append(f"jina {href}: {result.error or 'fail'}")

    # --- Strategy C: origin publisher pages ---
    stub_len = len(best_stub.text) if best_stub else 0
    for origin in origins[:5]:
        result = _fetch_direct(origin, timeout=timeout)
        result.strategy = "origin"
        if (
            result.ok
            and body_quality_ok(result.text, expected_word_count=expected_word_count)
            and len(result.text) > max(stub_len * 2, config.NEWS_FETCH_MIN_CHARS)
        ):
            result.warnings.append(f"已改用原文站: {origin}")
            return result
        if result.ok:
            if best_stub is None or len(result.text) > len(best_stub.text):
                best_stub = result
            attempts.append(f"origin {origin}: stub ({len(result.text)} chars)")
        else:
            attempts.append(f"origin {origin}: {result.error or 'fail'}")

    # --- Strategy D: Jina on origin candidates ---
    if config.NEWS_FETCH_USE_JINA:
        for target in origins[:2]:
            result = _fetch_jina(target, timeout=timeout)
            if result.ok and body_quality_ok(
                result.text, expected_word_count=expected_word_count
            ):
                result.warnings.append(f"已通过 Jina Reader 获取: {target}")
                return result
            if result.ok:
                if best_stub is None or len(result.text) > len(best_stub.text):
                    best_stub = result
                attempts.append(f"jina {target}: stub ({len(result.text)} chars)")
            else:
                attempts.append(f"jina {target}: {result.error or 'fail'}")

    detail = "；".join(attempts[:6]) if attempts else "未知原因"
    if best_stub and best_stub.text:
        # Return stub marked as error so callers can decide to refetch / fallback.
        return FetchResult(
            url=best_stub.url or href,
            title=best_stub.title,
            text=best_stub.text,
            error=f"正文过短（质量门控未通过）: {detail}",
            strategy=best_stub.strategy or "stub",
            warnings=list(best_stub.warnings),
        )
    return FetchResult(
        url=href,
        title="",
        text="",
        error=f"未能抽取合格正文: {detail}",
        strategy="failed",
    )


def to_loaded_doc(result: FetchResult, *, fallback_title: str = "") -> LoadedDoc:
    name = (result.title or fallback_title or "article").strip() or "article"
    safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:80]
    filename = f"{safe_name}.md"
    body = f"# {name}\n\n来源: {result.url}\n\n{result.text}"
    return LoadedDoc(
        text=body,
        source=result.url,
        filename=filename,
        metadata={"suffix": ".md", "url": result.url},
    )
