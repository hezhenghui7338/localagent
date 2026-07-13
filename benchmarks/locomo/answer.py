"""Answer LoCoMo questions via LocalAgent memory recall (+ optional LLM)."""

from __future__ import annotations

from typing import Any, Literal

AnswerMode = Literal["recall", "recall_generate", "reflect"]

QA_PROMPT = """You are scoring a long-term memory QA benchmark.
Use ONLY the retrieved memories below. Reply with a SHORT phrase answer (a few words).
Copy exact words from the memories whenever possible.
When asked WHEN something happened, prefer the absolute calendar date from memory metadata
(e.g. "7 May 2023" or "June 2023") over relative words like "yesterday".
Only reply exactly "No information available" if NONE of the memories contain any supporting fact.
Do not refuse when a supporting detail is present, even if partial.
Do not explain. Do not use markdown. Do not mention tools or files.

Memories:
{context}

Question: {question}
Short answer:"""


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


def recall_context(question: str, *, top_k: int = 5) -> list[dict[str, Any]]:
    from localagent.memory.backend import get_memory_backend

    return get_memory_backend().recall(question, max_results=top_k)


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
    router = get_model_router()
    prefer = None if not provider or provider == "auto" else provider
    text = router.chat(
        [ChatMessage(role="user", content=prompt)],
        temperature=0.0,
        prefer=prefer,
        usage_command="locomo_qa",
    ).strip()
    return text, router.last_provider, router.last_model


def answer_question(
    question: str,
    *,
    category: int,
    mode: AnswerMode = "recall_generate",
    top_k: int = 5,
    provider: str | None = None,
) -> dict[str, Any]:
    """Answer one LoCoMo QA item using LocalAgent memory."""
    hits = recall_context(question, top_k=top_k)
    context = _format_hits(hits)
    retrieved_ids = [str(h.get("id") or "") for h in hits]
    dia_ids = []
    for hit in hits:
        meta = hit.get("metadata") or {}
        if meta.get("dia_id"):
            dia_ids.append(str(meta["dia_id"]))

    if mode == "recall":
        prediction = " ".join(str(h.get("text") or "") for h in hits[:3]).strip()
        return {
            "prediction": prediction or "No information available",
            "context": context,
            "retrieved_ids": retrieved_ids,
            "retrieved_dia_ids": dia_ids,
            "mode": mode,
            "provider": None,
            "model": None,
        }

    if mode == "reflect":
        from localagent.tools import reflect_memory

        prediction = reflect_memory(question).strip()
        return {
            "prediction": prediction or "No information available",
            "context": context,
            "retrieved_ids": retrieved_ids,
            "retrieved_dia_ids": dia_ids,
            "mode": mode,
            "provider": provider,
            "model": None,
        }

    # Default: recall + generate (LoCoMo RAG protocol)
    prediction, used_provider, used_model = generate_from_context(
        question,
        context,
        category=category,
        provider=provider,
    )
    return {
        "prediction": prediction or "No information available",
        "context": context,
        "retrieved_ids": retrieved_ids,
        "retrieved_dia_ids": dia_ids,
        "mode": mode,
        "provider": used_provider,
        "model": used_model,
    }
