"""Write-time memory consolidation: ADD / UPDATE / DELETE / NOOP."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from localagent import config

logger = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_OPS = frozenset({"ADD", "UPDATE", "DELETE", "NOOP"})


@dataclass
class ConsolidationAction:
    op: str
    text: str
    target_id: str = ""
    reason: str = ""


@dataclass
class ConsolidationReport:
    actions: list[ConsolidationAction] = field(default_factory=list)
    retained_ids: list[str] = field(default_factory=list)
    updated_ids: list[str] = field(default_factory=list)
    deleted_ids: list[str] = field(default_factory=list)
    noop_count: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return len(self.retained_ids) + len(self.updated_ids) + len(self.deleted_ids)


def _parse_action(reply: str, *, fallback_text: str) -> ConsolidationAction:
    raw = (reply or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    data: Any = None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = _JSON_RE.search(raw)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, dict):
        return ConsolidationAction(op="ADD", text=fallback_text, reason="parse_failed")
    op = str(data.get("op") or data.get("operation") or "ADD").strip().upper()
    if op not in _OPS:
        op = "ADD"
    text = str(data.get("text") or fallback_text).strip() or fallback_text
    target_id = str(data.get("target_id") or data.get("id") or "").strip()
    reason = str(data.get("reason") or "").strip()
    return ConsolidationAction(op=op, text=text, target_id=target_id, reason=reason)


def _decide_against_related(
    new_text: str,
    related: list[dict[str, Any]],
) -> ConsolidationAction:
    if not related:
        return ConsolidationAction(op="ADD", text=new_text, reason="no_related")

    try:
        from localagent.models.router import ChatMessage, get_model_router
    except Exception:
        return ConsolidationAction(op="ADD", text=new_text, reason="llm_unavailable")

    lines = []
    for hit in related[: config.MEMORY_CONSOLIDATE_RELATED_K]:
        hid = str(hit.get("id") or "")
        text = str(hit.get("text") or "").strip()
        if text:
            lines.append(f"- id={hid}: {text}")
    prompt = (
        "你是记忆巩固器。将「新事实」与已有相关记忆比较，决定操作。\n"
        "只输出 JSON：\n"
        '{"op":"ADD|UPDATE|DELETE|NOOP","target_id":"已有记忆id或空","text":"最终应保留的文本","reason":"简短原因"}\n'
        "规则：\n"
        "- 全新信息 → ADD（target_id 空，text=新事实）\n"
        "- 与某条冲突且新事实更新 → UPDATE（填 target_id，text=合并后的正确事实）\n"
        "- 新事实完全重复 → NOOP\n"
        "- 新事实表明旧事实作废且无需新条 → DELETE（填 target_id）\n"
        "- 不要编造；不确定时用 ADD\n\n"
        f"新事实：{new_text}\n\n相关记忆：\n" + "\n".join(lines)
    )
    try:
        reply = get_model_router().chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.0,
            usage_command="memory_consolidate",
        )
    except Exception as exc:
        logger.debug("consolidate decide failed: %s", exc)
        return ConsolidationAction(op="ADD", text=new_text, reason="llm_failed")
    return _parse_action(reply, fallback_text=new_text)


def _apply_action(
    backend: Any,
    action: ConsolidationAction,
    *,
    metadata: dict[str, Any] | None,
    report: ConsolidationReport,
) -> None:
    meta = dict(metadata or {})
    meta.setdefault("source", meta.get("source") or "consolidate")
    if action.op == "NOOP":
        report.noop_count += 1
        return
    if action.op == "ADD":
        fact_id = backend.retain(action.text, metadata=meta)
        if fact_id:
            report.retained_ids.append(fact_id)
        return
    if action.op == "DELETE":
        if not action.target_id:
            report.errors.append("DELETE missing target_id")
            return
        if backend.delete(action.target_id):
            report.deleted_ids.append(action.target_id)
        else:
            report.errors.append(f"DELETE failed: {action.target_id}")
        return
    if action.op == "UPDATE":
        if not action.target_id:
            # Fall back to add if no target.
            fact_id = backend.retain(action.text, metadata=meta)
            if fact_id:
                report.retained_ids.append(fact_id)
            return
        # Preserve provenance from the old fact when possible.
        from localagent.memory.store import get_memory_store

        store = get_memory_store()
        old = store.get(action.target_id)
        update_meta = dict(meta)
        if old is not None:
            update_meta.setdefault("source_file", old.source_file)
            update_meta.setdefault("section_heading", old.section_heading)
            for key in ("session_id", "dia_id", "occurred_at", "speaker"):
                if key in (old.metadata or {}) and key not in update_meta:
                    update_meta[key] = old.metadata[key]
            update_meta["replaced_id"] = old.id
        if not backend.delete(action.target_id):
            report.errors.append(f"UPDATE delete failed: {action.target_id}")
            return
        new_id = backend.retain(action.text, metadata=update_meta)
        if new_id:
            report.updated_ids.append(new_id)
            report.deleted_ids.append(action.target_id)
        else:
            report.errors.append(f"UPDATE retain failed after delete: {action.target_id}")
        return
    report.errors.append(f"unknown op: {action.op}")


def consolidate_candidates(
    candidates: list[str],
    *,
    metadata: dict[str, Any] | None = None,
    already_retained: bool = False,
) -> ConsolidationReport:
    """Consolidate candidate facts against related existing memories.

    If ``already_retained`` is True, candidates are texts that were just written;
    NOOP/DELETE/UPDATE may remove the newest duplicate, and ADD is skipped
    (treat identical new writes as already present — use related matching only).
    Prefer calling this **before** retain with already_retained=False.
    """
    report = ConsolidationReport()
    if not config.MEMORY_CONSOLIDATE:
        if not already_retained:
            from localagent.memory.backend import get_memory_backend

            backend = get_memory_backend()
            for text in candidates:
                fact_id = backend.retain(text, metadata=metadata)
                if fact_id:
                    report.retained_ids.append(fact_id)
                    report.actions.append(ConsolidationAction(op="ADD", text=text))
        return report

    from localagent.memory.backend import get_memory_backend

    backend = get_memory_backend()
    related_k = max(1, config.MEMORY_CONSOLIDATE_RELATED_K)

    for text in candidates:
        cleaned = " ".join((text or "").split())
        if not cleaned:
            continue
        try:
            related = backend.recall(cleaned, max_results=related_k)
        except Exception as exc:
            logger.debug("consolidate recall failed: %s", exc)
            related = []

        # When consolidating pre-retained facts, drop self-matches by exact text.
        if already_retained:
            related = [
                hit
                for hit in related
                if " ".join(str(hit.get("text") or "").split()) != cleaned
            ]

        action = _decide_against_related(cleaned, related)
        report.actions.append(action)

        if already_retained:
            if action.op == "ADD":
                # Already retained — nothing to do.
                report.noop_count += 1
                continue
            if action.op == "NOOP":
                # Duplicate of an older fact: remove the newly retained copy if we can find it.
                report.noop_count += 1
                for hit in backend.recall(cleaned, max_results=3):
                    if " ".join(str(hit.get("text") or "").split()) == cleaned:
                        hid = str(hit.get("id") or "")
                        # Prefer deleting the newest duplicate when target points elsewhere.
                        if action.target_id and hid == action.target_id:
                            continue
                        if hid and backend.delete(hid):
                            report.deleted_ids.append(hid)
                        break
                continue
            _apply_action(backend, action, metadata=metadata, report=report)
            continue

        _apply_action(backend, action, metadata=metadata, report=report)

    return report


def consolidate_recent(
    *,
    limit: int = 40,
) -> ConsolidationReport:
    """Re-check recent registry facts and merge contradictions (background task)."""
    from localagent.memory.backend import get_memory_backend
    from localagent.memory.store import get_memory_store

    report = ConsolidationReport()
    if not config.MEMORY_CONSOLIDATE:
        return report

    store = get_memory_store()
    facts = list(store.all_facts())
    # Newest last in file often; process the tail.
    window = facts[-max(1, limit) :]
    backend = get_memory_backend()
    related_k = max(1, config.MEMORY_CONSOLIDATE_RELATED_K)

    for fact in window:
        text = " ".join((fact.text or "").split())
        if not text:
            continue
        try:
            related = [
                hit
                for hit in backend.recall(text, max_results=related_k + 1)
                if str(hit.get("id") or "") != fact.id
            ]
        except Exception:
            related = []
        if not related:
            continue
        action = _decide_against_related(text, related)
        report.actions.append(action)
        if action.op in {"NOOP", "ADD"}:
            if action.op == "NOOP":
                report.noop_count += 1
            continue
        # For store scan: UPDATE/DELETE apply to related/target, not re-adding self.
        if action.op == "DELETE" and not action.target_id:
            action = ConsolidationAction(
                op="DELETE",
                text=text,
                target_id=fact.id,
                reason=action.reason or "self_obsolete",
            )
        if action.op == "UPDATE" and action.target_id == fact.id:
            # Replace self in place.
            action = ConsolidationAction(
                op="UPDATE",
                text=action.text or text,
                target_id=fact.id,
                reason=action.reason,
            )
        _apply_action(
            backend,
            action,
            metadata={"source": "consolidate_scan", "session_id": (fact.metadata or {}).get("session_id")},
            report=report,
        )
    return report
