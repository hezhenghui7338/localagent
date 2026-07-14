"""Derive entities and relations from a MemoryFact for the local graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GraphPayload:
    entities: list[tuple[str, str]] = field(default_factory=list)  # (name, type)
    relations: list[tuple[str, str, str, float]] = field(default_factory=list)
    # (src, predicate, dst, confidence)


_PERSON_HINTS = frozenset({"用户", "user", "me", "i", "本人"})
_PLACE_HINTS = frozenset({"location", "place", "city", "地点", "城市", "住址"})


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


def extract_graph_payload(fact: Any) -> GraphPayload:
    """Build graph nodes/edges from fact text + metadata (slots/entities)."""
    meta = dict(getattr(fact, "metadata", None) or {})
    text = _clean(getattr(fact, "text", "") or "")
    payload = GraphPayload()
    seen_entities: set[str] = set()

    def add_entity(name: str, *, entity_type: str = "concept") -> str | None:
        cleaned = _clean(name)
        if not cleaned or len(cleaned) < 2:
            return None
        key = cleaned.casefold()
        if key in seen_entities:
            return cleaned
        seen_entities.add(key)
        payload.entities.append((cleaned, entity_type))
        return cleaned

    slots = meta.get("slots") or {}
    if isinstance(slots, dict):
        subject = add_entity(slots.get("subject", ""), entity_type=_guess_type(str(slots.get("subject") or ""), slot_key="subject"))
        obj = add_entity(slots.get("object", ""), entity_type=_guess_type(str(slots.get("object") or ""), slot_key="object"))
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
            pred = action or "related_to"
            payload.relations.append((subject, pred, obj, 0.95))
        if subject and location:
            payload.relations.append((subject, "located_in", location, 0.9))
        if subject and outcome and outcome != obj:
            payload.relations.append((subject, action or "results_in", outcome, 0.75))

    entities = meta.get("entities") or []
    if isinstance(entities, list):
        names: list[str] = []
        for item in entities:
            name = add_entity(item)
            if name:
                names.append(name)
        # Weak co-mention edges among consecutive entities (cap to avoid dense cliques).
        for index in range(min(len(names) - 1, 5)):
            payload.relations.append((names[index], "CO_MENTIONS", names[index + 1], 0.45))

    if text and not payload.entities:
        # Last resort: pull entities from text via existing extractor.
        from localagent.memory.entities import extract_entities

        for name in extract_entities(text, limit=8):
            add_entity(name)

    return payload
