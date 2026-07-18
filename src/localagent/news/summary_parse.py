"""Parse BestBlogs-style RSS summaries into one-liner / detail / viewpoints / meta."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


_SECTION_RE = re.compile(
    r"(?:^|\s)"
    r"(?:"
    r"📌\s*一句话摘要|📝\s*详细摘要|💡\s*主要观点|💬\s*文章金句|📊\s*文章信息"
    r"|一句话摘要|详细摘要|主要观点|文章金句|文章信息"
    r")"
    r"\s*",
)

_SECTION_KIND = {
    "📌一句话摘要": "one_liner",
    "一句话摘要": "one_liner",
    "📝详细摘要": "detail",
    "详细摘要": "detail",
    "💡主要观点": "viewpoints",
    "主要观点": "viewpoints",
    "💬文章金句": "quotes",
    "文章金句": "quotes",
    "📊文章信息": "meta",
    "文章信息": "meta",
}

_META_KEYS = (
    ("ai_score", re.compile(r"AI\s*初评[:：]\s*(\d{1,3})", re.I)),
    ("source", re.compile(r"来源[:：]\s*([^\s]+(?:\([^)]*\))?)")),
    ("author", re.compile(r"作者[:：]\s*([^\s]+)")),
    ("category", re.compile(r"分类[:：]\s*([^\s]+)")),
    ("language", re.compile(r"语言[:：]\s*([^\s]+)")),
    ("read_mins", re.compile(r"阅读时间[:：]\s*(\d+)\s*分钟")),
    ("word_count", re.compile(r"字数[:：]\s*(\d+)")),
)

_CLAIM_MAX_CHARS = 60
_NOTE_MIN_CHARS = 35


@dataclass
class ParsedRssSummary:
    one_liner: str = ""
    detail: str = ""
    viewpoints: list[str] = field(default_factory=list)
    viewpoint_notes: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)


def _normalize_section_key(raw: str) -> str:
    return re.sub(r"\s+", "", raw.strip())


def _split_sections(text: str) -> dict[str, str]:
    raw = (text or "").strip()
    if not raw:
        return {}
    matches = list(_SECTION_RE.finditer(raw))
    if not matches:
        return {}
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        key = _SECTION_KIND.get(_normalize_section_key(m.group(0)))
        if not key:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        body = raw[start:end].strip()
        body = re.sub(r"\s*阅读(?:完整文章|推文)\s*$", "", body).strip()
        if body:
            out[key] = body
    return out


def _sentences(text: str) -> list[str]:
    # Do not split on ； — BestBlogs elaborations often use it mid-sentence.
    parts = re.split(r"(?<=[。！？])\s*", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _ensure_punct(s: str) -> str:
    s = s.strip()
    if not s:
        return s
    if s.endswith(("。", "！", "？", ".", "!", "?")):
        return s
    return s + "。"


def _extract_viewpoints(text: str) -> tuple[list[str], list[str]]:
    """Pair a claim with the following longer elaboration when present."""
    sents = _sentences(text)
    claims: list[str] = []
    notes: list[str] = []
    i = 0
    while i < len(sents):
        s = sents[i]
        nxt = sents[i + 1] if i + 1 < len(sents) else ""
        if (
            nxt
            and len(nxt) > len(s)
            and len(nxt) >= _NOTE_MIN_CHARS
            and len(s) <= _CLAIM_MAX_CHARS
        ):
            claims.append(_ensure_punct(s))
            notes.append(nxt)
            i += 2
        else:
            claims.append(_ensure_punct(s))
            notes.append("")
            i += 1
    return claims, notes


def _extract_quotes(text: str) -> list[str]:
    return [_ensure_punct(s) for s in _sentences(text) if len(s.strip("。！？.!?")) >= 2]


def _parse_meta(text: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for key, pat in _META_KEYS:
        m = pat.search(text or "")
        if m:
            meta[key] = m.group(1).strip()
    return meta


def _fallback(text: str) -> ParsedRssSummary:
    raw = " ".join((text or "").split()).strip()
    if not raw:
        return ParsedRssSummary()
    sents = _sentences(raw)
    if not sents:
        one = raw[:120] + ("…" if len(raw) > 120 else "")
        return ParsedRssSummary(one_liner=one)
    one = sents[0]
    if len(one) > 120:
        one = one[:119] + "…"
    rest = sents[1:]
    detail = "".join(rest) if rest else ""
    # Prefer short sentences as viewpoints when no markers
    claims = [s if s.endswith(("。", "！", "？")) else s + "。" for s in rest if len(s) <= _CLAIM_MAX_CHARS][
        :5
    ]
    return ParsedRssSummary(one_liner=one, detail=detail, viewpoints=claims)


def parse_rss_summary(text: str) -> ParsedRssSummary:
    """Parse BestBlogs (or plain) RSS summary into structured parts."""
    sections = _split_sections(text)
    if not sections:
        return _fallback(text)

    one = sections.get("one_liner", "").strip()
    detail = sections.get("detail", "").strip()
    vp_raw = sections.get("viewpoints", "").strip()
    quotes_raw = sections.get("quotes", "").strip()
    meta_raw = sections.get("meta", "").strip()

    claims: list[str] = []
    notes: list[str] = []
    if vp_raw:
        claims, notes = _extract_viewpoints(vp_raw)

    if not one:
        return _fallback(detail or text)

    return ParsedRssSummary(
        one_liner=one,
        detail=detail,
        viewpoints=claims,
        viewpoint_notes=notes,
        quotes=_extract_quotes(quotes_raw) if quotes_raw else [],
        meta=_parse_meta(meta_raw),
    )


def viewpoints_to_skim_text(parsed: ParsedRssSummary) -> str:
    """Serialize viewpoints for Article.structured_skim storage."""
    lines: list[str] = []
    for i, claim in enumerate(parsed.viewpoints):
        lines.append(f"· {claim}")
        note = ""
        if i < len(parsed.viewpoint_notes):
            note = (parsed.viewpoint_notes[i] or "").strip()
        if note:
            lines.append(f"  {note}")
    return "\n".join(lines)
