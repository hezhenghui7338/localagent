"""Query decomposition for multi-hop / compound memory recall."""

from __future__ import annotations

import re
from typing import Iterable

from localagent import config

_SPLIT_RE = re.compile(
    r"\s+(?:and also|as well as|along with|in addition to)\s+"
    r"|\s+以及\s+|\s+还有\s+|\s+另外\s+",
    re.IGNORECASE,
)
_BOTH_AND_RE = re.compile(
    r"\bboth\s+(.+?)\s+and\s+(.+?)(?:[?.!]|$)",
    re.IGNORECASE | re.DOTALL,
)
_AND_SPLIT_RE = re.compile(r"\s+and\s+", re.IGNORECASE)
_MULTI_Q_RE = re.compile(r"[?？]")
_WH_RE = re.compile(
    r"\b(?:what|when|where|who|whom|which|why|how|whose)\b",
    re.IGNORECASE,
)
_CONTENT_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9']{2,}|[\u4e00-\u9fff]{2,}")
_STOP = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "what", "when", "where",
        "who", "whom", "which", "why", "how", "did", "does", "have", "has", "had",
        "was", "were", "are", "been", "being", "about", "into", "their", "they",
        "them", "your", "you", "her", "his", "she", "him", "our", "out", "not",
        "also", "than", "then", "both", "each", "some", "any", "all", "just",
        "does", "do", "of", "to", "in", "on", "at", "by", "or", "as", "is",
        "caroline", "melanie", "mel", "know", "remember", "tell", "please",
        "什么", "怎么", "怎样", "哪些", "哪个", "为什么", "是否", "有没有",
        "知道", "记得", "告诉", "请问", "时候", "哪里", "哪儿", "多少",
    }
)


def _clean(text: str) -> str:
    return " ".join((text or "").split()).strip(" ,;，；")


def _uniq(items: Iterable[str], *, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        cleaned = _clean(item)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= limit:
            break
    return out


def _content_tokens(text: str) -> list[str]:
    tokens = []
    for tok in _CONTENT_TOKEN_RE.findall(text or ""):
        lower = tok.lower()
        if lower in _STOP or tok in _STOP:
            continue
        tokens.append(tok)
    return tokens


def _looks_compound(query: str) -> bool:
    q = query or ""
    if _BOTH_AND_RE.search(q):
        return True
    if _SPLIT_RE.search(q):
        return True
    if len(_MULTI_Q_RE.findall(q)) >= 2:
        return True
    # Multiple WH words often signal multi-hop LoCoMo questions.
    if len(_WH_RE.findall(q)) >= 2:
        return True
    # Long questions with many content tokens.
    tokens = _content_tokens(q)
    if len(tokens) >= 8 and (" and " in q.lower() or "和" in q or "以及" in q):
        return True
    return False


def _split_parts(query: str) -> list[str]:
    both = _BOTH_AND_RE.search(query)
    if both:
        return [_clean(both.group(1)), _clean(both.group(2))]

    parts = [_clean(p) for p in _SPLIT_RE.split(query) if _clean(p)]
    if len(parts) >= 2:
        return parts

    # Multiple sentences/questions.
    q_parts = [_clean(p) for p in re.split(r"[?？]+", query) if _clean(p)]
    if len(q_parts) >= 2:
        return [f"{p}?" if not p.endswith(("?", "？")) else p for p in q_parts]

    # Conservative "X and Y" split when both sides have content tokens.
    if " and " in query.lower():
        chunks = [_clean(p) for p in _AND_SPLIT_RE.split(query) if _clean(p)]
        if len(chunks) == 2:
            left_n = len(_content_tokens(chunks[0]))
            right_n = len(_content_tokens(chunks[1]))
            if left_n >= 2 and right_n >= 2:
                return chunks
    return [query]


def _token_focus_queries(query: str, *, max_sub: int) -> list[str]:
    """Build short focus queries from content token windows for long compounds."""
    tokens = _content_tokens(query)
    if len(tokens) < 6:
        return []
    window = max(3, min(5, len(tokens) // 2))
    focuses: list[str] = []
    step = max(2, window - 1)
    for start in range(0, len(tokens), step):
        chunk = tokens[start : start + window]
        if len(chunk) < 3:
            continue
        focuses.append(" ".join(chunk))
        if len(focuses) >= max_sub - 1:
            break
    return focuses


def decompose_recall_query(query: str, *, max_subqueries: int | None = None) -> list[str]:
    """Return original query plus optional sub-queries for multi-path recall.

    Always includes the original query first. Decomposition is rule-based and
    conservative — only fires on compound / multi-hop-looking questions.
    """
    raw = _clean(query)
    if not raw:
        return []
    limit = max_subqueries if max_subqueries is not None else config.MEMORY_RECALL_DECOMPOSE_MAX
    limit = max(1, limit)
    if not config.MEMORY_RECALL_DECOMPOSE or not _looks_compound(raw):
        return [raw]

    parts = _split_parts(raw)
    focuses = _token_focus_queries(raw, max_sub=limit)
    return _uniq([raw, *parts, *focuses], limit=limit)
