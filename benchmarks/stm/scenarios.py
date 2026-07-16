"""STM scenario runners: routing / in-session / same-day / priority / hot."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "cases.json"


def load_cases(path: Path | str | None = None) -> dict[str, Any]:
    fixture = Path(path) if path else DEFAULT_FIXTURE
    data = json.loads(fixture.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected object fixture in {fixture}")
    return data


def _contains(haystack: str, needle: str) -> bool:
    return needle.casefold() in haystack.casefold()


def _format_history(history: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for msg in history:
        role = "用户" if msg.get("role") == "user" else "助手"
        content = (msg.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _seed_session(
    session_id: str,
    messages: list[dict[str, str]],
    *,
    day_offset: int = 0,
    hour_offset: float | None = None,
) -> None:
    """Write a conversation relative to now for the STM rolling window.

    Prefer ``hour_offset`` (hours from now). Legacy ``day_offset``:
    0 → 1h ago (inside default 24h window); negative → 48h * |offset| ago
    (outside the default window).
    """
    from localagent.persist.conversations import (
        _append_to_mapping,
        _empty_conversation,
        _save_raw,
    )

    now = datetime.now(tz=timezone.utc)
    if hour_offset is not None:
        base = now + timedelta(hours=float(hour_offset))
    elif day_offset >= 0:
        base = now - timedelta(hours=1)
    else:
        base = now - timedelta(hours=48.0 * abs(day_offset))
    data = _empty_conversation(session_id, now=base.timestamp())
    for index, msg in enumerate(messages):
        ts = (base + timedelta(minutes=index)).timestamp()
        _append_to_mapping(
            data,
            role=str(msg.get("role") or "user"),
            content=str(msg.get("content") or ""),
            create_time=ts,
        )
    _save_raw(session_id, data)


def run_routing(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from localagent.agent.runtime import is_archive_recall_query, is_session_recall_query

    rows: list[dict[str, Any]] = []
    for case in cases:
        query = str(case.get("query") or "")
        expect = str(case.get("expect") or "")
        is_session = is_session_recall_query(query)
        is_archive = is_archive_recall_query(query)
        if expect == "session":
            ok = is_session and not is_archive
            actual = "session" if is_session else ("archive" if is_archive else "neither")
        elif expect == "archive":
            ok = is_archive and not is_session
            actual = "archive" if is_archive else ("session" if is_session else "neither")
        else:
            ok = (not is_session) and (not is_archive)
            actual = "session" if is_session else ("archive" if is_archive else "neither")
        rows.append(
            {
                "query": query,
                "expect": expect,
                "actual": actual,
                "ok": ok,
            }
        )
    return rows


def run_in_session(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """S1: gold evidence/answer must remain visible in injected history (no Warm/Cold)."""
    rows: list[dict[str, Any]] = []
    for case in cases:
        history = list(case.get("history") or [])
        context = _format_history(history)
        evidence = [str(x) for x in (case.get("gold_evidence") or [])]
        gold = str(case.get("gold_answer") or "")
        coverage = all(_contains(context, ev) for ev in evidence) if evidence else bool(context)
        answer_hit = bool(gold) and _contains(context, gold)
        rows.append(
            {
                "id": case.get("id"),
                "gold_answer": gold,
                "context_coverage": coverage,
                "answer_hit": answer_hit,
                "context_chars": len(context),
            }
        )
    return rows


def run_same_day(cases: list[dict[str, Any]], *, work_dir: Path) -> list[dict[str, Any]]:
    """S2: STM-window transcripts via _prefetch_session_context; outside window excluded."""
    from benchmarks.locomo.runtime import configure_data_dir
    from localagent.agent.runtime import (
        _prefetch_archive_context,
        _prefetch_session_context,
        is_archive_recall_query,
        is_session_recall_query,
    )

    rows: list[dict[str, Any]] = []
    for case in cases:
        case_dir = work_dir / str(case.get("id") or "same_day")
        configure_data_dir(case_dir)
        for session in case.get("sessions") or []:
            hour_raw = session.get("hour_offset")
            _seed_session(
                str(session["session_id"]),
                list(session.get("messages") or []),
                day_offset=int(session.get("day_offset") or 0),
                hour_offset=float(hour_raw) if hour_raw is not None else None,
            )
        query = str(case.get("query") or "")
        routed_session = is_session_recall_query(query)
        routed_archive = is_archive_recall_query(query)
        session_ctx = _prefetch_session_context(query, history=None, session_id=None)
        archive_ctx = _prefetch_archive_context(query)

        must_include = [str(x) for x in (case.get("gold_must_include") or [])]
        must_exclude = [str(x) for x in (case.get("gold_must_exclude") or [])]
        include_ok = all(_contains(session_ctx, x) for x in must_include)
        exclude_ok = all(not _contains(session_ctx, x) for x in must_exclude)
        session_hit = (
            routed_session
            and not routed_archive
            and include_ok
            and exclude_ok
            and bool(session_ctx.strip())
        )
        rows.append(
            {
                "id": case.get("id"),
                "query": query,
                "routed_session": routed_session,
                "routed_archive": routed_archive,
                "session_hit": session_hit,
                "include_ok": include_ok,
                "exclude_ok": exclude_ok,
                "archive_polluted": bool(archive_ctx.strip()),
                "context_preview": session_ctx[:400],
            }
        )
    return rows


def run_priority(cases: list[dict[str, Any]], *, work_dir: Path) -> list[dict[str, Any]]:
    """S3: today's transcript wins over stale Warm facts.

    Writes stale Warm facts via the JSON store only (no embedding/rerank path)
    so the STM suite stays CI-fast.
    """
    from benchmarks.locomo.runtime import configure_data_dir
    from localagent.agent.runtime import (
        _prefetch_session_context,
        is_session_recall_query,
    )
    from localagent.memory.backend import reset_memory_backend
    from localagent.memory.store import get_memory_store, reset_memory_store_singleton

    rows: list[dict[str, Any]] = []
    for case in cases:
        case_dir = work_dir / str(case.get("id") or "priority")
        configure_data_dir(case_dir)
        reset_memory_backend()
        reset_memory_store_singleton()
        sid = str(case.get("today_session_id") or "s-today")
        _seed_session(sid, list(case.get("today_messages") or []), day_offset=0)

        stale = str(case.get("stale_warm_fact") or "")
        if stale:
            store = get_memory_store()
            store.retain_from_section(
                filename="stm-stale",
                heading="stale",
                text=stale,
                chunk_id="stale-1",
                extra_metadata={"source": "stm-stale", "kind": "fact"},
            )
            store.save()

        query = str(case.get("query") or "")
        session_ctx = _prefetch_session_context(query, history=None, session_id=sid)
        warm_text = "\n".join(f.text for f in get_memory_store().all_facts())

        correct = str(case.get("gold_correct") or "")
        stale_token = str(case.get("gold_stale") or "")
        in_session = _contains(session_ctx, correct)
        stale_in_warm = bool(stale_token) and _contains(warm_text, stale_token)
        # Priority win: session path active + correct fact present in STM context.
        priority_win = is_session_recall_query(query) and in_session
        rows.append(
            {
                "id": case.get("id"),
                "query": query,
                "priority_win": priority_win,
                "correct_in_session": in_session,
                "stale_in_warm": stale_in_warm,
                "session_preview": session_ctx[:400],
            }
        )
    return rows


def run_hot_profile(cases: list[dict[str, Any]], *, work_dir: Path) -> list[dict[str, Any]]:
    """Hot-layer aux: pinned profile fields survive load/save."""
    from benchmarks.locomo.runtime import configure_data_dir
    from localagent.memory.core_profile import (
        CoreProfile,
        load_core_profile,
        save_core_profile,
    )

    rows: list[dict[str, Any]] = []
    for case in cases:
        case_dir = work_dir / str(case.get("id") or "hot")
        configure_data_dir(case_dir)
        pins = case.get("pins") or {}
        expect = case.get("expect") or pins
        profile = CoreProfile(
            name=str(pins.get("name") or ""),
            preferences={str(k): str(v) for k, v in dict(pins.get("preferences") or {}).items()},
            updated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        )
        save_core_profile(profile)
        loaded = load_core_profile()
        name_ok = loaded.name == str(expect.get("name") or "")
        pref_expect = {str(k): str(v) for k, v in dict(expect.get("preferences") or {}).items()}
        pref_ok = all(loaded.preferences.get(k) == v for k, v in pref_expect.items())
        rows.append(
            {
                "id": case.get("id"),
                "profile_hit": name_ok and pref_ok,
                "name_ok": name_ok,
                "preferences_ok": pref_ok,
                "loaded": loaded.to_dict(),
            }
        )
    return rows


def run_all(cases: dict[str, Any], *, work_dir: Path) -> dict[str, Any]:
    import os

    # Keep the whole STM suite off Mem0/embedder so CI stays seconds-fast.
    os.environ["LA_MEMORY_BACKEND"] = "json"
    try:
        from localagent import config as _cfg

        _cfg.MEMORY_BACKEND = "json"
    except Exception:
        pass

    work_dir.mkdir(parents=True, exist_ok=True)
    return {
        "routing": run_routing(list(cases.get("routing") or [])),
        "in_session": run_in_session(list(cases.get("in_session") or [])),
        "same_day": run_same_day(list(cases.get("same_day") or []), work_dir=work_dir / "same_day"),
        "priority": run_priority(list(cases.get("priority") or []), work_dir=work_dir / "priority"),
        "hot_profile": run_hot_profile(
            list(cases.get("hot_profile") or []),
            work_dir=work_dir / "hot",
        ),
    }
