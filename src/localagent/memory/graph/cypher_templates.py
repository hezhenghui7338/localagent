"""Parameterized Cypher templates for precise memory-graph questions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from localagent import config

ParamBuilder = Callable[[str, list[str]], dict[str, Any] | None]


@dataclass(frozen=True)
class CypherTemplate:
    id: str
    kind: str  # count | collect | path | co_mention
    description: str
    cypher: str
    build_params: ParamBuilder


_PLACE_HINT = re.compile(
    r"城市|地点|地方|住在|哪[里儿]|where|city|cities|place|location|住哪",
    re.IGNORECASE,
)
_PERSON_HINT = re.compile(
    r"谁|哪[些个]?人|who|person|people|朋友|friend",
    re.IGNORECASE,
)
_COUNT_PRED = re.compile(
    r"(?:提到|聊到|谈到|说过|提到过|去过|visited|mentioned|talked|met|adopted|"
    r"喜欢|去了|旅行|travel)",
    re.IGNORECASE,
)


def _min_conf() -> float:
    return float(getattr(config, "NEO4J_MIN_CONFIDENCE", 0.5) or 0.5)


def _params_entity(query: str, entities: list[str]) -> dict[str, Any] | None:
    if not entities:
        return None
    return {
        "__template": "count_facts_mentioning",
        "name": entities[0],
        "min_confidence": _min_conf(),
    }


def _params_rel_count(query: str, entities: list[str]) -> dict[str, Any] | None:
    if not entities:
        return None
    pred = ""
    match = _COUNT_PRED.search(query or "")
    if match:
        pred = match.group(0)
    return {
        "__template": "count_relations",
        "name": entities[0],
        "predicate": pred,
        "min_confidence": _min_conf(),
    }


def _params_collect(query: str, entities: list[str]) -> dict[str, Any] | None:
    if not entities:
        return None
    etype = ""
    if _PLACE_HINT.search(query or ""):
        etype = "place"
    elif _PERSON_HINT.search(query or ""):
        etype = "person"
    return {
        "__template": "collect_related",
        "name": entities[0],
        "entity_type": etype,
        "min_confidence": _min_conf(),
    }


def _params_path(query: str, entities: list[str]) -> dict[str, Any] | None:
    if not entities:
        return None
    etype = "place" if _PLACE_HINT.search(query or "") else ""
    if _PERSON_HINT.search(query or "") and not etype:
        etype = "person"
    return {
        "__template": "path_related",
        "name": entities[0],
        "entity_type": etype,
        "min_confidence": _min_conf(),
    }


def _params_co_mention(query: str, entities: list[str]) -> dict[str, Any] | None:
    if len(entities) < 2:
        return None
    return {
        "__template": "co_mention_count",
        "name": entities[0],
        "name2": entities[1],
        "min_confidence": _min_conf(),
    }


TEMPLATES: dict[str, CypherTemplate] = {
    "count_facts_mentioning": CypherTemplate(
        id="count_facts_mentioning",
        kind="count",
        description="Count distinct facts mentioning an entity",
        cypher="""
        MATCH (e:Entity)-[:MENTIONS]->(f:Fact)
        WHERE toLower(e.name) = toLower($name)
        RETURN count(DISTINCT f) AS value, collect(DISTINCT f.id) AS fact_ids
        """,
        build_params=_params_entity,
    ),
    "count_relations": CypherTemplate(
        id="count_relations",
        kind="count",
        description="Count RELATES edges involving an entity (optional predicate)",
        cypher="""
        MATCH (a:Entity)-[r:RELATES]->(b:Entity)
        WHERE r.confidence >= $min_confidence
          AND (toLower(a.name) = toLower($name) OR toLower(b.name) = toLower($name))
          AND ($predicate = '' OR toLower(r.predicate) CONTAINS toLower($predicate))
        RETURN count(DISTINCT r) AS value,
               collect(DISTINCT r.fact_id) AS fact_ids
        """,
        build_params=_params_rel_count,
    ),
    "collect_related": CypherTemplate(
        id="collect_related",
        kind="collect",
        description="Collect related entity names (optionally by type)",
        cypher="""
        MATCH (e:Entity)-[r:RELATES]-(other:Entity)
        WHERE toLower(e.name) = toLower($name)
          AND r.confidence >= $min_confidence
          AND ($entity_type = '' OR toLower(other.type) = toLower($entity_type))
          AND NOT other.name STARTS WITH 'turn:'
        RETURN collect(DISTINCT other.name) AS value,
               collect(DISTINCT r.fact_id) AS fact_ids
        """,
        build_params=_params_collect,
    ),
    "path_related": CypherTemplate(
        id="path_related",
        kind="path",
        description="1–2 hop related entities (multi-hop)",
        cypher="""
        MATCH (e:Entity)
        WHERE toLower(e.name) = toLower($name)
        MATCH (e)-[:RELATES|NEXT_TURN*1..2]-(other:Entity)
        WHERE ($entity_type = '' OR toLower(other.type) = toLower($entity_type))
          AND NOT other.name STARTS WITH 'turn:'
          AND toLower(other.name) <> toLower($name)
        RETURN collect(DISTINCT other.name) AS value,
               [] AS fact_ids
        """,
        build_params=_params_path,
    ),
    "co_mention_count": CypherTemplate(
        id="co_mention_count",
        kind="co_mention",
        description="Count facts that mention both entities",
        cypher="""
        MATCH (e1:Entity)-[:MENTIONS]->(f:Fact)<-[:MENTIONS]-(e2:Entity)
        WHERE toLower(e1.name) = toLower($name)
          AND toLower(e2.name) = toLower($name2)
          AND e1.id <> e2.id
        RETURN count(DISTINCT f) AS value, collect(DISTINCT f.id) AS fact_ids
        """,
        build_params=_params_co_mention,
    ),
}


def get_template(template_id: str) -> CypherTemplate | None:
    return TEMPLATES.get(template_id)
