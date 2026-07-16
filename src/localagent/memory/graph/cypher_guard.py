"""Read-only Cypher validation for Neo4j precise queries."""

from __future__ import annotations

import re
from dataclasses import dataclass

from localagent import config

# Write / admin verbs that must never run from the query path.
_FORBIDDEN = re.compile(
    r"\b(?:"
    r"CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD|CALL|FOREACH|"
    r"USING\s+PERIODIC|APOC\.|dbms\.|db\."
    r")\b",
    re.IGNORECASE,
)
_COMMENTS = re.compile(r"/\*.*?\*/|//.*?$", re.DOTALL | re.MULTILINE)
_RETURN = re.compile(r"\bRETURN\b", re.IGNORECASE)
_MATCH = re.compile(r"\bMATCH\b|\bOPTIONAL\s+MATCH\b", re.IGNORECASE)


@dataclass(frozen=True)
class CypherGuardResult:
    ok: bool
    reason: str = ""
    limited_cypher: str = ""


def strip_cypher_comments(cypher: str) -> str:
    return _COMMENTS.sub(" ", cypher or "").strip()


def validate_readonly_cypher(
    cypher: str,
    *,
    max_rows: int | None = None,
) -> CypherGuardResult:
    """Ensure Cypher is read-only MATCH/RETURN and apply a row limit."""
    cleaned = strip_cypher_comments(cypher)
    if not cleaned:
        return CypherGuardResult(ok=False, reason="empty Cypher")

    if _FORBIDDEN.search(cleaned):
        return CypherGuardResult(
            ok=False,
            reason="forbidden write/admin clause in Cypher",
        )
    if not _MATCH.search(cleaned):
        return CypherGuardResult(ok=False, reason="Cypher must contain MATCH")
    if not _RETURN.search(cleaned):
        return CypherGuardResult(ok=False, reason="Cypher must contain RETURN")

    limit = config.NEO4J_MAX_ROWS if max_rows is None else max(1, int(max_rows))
    limited = cleaned
    if not re.search(r"\bLIMIT\s+\d+\b", cleaned, re.IGNORECASE):
        limited = f"{cleaned.rstrip().rstrip(';')} LIMIT {limit}"

    return CypherGuardResult(ok=True, limited_cypher=limited)
