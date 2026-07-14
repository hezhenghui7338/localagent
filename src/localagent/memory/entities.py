"""Lightweight entity extraction for memory write/recall soft boosts."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Iterable

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,8}|[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*|[A-Za-z]{3,}")
_QUOTED_RE = re.compile(r'"([^"]{2,60})"|“([^”]{2,60})”|\'([^\']{2,60})\'')
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_EN_STOP = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "what", "when", "where",
        "who", "whom", "which", "why", "how", "did", "does", "have", "has", "had",
        "was", "were", "are", "been", "being", "about", "into", "their", "they",
        "them", "your", "you", "her", "his", "she", "him", "our", "out", "not",
        "also", "than", "then", "both", "each", "some", "any", "all", "just",
        "visited", "gallery", "about", "said", "says", "went", "going", "like",
    }
)
_CJK_STOP = frozenset(
    {
        "什么", "怎么", "怎样", "哪些", "哪个", "为什么", "是否", "有没有",
        "知道", "记得", "告诉", "请问", "时候", "哪里", "哪儿", "多少",
        "用户", "自己", "我们", "他们", "她们", "这个", "那个", "一个",
    }
)


@lru_cache(maxsize=1)
def _spacy_nlp():
    try:
        import spacy

        return spacy.load("en_core_web_sm", disable=["parser", "lemmatizer", "textcat"])
    except Exception as exc:
        logger.debug("spaCy NER unavailable: %s", exc)
        return None


def _normalize_entity(text: str) -> str:
    return " ".join(text.strip().split())


def _heuristic_entities(text: str) -> list[str]:
    found: list[str] = []
    for match in _QUOTED_RE.finditer(text or ""):
        phrase = match.group(1) or match.group(2) or match.group(3) or ""
        cleaned = _normalize_entity(phrase)
        if cleaned:
            found.append(cleaned)
    for token in _TOKEN_RE.findall(text or ""):
        cleaned = _normalize_entity(token)
        if not cleaned:
            continue
        lower = cleaned.lower()
        if _CJK_RE.fullmatch(cleaned):
            if cleaned in _CJK_STOP or len(cleaned) < 2:
                continue
            found.append(cleaned)
            continue
        if lower in _EN_STOP or len(lower) < 3:
            continue
        # Prefer Title-Case / multi-word English names.
        if cleaned[0].isupper() or " " in cleaned:
            found.append(cleaned)
        elif len(cleaned) >= 5:
            found.append(cleaned)
    return found


def _spacy_entities(text: str) -> list[str]:
    nlp = _spacy_nlp()
    if nlp is None or not (text or "").strip():
        return []
    try:
        doc = nlp(text[:4000])
    except Exception:
        return []
    keep = {"PERSON", "ORG", "GPE", "LOC", "FAC", "EVENT", "PRODUCT", "WORK_OF_ART", "DATE", "NORP"}
    out: list[str] = []
    for ent in doc.ents:
        if ent.label_ not in keep:
            continue
        cleaned = _normalize_entity(ent.text)
        if cleaned and cleaned.lower() not in _EN_STOP:
            out.append(cleaned)
    return out


def extract_entities(text: str, *, limit: int = 12) -> list[str]:
    """Extract salient entities/phrases for metadata and recall boosts."""
    if not (text or "").strip():
        return []
    ordered: list[str] = []
    seen: set[str] = set()
    for item in (*_spacy_entities(text), *_heuristic_entities(text)):
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
        if len(ordered) >= limit:
            break
    return ordered


def entity_overlap_score(query_entities: Iterable[str], hit_entities: Iterable[str], hit_text: str) -> float:
    """Soft overlap in [0, 1] between query entities and hit entities/text."""
    q = [_normalize_entity(e) for e in query_entities if e and e.strip()]
    if not q:
        return 0.0
    hit_set = { _normalize_entity(e).lower() for e in hit_entities if e and str(e).strip() }
    haystack = (hit_text or "").lower()
    hits = 0
    for ent in q:
        key = ent.lower()
        if key in hit_set or (len(key) >= 2 and key in haystack):
            hits += 1
    return hits / len(q)
