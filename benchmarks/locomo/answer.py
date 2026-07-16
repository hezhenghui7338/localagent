"""Answer LoCoMo questions via LocalAgent memory recall (+ optional LLM)."""

from __future__ import annotations

import logging
import re
from typing import Any, Literal

AnswerMode = Literal["recall", "recall_generate", "reflect"]

logger = logging.getLogger(__name__)

QA_PROMPT = """You are scoring a long-term memory QA benchmark.
Use ONLY the retrieved memories below. Reply with a SHORT phrase answer (a few words).
Copy exact words from the memories whenever possible.
When asked WHEN something happened, prefer the absolute calendar date from memory metadata
fields like date=... / occurred_at / [session=... date=...] (e.g. "7 May 2023" or "13 August")
over relative words like "yesterday" or "last night".
For list / multi-hop questions, enumerate ALL supporting items found across memories
(comma-separated), not just the first match.
You MAY use short implicit inferences that are clearly supported
(e.g. "single parent" → "Single"; "home country, Sweden" → "Sweden").
Only reply exactly "No information available" if NONE of the memories contain any supporting fact.
Do not refuse when a supporting detail is present, even if partial.
Do not explain. Do not use markdown. Do not mention tools or files.

Memories:
{context}

Question: {question}
Short answer:"""

_ABSTAIN_RE = re.compile(
    r"no information available|not mentioned|i don't know|i do not know|"
    r"insufficient information|无法|不知道|没有相关信息|对话中未提及",
    re.IGNORECASE,
)
_DIA_ID_RE = re.compile(r"\b(D\d+:\d+)\b")


def _is_abstain(prediction: str) -> bool:
    text = (prediction or "").strip()
    if not text:
        return True
    return bool(_ABSTAIN_RE.search(text))


def _format_hits(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "(no memories recalled)"
    lines: list[str] = []
    for index, hit in enumerate(hits, start=1):
        text = str(hit.get("text") or "").strip()
        score = hit.get("score")
        prefix = f"[{index}]"
        if score is not None:
            try:
                prefix = f"[{index}|{float(score):.3f}]"
            except (TypeError, ValueError):
                pass
        lines.append(f"{prefix} {text}")
    return "\n".join(lines)


def _hit_dia_id(hit: dict[str, Any]) -> str:
    meta = hit.get("metadata") or {}
    dia = str(meta.get("dia_id") or "").strip()
    if dia:
        return dia
    text = str(hit.get("text") or "")
    match = _DIA_ID_RE.search(text)
    return match.group(1) if match else ""


def _hit_key(hit: dict[str, Any]) -> str:
    dia = _hit_dia_id(hit)
    if dia:
        return f"dia:{dia}"
    hid = str(hit.get("id") or "").strip()
    if hid:
        return f"id:{hid}"
    return f"text:{hash(str(hit.get('text') or ''))}"


def dedupe_hits(hits: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    """Keep highest-ranked unique dia_id (or id) hits, capped at top_k."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        key = _hit_key(hit)
        if key in seen:
            continue
        seen.add(key)
        enriched = dict(hit)
        dia = _hit_dia_id(hit)
        if dia:
            meta = dict(enriched.get("metadata") or {})
            meta.setdefault("dia_id", dia)
            enriched["metadata"] = meta
        out.append(enriched)
        if len(out) >= max(1, top_k):
            break
    return out


def _recall_cold(question: str, *, top_k: int) -> list[dict[str, Any]]:
    """Retrieve Cold conversation chunks (chat / chatgpt / locomo)."""
    try:
        from localagent import config
        from localagent.knowledge.hybrid import get_hybrid_retriever
    except Exception:
        return []
    if not getattr(config, "COLD_CONVERSATION", True):
        return []
    try:
        raw = get_hybrid_retriever().retrieve(
            question,
            top_k=max(1, top_k),
            conversation_only=True,
        )
    except Exception as exc:
        logger.debug("locomo cold recall failed: %s", exc)
        return []

    hits: list[dict[str, Any]] = []
    for item in raw:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        meta = dict(item.get("metadata") or {})
        dia = str(meta.get("dia_id") or "").strip()
        if not dia:
            match = _DIA_ID_RE.search(text)
            if match:
                dia = match.group(1)
                meta["dia_id"] = dia
        hits.append(
            {
                "id": str(item.get("chunk_id") or meta.get("chunk_id") or f"cold:{hash(text)}"),
                "text": text,
                "score": item.get("score_rrf"),
                "source": "cold",
                "metadata": meta,
            }
        )
    return hits


def _tag_warm_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hit in hits:
        enriched = dict(hit)
        enriched.setdefault("source", "warm")
        out.append(enriched)
    return out


def _prefer_dia_id(hits: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    """Prefer dialog turns that carry dia_id so evidence hit@k is not diluted."""
    with_dia = [h for h in hits if _hit_dia_id(h)]
    without = [h for h in hits if not _hit_dia_id(h)]
    return (with_dia + without)[: max(1, top_k)]


def _rrf_fuse(
    lists: list[list[dict[str, Any]]],
    *,
    top_k: int,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Bidirectional RRF across Warm/Cold lists, then dia_id-dedupe to top_k."""
    scores: dict[str, float] = {}
    best: dict[str, dict[str, Any]] = {}
    for hits in lists:
        for rank, hit in enumerate(hits, start=1):
            key = _hit_key(hit)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            prev = best.get(key)
            if prev is None:
                best[key] = dict(hit)
                continue
            try:
                prev_score = float(prev.get("score") or 0.0)
            except (TypeError, ValueError):
                prev_score = 0.0
            try:
                cur_score = float(hit.get("score") or 0.0)
            except (TypeError, ValueError):
                cur_score = 0.0
            prev_src = str(prev.get("source") or "")
            cur_src = str(hit.get("source") or "")
            if cur_score > prev_score:
                merged = dict(hit)
                if prev_src and cur_src and prev_src != cur_src:
                    merged["source"] = "warm+cold"
                best[key] = merged
            elif prev_src and cur_src and prev_src != cur_src:
                prev = dict(prev)
                prev["source"] = "warm+cold"
                best[key] = prev
    ranked_keys = sorted(scores.keys(), key=lambda key: scores[key], reverse=True)
    fused = [dict(best[key], score=scores[key]) for key in ranked_keys]
    return _prefer_dia_id(dedupe_hits(fused, top_k=max(top_k, len(fused))), top_k=top_k)


def joint_recall(
    question: str,
    *,
    top_k: int = 8,
    mode: Literal["joint", "warm_only", "cold_only"] = "joint",
) -> list[dict[str, Any]]:
    """LTM recall: Warm∪Cold joint RRF (default), or single-layer diagnostics."""
    from localagent.memory.backend import get_memory_backend

    pool = max(top_k * 3, 24)
    if mode == "warm_only":
        return _prefer_dia_id(
            dedupe_hits(
                _tag_warm_hits(get_memory_backend().recall(question, max_results=pool)),
                top_k=pool,
            ),
            top_k=top_k,
        )
    if mode == "cold_only":
        return _prefer_dia_id(
            dedupe_hits(_recall_cold(question, top_k=pool), top_k=pool),
            top_k=top_k,
        )

    warm = _tag_warm_hits(get_memory_backend().recall(question, max_results=pool))
    cold = _recall_cold(question, top_k=pool)
    return _rrf_fuse([warm, cold], top_k=top_k)


def recall_context(question: str, *, top_k: int = 8) -> list[dict[str, Any]]:
    """Warm∪Cold joint recall (alias of ``joint_recall`` for the answer path)."""
    return joint_recall(question, top_k=top_k, mode="joint")


def _expand_with_followups(
    question: str,
    hits: list[dict[str, Any]],
    *,
    top_k: int,
    max_rounds: int = 2,
) -> list[dict[str, Any]]:
    """Merge extra recalls from reflect-style follow-up subqueries."""
    from localagent.memory.decompose import decompose_recall_query
    from localagent.memory.reflect_loop import decide_followups

    merged = list(hits)
    pending: list[str] = []
    for round_i in range(max(0, max_rounds)):
        ready, followups = decide_followups(question, merged)
        if ready and round_i > 0:
            break
        if not followups:
            parts = decompose_recall_query(question)
            followups = [p for p in parts if p.strip().lower() != question.strip().lower()][:2]
        if not followups:
            break
        pending = [
            q
            for q in followups
            if q.strip().lower() != question.strip().lower()
        ]
        if not pending:
            break
        for sub in pending:
            extra = recall_context(sub, top_k=top_k)
            merged = dedupe_hits([*merged, *extra], top_k=max(top_k * 2, top_k + 4))
        if ready:
            break
    return dedupe_hits(merged, top_k=top_k)


def generate_from_context(
    question: str,
    context: str,
    *,
    category: int,
    provider: str | None = None,
) -> tuple[str, str | None, str | None]:
    from localagent.models.router import ChatMessage, get_model_router

    prompt = QA_PROMPT.format(context=context, question=question)
    if int(category) == 5:
        prompt += (
            "\nThis may be an unanswerable / adversarial question. "
            "Prefer 'No information available' unless the memories clearly support an answer."
        )
    elif int(category) == 1:
        prompt += (
            "\nThis is a multi-hop question: combine facts from multiple memories "
            "and list every matching item."
        )
    router = get_model_router()
    prefer = None if not provider or provider == "auto" else provider
    text = router.chat(
        [ChatMessage(role="user", content=prompt)],
        temperature=0.0,
        prefer=prefer,
        usage_command="locomo_qa",
    ).strip()
    return text, router.last_provider, router.last_model


def _pack_result(
    *,
    prediction: str,
    hits: list[dict[str, Any]],
    mode: AnswerMode,
    provider: str | None,
    model: str | None,
) -> dict[str, Any]:
    context = _format_hits(hits)
    retrieved_ids = [str(h.get("id") or "") for h in hits]
    dia_ids = [_hit_dia_id(h) for h in hits if _hit_dia_id(h)]
    return {
        "prediction": prediction or "No information available",
        "context": context,
        "retrieved_ids": retrieved_ids,
        "retrieved_dia_ids": dia_ids,
        "mode": mode,
        "provider": provider,
        "model": model,
    }


def answer_question(
    question: str,
    *,
    category: int,
    mode: AnswerMode = "recall_generate",
    top_k: int = 8,
    provider: str | None = None,
) -> dict[str, Any]:
    """Answer one LoCoMo QA item using LocalAgent memory."""
    hits = recall_context(question, top_k=top_k)

    if mode == "recall":
        prediction = " ".join(str(h.get("text") or "") for h in hits[:3]).strip()
        return _pack_result(
            prediction=prediction or "No information available",
            hits=hits,
            mode=mode,
            provider=None,
            model=None,
        )

    if mode == "reflect":
        from localagent.tools import reflect_memory

        prediction = reflect_memory(question).strip()
        return _pack_result(
            prediction=prediction or "No information available",
            hits=hits,
            mode=mode,
            provider=provider,
            model=None,
        )

    # Proactive multi-hop expansion before first answer.
    if int(category) == 1:
        hits = _expand_with_followups(question, hits, top_k=top_k, max_rounds=1)

    prediction, used_provider, used_model = generate_from_context(
        question,
        _format_hits(hits),
        category=category,
        provider=provider,
    )

    # Abstain → re-recall with follow-ups, then answer again (skip adversarial).
    if int(category) != 5 and _is_abstain(prediction):
        hits = _expand_with_followups(question, hits, top_k=top_k, max_rounds=2)
        prediction, used_provider, used_model = generate_from_context(
            question,
            _format_hits(hits),
            category=category,
            provider=provider,
        )

    return _pack_result(
        prediction=prediction or "No information available",
        hits=hits,
        mode=mode,
        provider=used_provider,
        model=used_model,
    )
