"""Managed workspace task queue — sparse, reasoned, expiring action items."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from localagent import config
from localagent.i18n import t

TaskSource = Literal["user", "agent", "import"]
TaskStatus = Literal["open", "snoozed", "done", "dismissed", "expired"]

_TERMINAL = frozenset({"done", "dismissed", "expired"})
_TITLE_NORM = re.compile(r"\s+")


def _resolve_root(workspace: Path | None = None) -> Path:
    """Local resolve to avoid circular import with workspace.context."""
    if workspace is not None:
        return Path(workspace).expanduser().resolve()
    env = os.getenv("LA_WORKSPACE", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd().resolve()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        text = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_title(title: str) -> str:
    return _TITLE_NORM.sub(" ", (title or "").strip().lower())


@dataclass
class WorkspaceTask:
    id: str
    title: str
    rationale: str
    source: str = "user"
    status: str = "open"
    created_at: str = ""
    expires_at: str = ""
    snooze_until: str = ""
    reminded_at: str = ""
    complete_hint: str = ""
    evidence: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WorkspaceTask:
        return cls(
            id=str(raw.get("id") or ""),
            title=str(raw.get("title") or ""),
            rationale=str(raw.get("rationale") or ""),
            source=str(raw.get("source") or "user"),
            status=str(raw.get("status") or "open"),
            created_at=str(raw.get("created_at") or ""),
            expires_at=str(raw.get("expires_at") or ""),
            snooze_until=str(raw.get("snooze_until") or ""),
            reminded_at=str(raw.get("reminded_at") or ""),
            complete_hint=str(raw.get("complete_hint") or ""),
            evidence=str(raw.get("evidence") or ""),
            data=dict(raw.get("data") or {}),
        )


class TaskRejected(ValueError):
    """Raised when a task fails creation gates."""


def _workspace_key(root: Path) -> str:
    resolved = str(root.expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def _tasks_file() -> Path:
    return Path(config.WORKSPACE_TASKS_FILE)


def _load_raw() -> dict[str, Any]:
    path = _tasks_file()
    if not path.exists():
        return {"updated_at": "", "by_workspace": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"updated_at": "", "by_workspace": {}}
    if not isinstance(raw, dict):
        return {"updated_at": "", "by_workspace": {}}
    buckets = raw.get("by_workspace")
    if not isinstance(buckets, dict):
        raw["by_workspace"] = {}
    return raw


def _atomic_write(payload: dict[str, Any]) -> None:
    config.ensure_data_dirs()
    path = _tasks_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = _utc_now_iso()
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        suffix=".tmp",
    ) as tmp:
        tmp.write(json.dumps(payload, ensure_ascii=False, indent=2))
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _bucket_items(raw: dict[str, Any], key: str) -> list[WorkspaceTask]:
    buckets = raw.get("by_workspace") or {}
    bucket = buckets.get(key) if isinstance(buckets, dict) else None
    if not isinstance(bucket, dict):
        return []
    items = bucket.get("items")
    if not isinstance(items, list):
        return []
    out: list[WorkspaceTask] = []
    for row in items:
        if isinstance(row, dict) and row.get("id"):
            out.append(WorkspaceTask.from_dict(row))
    return out


def _save_bucket(root: Path, items: list[WorkspaceTask]) -> None:
    raw = _load_raw()
    key = _workspace_key(root)
    buckets = dict(raw.get("by_workspace") or {})
    buckets[key] = {
        "workspace": str(root.resolve()),
        "items": [i.to_dict() for i in items],
    }
    raw["by_workspace"] = buckets
    _atomic_write(raw)


def _refresh_lifecycle(items: list[WorkspaceTask], *, now: datetime | None = None) -> bool:
    """Apply snooze wake-up and TTL expiry. Returns True if any status changed."""
    now = now or _utc_now()
    changed = False
    for item in items:
        if item.status == "snoozed":
            until = _parse_ts(item.snooze_until)
            if until is not None and until <= now:
                item.status = "open"
                item.snooze_until = ""
                changed = True
        if item.status == "open":
            expires = _parse_ts(item.expires_at)
            if expires is not None and expires <= now:
                item.status = "expired"
                changed = True
    return changed


def load_tasks(workspace: Path | None = None, *, refresh: bool = True) -> list[WorkspaceTask]:
    root = _resolve_root(workspace)
    raw = _load_raw()
    items = _bucket_items(raw, _workspace_key(root))
    if refresh and _refresh_lifecycle(items):
        _save_bucket(root, items)
    return items


def list_open(
    workspace: Path | None = None,
    *,
    include_snoozed: bool = False,
) -> list[WorkspaceTask]:
    items = load_tasks(workspace)
    if include_snoozed:
        return [i for i in items if i.status in ("open", "snoozed")]
    return [i for i in items if i.status == "open"]


def task_count_open(workspace: Path | None = None) -> int:
    return len(list_open(workspace))


def get_task(task_id: str, workspace: Path | None = None) -> WorkspaceTask | None:
    tid = (task_id or "").strip()
    if not tid:
        return None
    for item in load_tasks(workspace):
        if item.id == tid or item.id.startswith(tid):
            return item
    return None


def _validate_create(title: str, rationale: str) -> tuple[str, str]:
    title = (title or "").strip()
    rationale = (rationale or "").strip()
    min_title = max(1, int(config.WORKSPACE_TASK_MIN_TITLE_LEN))
    min_why = max(1, int(config.WORKSPACE_TASK_MIN_RATIONALE_LEN))
    if len(title) < min_title:
        raise TaskRejected(t("workspace.reject_title", n=min_title))
    if len(rationale) < min_why:
        raise TaskRejected(t("workspace.reject_rationale", n=min_why))
    return title, rationale


def _agent_created_today(items: list[WorkspaceTask], now: datetime) -> int:
    day = now.date()
    n = 0
    for item in items:
        if item.source != "agent":
            continue
        created = _parse_ts(item.created_at)
        if created is not None and created.date() == day:
            n += 1
    return n


def _find_active_duplicate(
    items: list[WorkspaceTask],
    title: str,
) -> WorkspaceTask | None:
    """Block re-adding while an open/snoozed twin exists."""
    norm = _normalize_title(title)
    for item in items:
        if item.status in ("open", "snoozed") and _normalize_title(item.title) == norm:
            return item
    return None


def add_task(
    title: str,
    rationale: str,
    *,
    source: TaskSource = "user",
    workspace: Path | None = None,
    complete_hint: str = "",
    evidence: str = "",
    ttl_days: int | None = None,
    data: dict[str, Any] | None = None,
) -> WorkspaceTask:
    """Create a managed task. Raises TaskRejected on gate failure."""
    title, rationale = _validate_create(title, rationale)
    if source not in ("user", "agent", "import"):
        raise TaskRejected(t("workspace.reject_source", source=source))

    root = _resolve_root(workspace)
    items = load_tasks(root)
    now = _utc_now()
    dup = _find_active_duplicate(items, title)
    if dup is not None:
        raise TaskRejected(t("workspace.reject_dup", id=dup.id, title=dup.title))

    if source == "agent":
        # Also block recent identical titles (any status) within 7 days for agent spam.
        norm = _normalize_title(title)
        cutoff = now - timedelta(days=7)
        for item in items:
            if _normalize_title(item.title) != norm:
                continue
            created = _parse_ts(item.created_at)
            if created is not None and created >= cutoff:
                raise TaskRejected(
                    t("workspace.reject_recent", id=item.id, title=item.title)
                )
        limit = max(0, int(config.WORKSPACE_TASK_AGENT_DAILY_LIMIT))
        if _agent_created_today(items, now) >= limit:
            raise TaskRejected(t("workspace.reject_daily", limit=limit))

    days = int(config.WORKSPACE_TASK_TTL_DAYS if ttl_days is None else ttl_days)
    days = max(1, days)
    task = WorkspaceTask(
        id=uuid.uuid4().hex[:8],
        title=title,
        rationale=rationale,
        source=source,
        status="open",
        created_at=now.isoformat(),
        expires_at=(now + timedelta(days=days)).isoformat(),
        complete_hint=(complete_hint or "").strip(),
        evidence=(evidence or "").strip(),
        data=dict(data or {}),
    )
    items.append(task)
    _save_bucket(root, items)
    return task


def propose_task(
    title: str,
    rationale: str,
    *,
    workspace: Path | None = None,
    complete_hint: str = "",
    evidence: str = "",
    data: dict[str, Any] | None = None,
) -> WorkspaceTask:
    """Agent-gated create: major issues only, daily cap + dedup."""
    return add_task(
        title,
        rationale,
        source="agent",
        workspace=workspace,
        complete_hint=complete_hint,
        evidence=evidence,
        data=data,
    )


def _set_status(
    task_id: str,
    status: TaskStatus,
    *,
    workspace: Path | None = None,
    snooze_until: str = "",
) -> WorkspaceTask | None:
    root = _resolve_root(workspace)
    items = load_tasks(root)
    tid = (task_id or "").strip()
    target: WorkspaceTask | None = None
    for item in items:
        if item.id == tid or item.id.startswith(tid):
            target = item
            break
    if target is None:
        return None
    target.status = status
    if status == "snoozed":
        target.snooze_until = snooze_until
    else:
        target.snooze_until = ""
    _save_bucket(root, items)
    return target


def done(task_id: str, *, workspace: Path | None = None) -> WorkspaceTask | None:
    return _set_status(task_id, "done", workspace=workspace)


def dismiss(task_id: str, *, workspace: Path | None = None) -> WorkspaceTask | None:
    return _set_status(task_id, "dismissed", workspace=workspace)


def snooze(
    task_id: str,
    *,
    days: int = 1,
    workspace: Path | None = None,
) -> WorkspaceTask | None:
    days = max(1, int(days))
    until = (_utc_now() + timedelta(days=days)).isoformat()
    return _set_status(task_id, "snoozed", workspace=workspace, snooze_until=until)


def purge(
    workspace: Path | None = None,
    *,
    older_than_days: int | None = None,
) -> int:
    """Remove terminal tasks. Optionally only those older than N days."""
    root = _resolve_root(workspace)
    items = load_tasks(root)
    now = _utc_now()
    kept: list[WorkspaceTask] = []
    removed = 0
    cutoff = None
    if older_than_days is not None and older_than_days > 0:
        cutoff = now - timedelta(days=int(older_than_days))
    for item in items:
        if item.status not in _TERMINAL:
            kept.append(item)
            continue
        if cutoff is not None:
            created = _parse_ts(item.created_at) or _parse_ts(item.expires_at)
            if created is not None and created > cutoff:
                kept.append(item)
                continue
        removed += 1
    if removed:
        _save_bucket(root, kept)
    return removed


def mark_reminded(task_ids: list[str], *, workspace: Path | None = None) -> None:
    root = _resolve_root(workspace)
    items = load_tasks(root)
    id_set = set(task_ids)
    now = _utc_now_iso()
    changed = False
    for item in items:
        if item.id in id_set:
            item.reminded_at = now
            changed = True
    if changed:
        _save_bucket(root, items)


def remind_due(
    workspace: Path | None = None,
    *,
    limit: int = 2,
) -> list[WorkspaceTask]:
    """Open tasks prioritized for surfacing (soonest expiry first)."""
    items = list_open(workspace)
    items.sort(key=lambda t: t.expires_at or "9999")
    return items[: max(0, limit)]


def format_task_line(task: WorkspaceTask, *, verbose: bool = True) -> str:
    exp = ""
    expires = _parse_ts(task.expires_at)
    if expires is not None:
        exp = expires.strftime("%m-%d")
    base = f"[{task.id}] {task.title}"
    if exp:
        base += t("workspace.line_expires", exp=exp)
    if task.source and task.source != "user":
        base += f"  ·{task.source}"
    if not verbose:
        return base
    lines = [base, t("workspace.line_why", rationale=task.rationale)]
    if task.complete_hint:
        lines.append(t("workspace.line_hint", hint=task.complete_hint))
    if task.evidence:
        lines.append(t("workspace.line_evidence", evidence=task.evidence))
    lines.append(t("workspace.line_actions", id=task.id))
    return "\n".join(lines)


def format_open_tasks(
    workspace: Path | None = None,
    *,
    limit: int = 20,
    verbose: bool = True,
) -> str:
    root = _resolve_root(workspace)
    items = list_open(root)[:limit]
    if not items:
        return t("workspace.open_empty", root=root)
    lines = [
        t(
            "workspace.open_header",
            count=len(list_open(root)),
            shown=len(items),
        )
    ]
    for item in items:
        lines.append(format_task_line(item, verbose=verbose))
    return "\n".join(lines)


def format_tasks_for_summary(workspace: Path | None = None, *, limit: int = 10) -> str:
    """Compact block for workspace summary / agent context."""
    root = _resolve_root(workspace)
    open_items = list_open(root)
    if not open_items:
        return t("workspace.summary_empty")
    shown = min(limit, len(open_items))
    lines = [t("workspace.summary_header", count=len(open_items), shown=shown)]
    for item in open_items[:limit]:
        hint = f" — {item.complete_hint}" if item.complete_hint else ""
        lines.append(f"  - [{item.id}] {item.title}{hint}")
        lines.append(t("workspace.line_why", rationale=item.rationale))
    if len(open_items) > limit:
        lines.append(t("workspace.summary_more", count=len(open_items)))
    else:
        lines.append(t("workspace.summary_actions"))
    return "\n".join(lines)
