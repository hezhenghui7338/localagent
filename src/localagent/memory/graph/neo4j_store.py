"""Neo4j-backed entity / relation store for precise Warm memory queries."""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Iterable

from localagent import config
from localagent.memory.graph.store import entity_id_for

logger = logging.getLogger(__name__)

_DIA_RE = re.compile(r"^D(\d+):(\d+)$", re.IGNORECASE)
_lock = threading.Lock()
_store: Neo4jMemoryStore | None = None

_SCHEMA_CYPHER = """
CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE;
CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (f:Fact) REQUIRE f.id IS UNIQUE;
CREATE INDEX entity_name IF NOT EXISTS FOR (e:Entity) ON (e.name);
"""


def neo4j_enabled() -> bool:
    return bool(getattr(config, "NEO4J", False))


def neo4j_available() -> bool:
    """True when Neo4j path can run (enabled + driver or in-memory URI)."""
    if not neo4j_enabled():
        return False
    uri = (getattr(config, "NEO4J_URI", "") or "").strip()
    if uri.startswith("memory://"):
        return True
    try:
        import neo4j  # noqa: F401
    except ImportError:
        return False
    return True


class _InMemoryDriver:
    """Minimal graph for tests / LA_NEO4J_URI=memory:// — no Bolt required."""

    def __init__(self) -> None:
        self.entities: dict[str, dict[str, str]] = {}
        self.facts: dict[str, dict[str, Any]] = {}
        self.mentions: set[tuple[str, str]] = set()
        self.relations: list[dict[str, Any]] = []

    def close(self) -> None:
        pass

    def clear(self) -> None:
        self.entities.clear()
        self.facts.clear()
        self.mentions.clear()
        self.relations.clear()

    def session(self, **_kwargs: Any) -> _InMemorySession:
        return _InMemorySession(self)


class _InMemorySession:
    def __init__(self, driver: _InMemoryDriver) -> None:
        self._d = driver

    def __enter__(self) -> _InMemorySession:
        return self

    def __exit__(self, *_exc: Any) -> None:
        pass

    def run(self, cypher: str, parameters: dict[str, Any] | None = None, **_kw: Any):
        params = dict(parameters or {})
        rows = self._d.execute(cypher, params)
        return _InMemoryResult(rows)

    def close(self) -> None:
        pass


class _InMemoryResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def data(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def single(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None


def _norm_name(name: str) -> str:
    return " ".join((name or "").strip().split())


def _inmemory_execute(self: _InMemoryDriver, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    text = " ".join((cypher or "").split())
    upper = text.upper()
    template = str(params.get("__template") or "")

    if "CREATE CONSTRAINT" in upper or "CREATE INDEX" in upper:
        return []
    if "DETACH DELETE" in upper:
        self.clear()
        return []

    # Writes from Neo4jMemoryStore helpers
    if "MERGE (E:ENTITY" in upper or (
        "MERGE (E:ENTITY" in upper.replace(" ", "")
    ) or ("MERGE (e:Entity" in text or "MERGE (e:Entity" in cypher):
        eid = str(params.get("id") or "")
        name = _norm_name(str(params.get("name") or ""))
        etype = str(params.get("type") or "concept")
        if eid and name:
            prev = self.entities.get(eid)
            if prev and prev.get("type") == "concept" and etype != "concept":
                pass
            elif prev and prev.get("type") != "concept" and etype == "concept":
                etype = prev["type"]
            elif prev:
                etype = prev.get("type") or etype
            self.entities[eid] = {"id": eid, "name": name, "type": etype}
        return []

    if "MERGE (f:Fact" in cypher or "MERGE (F:FACT" in upper:
        fid = str(params.get("id") or "")
        if fid:
            self.facts[fid] = {
                "id": fid,
                "text": str(params.get("text") or ""),
                "created_at": str(params.get("created_at") or ""),
                "source_file": str(params.get("source_file") or ""),
            }
        return []

    if "MENTIONS" in upper and "MERGE" in upper and ("$eid" in cypher or "eid" in params):
        eid = str(params.get("eid") or "")
        fid = str(params.get("fid") or "")
        if eid and fid:
            self.mentions.add((eid, fid))
        return []

    if "NEXT_TURN" in upper and "MERGE" in upper:
        src = str(params.get("src") or "")
        dst = str(params.get("dst") or "")
        if src and dst:
            self.relations.append(
                {
                    "src": src,
                    "predicate": "NEXT_TURN",
                    "dst": dst,
                    "fact_id": params.get("fact_id"),
                    "confidence": float(params.get("confidence") or 0.7),
                }
            )
        return []

    if "RELATES" in upper and "MERGE" in upper:
        src = str(params.get("src") or "")
        dst = str(params.get("dst") or "")
        pred = str(params.get("predicate") or "related_to")
        fid = params.get("fact_id")
        conf = float(params.get("confidence") or 1.0)
        if src and dst and src != dst:
            key = (src, pred, dst, str(fid or ""))
            self.relations = [
                r
                for r in self.relations
                if (r["src"], r["predicate"], r["dst"], str(r.get("fact_id") or "")) != key
            ]
            self.relations.append(
                {
                    "src": src,
                    "predicate": pred,
                    "dst": dst,
                    "fact_id": fid,
                    "confidence": conf,
                }
            )
        return []

    if "DELETE" in upper and ("FACT" in upper or "$id" in cypher):
        fid = str(params.get("id") or params.get("fact_id") or "")
        if fid:
            self.facts.pop(fid, None)
            self.mentions = {(e, f) for e, f in self.mentions if f != fid}
            self.relations = [r for r in self.relations if str(r.get("fact_id") or "") != fid]
        return []

    if "AS ENTITIES" in upper or ("COUNT(E)" in upper and "COUNT(F)" in upper):
        return [
            {
                "entities": len(self.entities),
                "facts": len(self.facts),
                "mentions": len(self.mentions),
                "relations": len(self.relations),
            }
        ]

    min_conf = float(params.get("min_confidence") or 0.0)
    name = _norm_name(str(params.get("name") or ""))
    name2 = _norm_name(str(params.get("name2") or ""))
    etype = str(params.get("entity_type") or "").strip().lower()
    predicate = str(params.get("predicate") or "").strip()

    def _ids_for(want: str) -> set[str]:
        return {
            eid
            for eid, ent in self.entities.items()
            if _norm_name(ent.get("name", "")).casefold() == want.casefold()
        }

    def _entity_match(eid: str, want: str) -> bool:
        ent = self.entities.get(eid) or {}
        return _norm_name(ent.get("name", "")).casefold() == want.casefold()

    if template == "count_facts_mentioning" or (
        not template and "MENTIONS" in upper and "COUNT(DISTINCT F)" in upper and name and not name2
    ):
        eids = _ids_for(name)
        fact_ids = sorted({fid for eid, fid in self.mentions if eid in eids})
        return [{"value": len(fact_ids), "fact_ids": fact_ids}]

    if template == "count_relations" or (
        not template and "RELATES" in upper and "COUNT" in upper and name
    ):
        count = 0
        fact_ids: list[str] = []
        for rel in self.relations:
            if rel.get("predicate") == "NEXT_TURN":
                continue
            if float(rel.get("confidence") or 0) < min_conf:
                continue
            if predicate and predicate.casefold() not in rel["predicate"].casefold():
                continue
            if not (_entity_match(rel["src"], name) or _entity_match(rel["dst"], name)):
                continue
            count += 1
            if rel.get("fact_id"):
                fact_ids.append(str(rel["fact_id"]))
        return [{"value": count, "fact_ids": sorted(set(fact_ids))}]

    if template == "collect_related":
        seed = _ids_for(name)
        names: list[str] = []
        fact_ids = []
        for rel in self.relations:
            if rel.get("predicate") == "NEXT_TURN":
                continue
            if float(rel.get("confidence") or 0) < min_conf:
                continue
            other = None
            if rel["src"] in seed:
                other = rel["dst"]
            elif rel["dst"] in seed:
                other = rel["src"]
            if other is None:
                continue
            ent = self.entities.get(other) or {}
            if etype and (ent.get("type") or "").lower() != etype:
                continue
            n = ent.get("name") or ""
            if n.startswith("turn:"):
                continue
            if n and n not in names:
                names.append(n)
            if rel.get("fact_id"):
                fact_ids.append(str(rel["fact_id"]))
        return [{"value": names, "fact_ids": sorted(set(fact_ids))}]

    if template == "path_related":
        seed = _ids_for(name)
        frontier = set(seed)
        seen = set(seed)
        for _ in range(2):
            nxt: set[str] = set()
            for rel in self.relations:
                if float(rel.get("confidence") or 0) < min_conf and rel.get("predicate") != "NEXT_TURN":
                    if float(rel.get("confidence") or 0) < min_conf:
                        continue
                a, b = rel["src"], rel["dst"]
                if a in frontier and b not in seen:
                    seen.add(b)
                    nxt.add(b)
                if b in frontier and a not in seen:
                    seen.add(a)
                    nxt.add(a)
            frontier = nxt
        names = []
        for eid in seen - seed:
            ent = self.entities.get(eid) or {}
            if etype and (ent.get("type") or "").lower() != etype:
                continue
            n = ent.get("name") or ""
            if n and not n.startswith("turn:"):
                names.append(n)
        return [{"value": sorted(set(names)), "fact_ids": []}]

    if template == "co_mention_count" or (name and name2 and "MENTIONS" in upper):
        facts1 = {fid for eid, fid in self.mentions if eid in _ids_for(name)}
        facts2 = {fid for eid, fid in self.mentions if eid in _ids_for(name2)}
        shared = sorted(facts1 & facts2)
        return [{"value": len(shared), "fact_ids": shared}]

    return []


_InMemoryDriver.execute = _inmemory_execute  # type: ignore[attr-defined]


class Neo4jMemoryStore:
    """Precise-query graph: Entity / Fact / RELATES / MENTIONS / NEXT_TURN."""

    def __init__(
        self,
        *,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        driver: Any | None = None,
    ) -> None:
        self.uri = (uri if uri is not None else config.NEO4J_URI) or "bolt://localhost:7687"
        self.user = user if user is not None else config.NEO4J_USER
        self.password = password if password is not None else config.NEO4J_PASSWORD
        self.database = database if database is not None else config.NEO4J_DATABASE
        self._memory = isinstance(driver, _InMemoryDriver) or self.uri.startswith("memory://")
        if driver is not None:
            self._driver = driver
        elif self.uri.startswith("memory://"):
            self._driver = _InMemoryDriver()
        else:
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:
                raise ImportError(
                    "neo4j package required: pip install 'la-localagent[neo4j]'"
                ) from exc
            self._driver = GraphDatabase.driver(
                self.uri, auth=(self.user, self.password)
            )
        self._ensure_schema()

    def _session_kwargs(self) -> dict[str, Any]:
        if self._memory:
            return {}
        return {"database": self.database}

    def _ensure_schema(self) -> None:
        if self._memory:
            return
        try:
            with self._driver.session(**self._session_kwargs()) as session:
                for stmt in _SCHEMA_CYPHER.strip().split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        session.run(stmt)
        except Exception as exc:
            logger.warning("neo4j schema ensure failed: %s", exc)

    def close(self) -> None:
        try:
            self._driver.close()
        except Exception:
            pass

    def clear(self) -> None:
        with _lock:
            with self._driver.session(**self._session_kwargs()) as session:
                session.run("MATCH (n) DETACH DELETE n")

    def run_cypher(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        with _lock:
            with self._driver.session(**self._session_kwargs()) as session:
                result = session.run(cypher, parameters=params or {})
                return list(result.data())

    def stats(self) -> dict[str, int]:
        rows = self.run_cypher(
            """
            MATCH (e:Entity) WITH count(e) AS entities
            MATCH (f:Fact) WITH entities, count(f) AS facts
            MATCH ()-[r:RELATES|NEXT_TURN]->() WITH entities, facts, count(r) AS relations
            MATCH ()-[m:MENTIONS]->()
            RETURN entities, facts, relations, count(m) AS mentions
            """
        )
        if not rows:
            if self._memory and isinstance(self._driver, _InMemoryDriver):
                return {
                    "entities": len(self._driver.entities),
                    "facts": len(self._driver.facts),
                    "relations": len(self._driver.relations),
                    "mentions": len(self._driver.mentions),
                }
            return {"entities": 0, "facts": 0, "relations": 0, "mentions": 0}
        row = rows[0]
        return {
            "entities": int(row.get("entities") or 0),
            "facts": int(row.get("facts") or 0),
            "relations": int(row.get("relations") or 0),
            "mentions": int(row.get("mentions") or 0),
        }

    def upsert_entity(self, name: str, *, entity_type: str = "concept") -> str | None:
        cleaned = _norm_name(name)
        if not cleaned or len(cleaned) < 2:
            return None
        eid = entity_id_for(cleaned)
        etype = (entity_type or "concept").strip() or "concept"
        self.run_cypher(
            """
            MERGE (e:Entity {id: $id})
            ON CREATE SET e.name = $name, e.type = $type
            ON MATCH SET e.name = $name,
              e.type = CASE
                WHEN e.type = 'concept' AND $type <> 'concept' THEN $type
                ELSE e.type END
            """,
            {"id": eid, "name": cleaned, "type": etype},
        )
        return eid

    def upsert_fact(
        self,
        fact_id: str,
        *,
        text: str = "",
        created_at: str = "",
        source_file: str = "",
    ) -> None:
        if not fact_id:
            return
        self.run_cypher(
            """
            MERGE (f:Fact {id: $id})
            SET f.text = $text, f.created_at = $created_at, f.source_file = $source_file
            """,
            {
                "id": fact_id,
                "text": text or "",
                "created_at": created_at or "",
                "source_file": source_file or "",
            },
        )

    def add_mention(self, entity_id: str, fact_id: str) -> None:
        if not entity_id or not fact_id:
            return
        self.run_cypher(
            """
            MATCH (e:Entity {id: $eid})
            MATCH (f:Fact {id: $fid})
            MERGE (e)-[:MENTIONS]->(f)
            """,
            {"eid": entity_id, "fid": fact_id},
        )

    def add_relation(
        self,
        src_entity: str,
        predicate: str,
        dst_entity: str,
        *,
        fact_id: str | None = None,
        confidence: float = 1.0,
    ) -> None:
        if not src_entity or not dst_entity or src_entity == dst_entity:
            return
        pred = " ".join((predicate or "related_to").strip().split()) or "related_to"
        # NEXT_TURN is a dedicated type for dialog adjacency.
        if pred.upper() == "NEXT_TURN" or pred == "NEXT_TURN":
            self.run_cypher(
                """
                MATCH (a:Entity {id: $src})
                MATCH (b:Entity {id: $dst})
                MERGE (a)-[r:NEXT_TURN]->(b)
                SET r.fact_id = $fact_id, r.confidence = $confidence, r.predicate = 'NEXT_TURN'
                """,
                {
                    "src": src_entity,
                    "dst": dst_entity,
                    "fact_id": fact_id,
                    "confidence": float(confidence),
                },
            )
            return
        self.run_cypher(
            """
            MATCH (a:Entity {id: $src})
            MATCH (b:Entity {id: $dst})
            MERGE (a)-[r:RELATES {predicate: $predicate, fact_id: $fact_id}]->(b)
            SET r.confidence = $confidence
            """,
            {
                "src": src_entity,
                "dst": dst_entity,
                "predicate": pred,
                "fact_id": fact_id,
                "confidence": float(confidence),
            },
        )

    def remove_fact(self, fact_id: str) -> None:
        if not fact_id:
            return
        self.run_cypher(
            """
            OPTIONAL MATCH (f:Fact {id: $id})
            OPTIONAL MATCH ()-[r:RELATES|NEXT_TURN {fact_id: $id}]->()
            DELETE r
            WITH f
            OPTIONAL MATCH (e:Entity)-[m:MENTIONS]->(f)
            DELETE m, f
            """,
            {"id": fact_id},
        )

    def resolve_entity_ids(self, names: Iterable[str]) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for name in names:
            cleaned = _norm_name(name)
            if not cleaned:
                continue
            eid = entity_id_for(cleaned)
            if self._memory and isinstance(self._driver, _InMemoryDriver):
                ent = self._driver.entities.get(eid)
                if ent is None:
                    for other in self._driver.entities.values():
                        if _norm_name(other.get("name", "")).casefold() == cleaned.casefold():
                            eid = other["id"]
                            ent = other
                            break
                if ent is None:
                    continue
            else:
                rows = self.run_cypher(
                    """
                    MATCH (e:Entity)
                    WHERE e.id = $id OR toLower(e.name) = toLower($name)
                    RETURN e.id AS id LIMIT 1
                    """,
                    {"id": eid, "name": cleaned},
                )
                if not rows:
                    continue
                eid = str(rows[0].get("id") or eid)
            if eid not in seen:
                seen.add(eid)
                ids.append(eid)
        return ids

    def neighbor_entity_ids(self, entity_ids: Iterable[str], *, hops: int = 1) -> set[str]:
        frontier = {eid for eid in entity_ids if eid}
        seen = set(frontier)
        if self._memory and isinstance(self._driver, _InMemoryDriver):
            for _ in range(max(0, hops)):
                if not frontier:
                    break
                nxt: set[str] = set()
                for rel in self._driver.relations:
                    a, b = rel["src"], rel["dst"]
                    if a in frontier and b not in seen:
                        seen.add(b)
                        nxt.add(b)
                    if b in frontier and a not in seen:
                        seen.add(a)
                        nxt.add(a)
                frontier = nxt
            return seen

        for _ in range(max(0, hops)):
            if not frontier:
                break
            rows = self.run_cypher(
                """
                MATCH (a:Entity)-[:RELATES|NEXT_TURN]-(b:Entity)
                WHERE a.id IN $ids
                RETURN DISTINCT b.id AS id
                """,
                {"ids": list(frontier)},
            )
            nxt = set()
            for row in rows:
                eid = str(row.get("id") or "")
                if eid and eid not in seen:
                    seen.add(eid)
                    nxt.add(eid)
            frontier = nxt
        return seen

    def fact_ids_for_entities(self, entity_ids: Iterable[str]) -> set[str]:
        ids = [eid for eid in entity_ids if eid]
        if not ids:
            return set()
        if self._memory and isinstance(self._driver, _InMemoryDriver):
            return {fid for eid, fid in self._driver.mentions if eid in set(ids)}
        rows = self.run_cypher(
            """
            MATCH (e:Entity)-[:MENTIONS]->(f:Fact)
            WHERE e.id IN $ids
            RETURN DISTINCT f.id AS id
            """,
            {"ids": ids},
        )
        return {str(row.get("id")) for row in rows if row.get("id")}


def get_neo4j_store() -> Neo4jMemoryStore:
    global _store
    with _lock:
        if _store is None:
            _store = Neo4jMemoryStore()
        return _store


def reset_neo4j_store_singleton() -> None:
    """Test helper: close and drop the process-wide Neo4j singleton."""
    global _store
    with _lock:
        if _store is not None:
            _store.close()
            _store = None


def sync_fact_to_neo4j(fact: Any) -> None:
    """Index one MemoryFact into Neo4j when LA_NEO4J is enabled."""
    if not neo4j_enabled():
        return
    if not neo4j_available():
        logger.warning("LA_NEO4J=1 but neo4j driver unavailable; skip sync")
        return
    from localagent.memory.graph.extract import extract_graph_payload

    try:
        payload = extract_graph_payload(fact)
        store = get_neo4j_store()
        fact_id = str(getattr(fact, "id", "") or "")
        if not fact_id:
            return
        store.remove_fact(fact_id)
        store.upsert_fact(
            fact_id,
            text=str(getattr(fact, "text", "") or ""),
            created_at=str(getattr(fact, "created_at", "") or ""),
            source_file=str(getattr(fact, "source_file", "") or ""),
        )
        entity_ids: dict[str, str] = {}
        for name, etype in payload.entities:
            eid = store.upsert_entity(name, entity_type=etype)
            if eid:
                entity_ids[name.casefold()] = eid
                store.add_mention(eid, fact_id)
        for src, pred, dst, conf in payload.relations:
            src_id = entity_ids.get(src.casefold()) or store.upsert_entity(src)
            dst_id = entity_ids.get(dst.casefold()) or store.upsert_entity(dst)
            if src_id and dst_id:
                store.add_relation(
                    src_id, pred, dst_id, fact_id=fact_id, confidence=conf
                )
                store.add_mention(src_id, fact_id)
                store.add_mention(dst_id, fact_id)
    except Exception as exc:
        logger.warning("neo4j sync failed for %s: %s", getattr(fact, "id", "?"), exc)


def unsync_fact_from_neo4j(fact_id: str) -> None:
    if not neo4j_enabled():
        return
    if not neo4j_available():
        return
    try:
        get_neo4j_store().remove_fact(fact_id)
    except Exception as exc:
        logger.debug("neo4j unsync failed for %s: %s", fact_id, exc)


def rebuild_neo4j_graph(*, facts: list[Any] | None = None) -> dict[str, int]:
    """Clear and rebuild the Neo4j graph from the Warm registry."""
    from localagent.memory.store import get_memory_store

    previous = config.NEO4J
    config.NEO4J = True
    try:
        if not neo4j_available():
            raise RuntimeError(
                "Neo4j unavailable: install 'la-localagent[neo4j]' "
                "or set LA_NEO4J_URI=memory://"
            )
        store = get_neo4j_store()
        store.clear()
        source = facts if facts is not None else list(get_memory_store().all_facts())
        for fact in source:
            sync_fact_to_neo4j(fact)
        _link_dialog_neighbors_neo4j(store, source)
        return store.stats()
    finally:
        config.NEO4J = previous


def _link_dialog_neighbors_neo4j(store: Neo4jMemoryStore, facts: list[Any]) -> None:
    by_session: dict[int, list[tuple[int, Any]]] = {}
    for fact in facts:
        meta = getattr(fact, "metadata", None) or {}
        dia = str(meta.get("dia_id") or "")
        match = _DIA_RE.match(dia)
        if not match:
            continue
        session_num = int(match.group(1))
        turn_num = int(match.group(2))
        by_session.setdefault(session_num, []).append((turn_num, fact))

    for turns in by_session.values():
        turns.sort(key=lambda item: item[0])
        for index in range(len(turns) - 1):
            turn_a, fact_a = turns[index]
            turn_b, fact_b = turns[index + 1]
            if turn_b != turn_a + 1:
                continue
            a_name = f"turn:{getattr(fact_a, 'id', '')}"
            b_name = f"turn:{getattr(fact_b, 'id', '')}"
            a_id = store.upsert_entity(a_name, entity_type="turn")
            b_id = store.upsert_entity(b_name, entity_type="turn")
            if not a_id or not b_id:
                continue
            store.add_mention(a_id, str(fact_a.id))
            store.add_mention(b_id, str(fact_b.id))
            store.add_relation(
                a_id,
                "NEXT_TURN",
                b_id,
                fact_id=str(fact_a.id),
                confidence=0.7,
            )
