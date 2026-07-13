"""LoCoMo QA metrics (aligned with snap-research/locomo task_eval/evaluation.py)."""

from __future__ import annotations

import re
import string
import unicodedata
from collections import Counter, defaultdict
from typing import Any

try:
    from nltk.stem import PorterStemmer

    _STEMMER = PorterStemmer()
except Exception:  # pragma: no cover - optional dependency
    _STEMMER = None

# Official LoCoMo category labels (see paper + evaluation.py scoring branches).
CATEGORY_NAMES: dict[int, str] = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
    5: "adversarial",
}


def _stem(word: str) -> str:
    if _STEMMER is None:
        return word
    return _STEMMER.stem(word)


def normalize_answer(text: str) -> str:
    """Normalize answers the same way LoCoMo evaluation does."""
    text = text.replace(",", "")

    def remove_articles(value: str) -> str:
        return re.sub(r"\b(a|an|the|and)\b", " ", value)

    def white_space_fix(value: str) -> str:
        return " ".join(value.split())

    def remove_punc(value: str) -> str:
        exclude = set(string.punctuation)
        return "".join(ch for ch in value if ch not in exclude)

    return white_space_fix(remove_articles(remove_punc(text.lower())))


def f1_score(prediction: str, ground_truth: str) -> float:
    prediction_tokens = [_stem(w) for w in normalize_answer(prediction).split()]
    ground_truth_tokens = [_stem(w) for w in normalize_answer(ground_truth).split()]
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = 1.0 * num_same / len(prediction_tokens)
    recall = 1.0 * num_same / len(ground_truth_tokens)
    return (2 * precision * recall) / (precision + recall)


def multi_answer_f1(prediction: str, ground_truth: str) -> float:
    """Category-1 multi-hop F1: split comma-separated sub-answers."""
    predictions = [p.strip() for p in prediction.split(",") if p.strip()]
    ground_truths = [g.strip() for g in ground_truth.split(",") if g.strip()]
    if not predictions or not ground_truths:
        return 0.0
    return float(
        sum(
            max(f1_score(pred, gt) for pred in predictions)
            for gt in ground_truths
        )
        / len(ground_truths)
    )


def exact_match_score(prediction: str, ground_truth: str) -> float:
    prediction_n = normalize_answer(prediction)
    ground_truth_n = normalize_answer(ground_truth)
    return float(set(prediction_n.split()) == set(ground_truth_n.split()))


def _is_abstain(prediction: str) -> bool:
    lowered = prediction.lower()
    return (
        "no information available" in lowered
        or "not mentioned" in lowered
        or "i don't know" in lowered
        or "i do not know" in lowered
        or "无法从对话中得知" in prediction
        or "对话中未提及" in prediction
        or "没有相关信息" in prediction
    )


def score_qa_item(*, category: int, prediction: str, answer: Any) -> float:
    """Score one QA item with official LoCoMo category rules."""
    cat = int(category)
    output = str(prediction or "")
    gold = "" if answer is None else str(answer)

    if cat == 3 and gold:
        gold = gold.split(";")[0].strip()

    if cat in (2, 3, 4):
        return f1_score(output, gold)
    if cat == 1:
        return multi_answer_f1(output, gold)
    if cat == 5:
        return 1.0 if _is_abstain(output) else 0.0
    raise ValueError(f"Unknown LoCoMo category: {category}")


def summarize_scores(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-category and overall F1."""
    by_cat: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        by_cat[int(row["category"])].append(float(row["f1"]))

    categories: dict[str, Any] = {}
    total_sum = 0.0
    total_n = 0
    for cat in sorted(by_cat):
        scores = by_cat[cat]
        mean = sum(scores) / len(scores) if scores else 0.0
        categories[str(cat)] = {
            "name": CATEGORY_NAMES.get(cat, f"cat-{cat}"),
            "n": len(scores),
            "f1": round(mean, 4),
        }
        total_sum += sum(scores)
        total_n += len(scores)

    return {
        "n": total_n,
        "overall_f1": round(total_sum / total_n, 4) if total_n else 0.0,
        "categories": categories,
    }


def has_answer_span(answers: list[str], text: str) -> bool:
    """Check whether any gold answer string appears in recalled text (retrieval hit)."""
    normalized_text = unicodedata.normalize("NFD", text).lower()
    for answer in answers:
        normalized = unicodedata.normalize("NFD", str(answer)).lower().strip()
        if normalized and normalized in normalized_text:
            return True
    return False
