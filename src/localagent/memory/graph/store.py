"""SQLite-backed entity / relation store for Warm memory graph overlay."""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from localagent import config

logger = logging.getLogger(__name__)

_DIA_RE = re.compile(r"^D(\d+):(\d+)$", re.IGNORECASE)
_lock = threading.Lock()
_graph: MemoryGraphStore | None = None


def graph_enabled() -> bool:
    return bool(getattr(config, "MEMORY_GRAPH", False))


def graph_expand_enabled() -> bool:
    """True when recall should hop-expand via SQLite and/or Neo4j."""
    if graph_enabled():
        return True
    if bool(getattr(config, "NEO4J", False)):
        try:
            from localagent.memory.graph.neo4j_store import neo4j_available

            return neo4j_available()
        except Exception:
            return False
    return False


def memory_graph_path() -> Path:
    return Path(config.MEMORY_GRAPH_FILE)


def entity_id_for(name: str) -> str:
    normalized = " ".join((name or "").strip().split())
    key = normalized.casefold()
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"e_{digest}"


class MemoryGraphStore:
    """Embedded relation index: Entity / FactMention / Relation."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else memory_graph_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'concept'
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_name
                ON entities(name COLLATE NOCASE);
            CREATE TABLE IF NOT EXISTS fact_mentions (
                entity_id TEXT NOT NULL,
                fact_id TEXT NOT NULL,
                PRIMARY KEY (entity_id, fact_id),
                FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_mentions_fact ON fact_mentions(fact_id);
            CREATE TABLE IF NOT EXISTS relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                src_entity TEXT NOT NULL,
                predicate TEXT NOT NULL,
                dst_entity TEXT NOT NULL,
                fact_id TEXT,
                confidence REAL NOT NULL DEFAULT 1.0,
                UNIQUE(src_entity, predicate, dst_entity, fact_id),
                FOREIGN KEY (src_entity) REFERENCES entities(id) ON DELETE CASCADE,
                FOREIGN KEY (dst_entity) REFERENCES entities(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_rel_src ON relations(src_entity);
            CREATE INDEX IF NOT EXISTS idx_rel_dst ON relations(dst_entity);
            CREATE INDEX IF NOT EXISTS idx_rel_fact ON relations(fact_id);
            """
        )
        self._conn.commit()

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def clear(self) -> None:
        with _lock:
            self._conn.executescript(
                "DELETE FROM relations; DELETE FROM fact_mentions; DELETE FROM entities;"
            )
            self._conn.commit()

    def stats(self) -> dict[str, int]:
        cur = self._conn.cursor()
        entities = cur.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        mentions = cur.execute("SELECT COUNT(*) FROM fact_mentions").fetchone()[0]
        relations = cur.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        facts = cur.execute(
            "SELECT COUNT(DISTINCT fact_id) FROM fact_mentions WHERE fact_id IS NOT NULL"
        ).fetchone()[0]
        return {
            "entities": int(entities),
            "mentions": int(mentions),
            "relations": int(relations),
            "facts": int(facts),
        }

    def upsert_entity(self, name: str, *, entity_type: str = "concept") -> str | None:
        cleaned = " ".join((name or "").strip().split())
        if not cleaned or len(cleaned) < 2:
            return None
        eid = entity_id_for(cleaned)
        etype = (entity_type or "concept").strip() or "concept"
        with _lock:
            self._conn.execute(
                """
                INSERT INTO entities (id, name, type) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    type=CASE
                        WHEN entities.type = 'concept' AND excluded.type != 'concept'
                        THEN excluded.type ELSE entities.type END
                """,
                (eid, cleaned, etype),
            )
            self._conn.commit()
        return eid

    def add_mention(self, entity_id: str, fact_id: str) -> None:
        if not entity_id or not fact_id:
            return
        with _lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO fact_mentions (entity_id, fact_id) VALUES (?, ?)",
                (entity_id, fact_id),
            )
            self._conn.commit()

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
        with _lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO relations
                    (src_entity, predicate, dst_entity, fact_id, confidence)
                VALUES (?, ?, ?, ?, ?)
                """,
                (src_entity, pred, dst_entity, fact_id, float(confidence)),
            )
            self._conn.commit()

    def remove_fact(self, fact_id: str) -> None:
        if not fact_id:
            return
        with _lock:
            self._conn.execute("DELETE FROM fact_mentions WHERE fact_id = ?", (fact_id,))
            self._conn.execute("DELETE FROM relations WHERE fact_id = ?", (fact_id,))
            self._conn.execute(
                """
                DELETE FROM entities WHERE id NOT IN (
                    SELECT entity_id FROM fact_mentions
                    UNION
                    SELECT src_entity FROM relations
                    UNION
                    SELECT dst_entity FROM relations
                )
                """
            )
            self._conn.commit()

    def resolve_entity_ids(self, names: Iterable[str]) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for name in names:
            cleaned = " ".join((name or "").strip().split())
            if not cleaned:
                continue
            eid = entity_id_for(cleaned)
            row = self._conn.execute(
                "SELECT id FROM entities WHERE id = ? OR name = ? COLLATE NOCASE",
                (eid, cleaned),
            ).fetchone()
            if row is None:
                continue
            resolved = str(row["id"])
            if resolved not in seen:
                seen.add(resolved)
                ids.append(resolved)
        return ids

    def neighbor_entity_ids(self, entity_ids: Iterable[str], *, hops: int = 1) -> set[str]:
        frontier = {eid for eid in entity_ids if eid}
        seen = set(frontier)
        for _ in range(max(0, hops)):
            if not frontier:
                break
            placeholders = ",".join("?" * len(frontier))
            rows = self._conn.execute(
                f"""
                SELECT dst_entity AS eid FROM relations WHERE src_entity IN ({placeholders})
                UNION
                SELECT src_entity AS eid FROM relations WHERE dst_entity IN ({placeholders})
                """,
                (*frontier, *frontier),
            ).fetchall()
            nxt: set[str] = set()
            for row in rows:
                eid = str(row["eid"])
                if eid not in seen:
                    seen.add(eid)
                    nxt.add(eid)
            frontier = nxt
        return seen

    def fact_ids_for_entities(self, entity_ids: Iterable[str]) -> set[str]:
        ids = [eid for eid in entity_ids if eid]
        if not ids:
            return set()
        placeholders = ",".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT DISTINCT fact_id FROM fact_mentions WHERE entity_id IN ({placeholders})",
            ids,
        ).fetchall()
        return {str(row["fact_id"]) for row in rows if row["fact_id"]}

    def paths_between_facts(
        self,
        seed_fact_ids: Iterable[str],
        target_fact_ids: Iterable[str],
        *,
        max_paths: int = 8,
    ) -> list[str]:
        """Return short human-readable relation snippets linking seed → target facts."""
        seeds = {fid for fid in seed_fact_ids if fid}
        targets = {fid for fid in target_fact_ids if fid} - seeds
        if not seeds or not targets:
            return []
        seed_ph = ",".join("?" * len(seeds))
        tgt_ph = ",".join("?" * len(targets))
        rows = self._conn.execute(
            f"""
            SELECT DISTINCT
                e1.name AS src_name,
                r.predicate AS predicate,
                e2.name AS dst_name
            FROM relations r
            JOIN entities e1 ON e1.id = r.src_entity
            JOIN entities e2 ON e2.id = r.dst_entity
            JOIN fact_mentions m1 ON m1.entity_id = r.src_entity
            JOIN fact_mentions m2 ON m2.entity_id = r.dst_entity
            WHERE m1.fact_id IN ({seed_ph})
              AND (m2.fact_id IN ({tgt_ph}) OR r.fact_id IN ({tgt_ph}))
            LIMIT ?
            """,
            (*seeds, *targets, *targets, max_paths),
        ).fetchall()
        return [
            f"[{row['src_name']}] -{row['predicate']}→ [{row['dst_name']}]" for row in rows
        ]


def get_memory_graph() -> MemoryGraphStore:
    global _graph
    with _lock:
        if _graph is None:
            config.ensure_data_dirs()
            _graph = MemoryGraphStore()
        return _graph


def reset_memory_graph_singleton() -> None:
    """Test helper: close and drop the process-wide graph singleton."""
    global _graph
    with _lock:
        if _graph is not None:
            _graph.close()
            _graph = None


def sync_fact_to_graph(fact: Any, *, neo4j: bool = True) -> None:
    """Index one MemoryFact into SQLite (optional) and/or Neo4j (optional)."""
    if graph_enabled():
        from localagent.memory.graph.extract import extract_graph_payload

        try:
            payload = extract_graph_payload(fact)
            graph = get_memory_graph()
            fact_id = str(getattr(fact, "id", "") or "")
            if fact_id:
                graph.remove_fact(fact_id)
                entity_ids: dict[str, str] = {}
                for name, etype in payload.entities:
                    eid = graph.upsert_entity(name, entity_type=etype)
                    if eid:
                        entity_ids[name.casefold()] = eid
                        graph.add_mention(eid, fact_id)
                for src, pred, dst, conf in payload.relations:
                    src_id = entity_ids.get(src.casefold()) or graph.upsert_entity(src)
                    dst_id = entity_ids.get(dst.casefold()) or graph.upsert_entity(dst)
                    if src_id and dst_id:
                        graph.add_relation(
                            src_id, pred, dst_id, fact_id=fact_id, confidence=conf
                        )
                        graph.add_mention(src_id, fact_id)
                        graph.add_mention(dst_id, fact_id)
        except Exception as exc:
            logger.warning(
                "memory graph sync failed for %s: %s", getattr(fact, "id", "?"), exc
            )

    if neo4j:
        try:
            from localagent.memory.graph.neo4j_store import sync_fact_to_neo4j

            sync_fact_to_neo4j(fact)
        except Exception as exc:
            logger.debug("neo4j sync dispatch failed: %s", exc)


def unsync_fact_from_graph(fact_id: str) -> None:
    if graph_enabled() or memory_graph_path().exists():
        try:
            get_memory_graph().remove_fact(fact_id)
        except Exception as exc:
            logger.debug("memory graph unsync failed for %s: %s", fact_id, exc)
    try:
        from localagent.memory.graph.neo4j_store import unsync_fact_from_neo4j

        unsync_fact_from_neo4j(fact_id)
    except Exception as exc:
        logger.debug("neo4j unsync dispatch failed: %s", exc)


def rebuild_memory_graph(*, facts: list[Any] | None = None) -> dict[str, int]:
    """Clear and rebuild the SQLite graph from the Warm registry.

    When LA_NEO4J is enabled, also rebuilds the Neo4j precise index
    (returned stats remain SQLite-only; Neo4j stats via rebuild_neo4j_graph).
    """
    from localagent.memory.store import get_memory_store

    previous = config.MEMORY_GRAPH
    config.MEMORY_GRAPH = True
    try:
        graph = get_memory_graph()
        graph.clear()
        source = facts if facts is not None else list(get_memory_store().all_facts())
        for fact in source:
            sync_fact_to_graph(fact, neo4j=False)
        _link_dialog_neighbors(graph, source)
        stats = graph.stats()
    finally:
        config.MEMORY_GRAPH = previous

    try:
        from localagent.memory.graph.neo4j_store import neo4j_enabled, rebuild_neo4j_graph

        if neo4j_enabled():
            rebuild_neo4j_graph(facts=facts)
    except Exception as exc:
        logger.warning("neo4j rebuild during memory graph rebuild failed: %s", exc)

    return stats


def _link_dialog_neighbors(graph: MemoryGraphStore, facts: list[Any]) -> None:
    """Add NEXT_TURN edges between adjacent dia_id facts in the same session."""
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
            a_id = graph.upsert_entity(a_name, entity_type="turn")
            b_id = graph.upsert_entity(b_name, entity_type="turn")
            if not a_id or not b_id:
                continue
            graph.add_mention(a_id, str(fact_a.id))
            graph.add_mention(b_id, str(fact_b.id))
            graph.add_relation(
                a_id,
                "NEXT_TURN",
                b_id,
                fact_id=str(fact_a.id),
                confidence=0.7,
            )
