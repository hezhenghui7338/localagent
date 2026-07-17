"""Fetch article HTML and extract main text."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from localagent.ingest.loader import LoadedDoc


@dataclass
class FetchResult:
    url: str
    title: str
    text: str
    error: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.text) and not self.error


def fetch_article(url: str, *, timeout: float = 45.0) -> FetchResult:
    """Download URL and extract readable text via trafilatura."""
    href = (url or "").strip()
    if not href:
        return FetchResult(url="", title="", text="", error="空 URL")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; LocalAgent-news/1.0; "
            "+https://github.com/hezhenghui7338/localagent)"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(href, headers=headers)
            resp.raise_for_status()
            html = resp.text
    except Exception as exc:
        return FetchResult(url=href, title="", text="", error=f"下载失败: {exc}")

    title = ""
    text = ""
    try:
        import trafilatura

        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
            url=href,
        )
        meta = trafilatura.extract_metadata(html)
        if meta and meta.title:
            title = meta.title
        text = (extracted or "").strip()
    except Exception as exc:
        return FetchResult(url=href, title="", text="", error=f"正文抽取失败: {exc}")

    if not text:
        return FetchResult(url=href, title=title, text="", error="未能抽取正文")
    return FetchResult(url=href, title=title, text=text)


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
