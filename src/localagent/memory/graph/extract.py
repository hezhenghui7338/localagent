"""Derive entities and relations from a MemoryFact for the local graph."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GraphPayload:
    entities: list[tuple[str, str]] = field(default_factory=list)  # (name, type)
    relations: list[tuple[str, str, str, float]] = field(default_factory=list)
    # (src, predicate, dst, confidence)


_PERSON_HINTS = frozenset({"用户", "user", "me", "i", "本人"})
_PLACE_HINTS = frozenset({"location", "place", "city", "地点", "城市", "住址"})
_LOCOMO_PREFIX_RE = re.compile(r"^\[session=\d+[^\]]*\]\s*")
_SAID_RE = re.compile(
    r'^(?P<speaker>[A-Za-z][\w.-]*)\s+said,\s*"(?P<utterance>.*)"\s*(?:and shared.*)?$',
    re.DOTALL,
)


def _guess_type(name: str, *, slot_key: str = "") -> str:
    key = (slot_key or "").lower()
    lower = name.casefold()
    if key in ("subject",) or lower in _PERSON_HINTS:
        return "person"
    if key in ("location", "place") or key in _PLACE_HINTS:
        return "place"
    if key in ("time",):
        return "time"
    if key in ("object", "outcome"):
        return "concept"
    if name[:5] == "turn:":
        return "turn"
    return "concept"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def utterance_from_fact_text(text: str) -> str:
    """Strip LoCoMo/session wrappers so NER sees the spoken content."""
    raw = _clean(text)
    if not raw:
        return ""
    stripped = _LOCOMO_PREFIX_RE.sub("", raw).strip()
    match = _SAID_RE.match(stripped)
    if match:
        return _clean(match.group("utterance"))
    return stripped or raw


def extract_graph_payload(fact: Any) -> GraphPayload:
    """Build graph nodes/edges from fact text + metadata (slots/entities)."""
    meta = dict(getattr(fact, "metadata", None) or {})
    text = _clean(getattr(fact, "text", "") or "")
    payload = GraphPayload()
    seen_entities: set[str] = set()
    relation_keys: set[tuple[str, str, str]] = set()

    def add_entity(name: str, *, entity_type: str = "concept") -> str | None:
        cleaned = _clean(name)
        if not cleaned or len(cleaned) < 2:
            return None
        # Avoid treating full quoted utterances as entities.
        if len(cleaned) > 48:
            return None
        key = cleaned.casefold()
        if key in seen_entities:
            return cleaned
        seen_entities.add(key)
        payload.entities.append((cleaned, entity_type))
        return cleaned

    def add_relation(src: str, pred: str, dst: str, confidence: float) -> None:
        key = (src.casefold(), pred.casefold(), dst.casefold())
        if key in relation_keys or src.casefold() == dst.casefold():
            return
        relation_keys.add(key)
        payload.relations.append((src, pred, dst, confidence))

    slots = meta.get("slots") or {}
    if isinstance(slots, dict):
        subject = add_entity(
            slots.get("subject", ""),
            entity_type=_guess_type(str(slots.get("subject") or ""), slot_key="subject"),
        )
        obj = add_entity(
            slots.get("object", ""),
            entity_type=_guess_type(str(slots.get("object") or ""), slot_key="object"),
        )
        location = add_entity(
            slots.get("location", ""),
            entity_type=_guess_type(str(slots.get("location") or ""), slot_key="location"),
        )
        outcome = add_entity(
            slots.get("outcome", ""),
            entity_type=_guess_type(str(slots.get("outcome") or ""), slot_key="outcome"),
        )
        action = _clean(slots.get("action", ""))
        if subject and obj:
            add_relation(subject, action or "related_to", obj, 0.95)
        if subject and location:
            add_relation(subject, "located_in", location, 0.9)
        if subject and outcome and outcome != obj:
            add_relation(subject, action or "results_in", outcome, 0.75)

    entities = meta.get("entities") or []
    if isinstance(entities, list):
        for item in entities:
            add_entity(item)

    speaker = _clean(meta.get("speaker", ""))
    if speaker:
        add_entity(speaker, entity_type="person")

    # Supplement from spoken text (or full text) when metadata is thin.
    utterance = utterance_from_fact_text(text) if text else ""
    if utterance and len(payload.entities) < 6:
        from localagent.memory.entities import extract_entities

        for name in extract_entities(utterance, limit=8):
            add_entity(name)

    if text and not payload.entities:
        from localagent.memory.entities import extract_entities

        for name in extract_entities(utterance or text, limit=8):
            add_entity(name)

    names = [name for name, _ in payload.entities]
    for index in range(min(len(names) - 1, 5)):
        add_relation(names[index], "CO_MENTIONS", names[index + 1], 0.45)

    if speaker:
        for name, _etype in payload.entities:
            if name.casefold() != speaker.casefold():
                add_relation(speaker, "SAID_ABOUT", name, 0.8)
                break

    return payload
