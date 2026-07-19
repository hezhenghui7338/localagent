"""Slow-loop hypotheses from episodes → optional insight suggestions."""

from __future__ import annotations

import json
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from localagent import config
from localagent.aware.episode import AwareEpisode, load_episodes
from localagent.aware.timewin import day_part_label, dominant_day_part, period_label
from localagent.aware.types import utc_now


def _episode_day_part(episodes: list[AwareEpisode]) -> str:
    """Dominant day/night label weighted by duration."""
    stamps: list[str] = []
    for e in episodes:
        # Repeat start by duration buckets so longer sessions dominate.
        weight = max(1, int(e.duration_min // 15) + 1)
        for _ in range(min(weight, 8)):
            if e.start:
                stamps.append(e.start)
    return dominant_day_part(stamps) or day_part_label(
        episodes[0].start if episodes else ""
    )


@dataclass
class Hypothesis:
    id: str
    claim: str
    confidence: float
    scene: str
    kind: str  # interest|habit|wellness|social
    evidence: list[str] = field(default_factory=list)
    status: str = "pending"  # pending|accepted|rejected|decayed
    created_at: str = ""
    expires_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Hypothesis:
        return cls(
            id=str(raw.get("id") or ""),
            claim=str(raw.get("claim") or ""),
            confidence=float(raw.get("confidence") or 0),
            scene=str(raw.get("scene") or ""),
            kind=str(raw.get("kind") or "interest"),
            evidence=[str(x) for x in list(raw.get("evidence") or [])],
            status=str(raw.get("status") or "pending"),
            created_at=str(raw.get("created_at") or ""),
            expires_at=str(raw.get("expires_at") or ""),
        )


def _hypotheses_path() -> Path:
    return Path(getattr(config, "AWARE_DIR", Path("."))) / "hypotheses.json"


def _meta_path() -> Path:
    return Path(getattr(config, "AWARE_DIR", Path("."))) / "hypothesis_meta.json"


def load_hypotheses(*, status: str | None = "pending") -> list[Hypothesis]:
    path = _hypotheses_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[Hypothesis] = []
    now = datetime.now(timezone.utc)
    for row in items:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        h = Hypothesis.from_dict(row)
        if h.expires_at:
            try:
                exp = datetime.fromisoformat(h.expires_at.replace("Z", "+00:00"))
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp < now and h.status == "pending":
                    h.status = "decayed"
            except ValueError:
                pass
        if status is None or h.status == status:
            out.append(h)
    return out


def _atomic_write(items: list[Hypothesis]) -> None:
    config.ensure_data_dirs()
    path = _hypotheses_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updated_at": utc_now(), "items": [h.to_dict() for h in items]}
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


def save_hypotheses(items: list[Hypothesis]) -> None:
    _atomic_write(items)


def _last_run_at() -> datetime | None:
    path = _meta_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        ts = str(raw.get("last_run_at") or "")
        if not ts:
            return None
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _mark_run() -> None:
    config.ensure_data_dirs()
    path = _meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"last_run_at": utc_now()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def should_run_hypothesis_loop(*, min_interval_hours: float = 6.0) -> bool:
    last = _last_run_at()
    if last is None:
        return True
    return datetime.now(timezone.utc) - last >= timedelta(hours=min_interval_hours)


def generate_hypotheses_from_episodes(
    episodes: list[AwareEpisode],
) -> list[Hypothesis]:
    """Rule-based hypotheses (lightweight; no LLM required)."""
    if not episodes:
        return []
    out: list[Hypothesis] = []
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    # Music: long sessions or repeated entities
    music = [e for e in episodes if e.scene == "music"]
    if music:
        total = sum(e.duration_min for e in music)
        entities: list[str] = []
        for e in music:
            entities.extend(e.entities)
            mt = str(e.signals.get("media_title") or "")
            if mt:
                entities.append(mt)
        # unique preserve order
        seen: set[str] = set()
        uniq = []
        for x in entities:
            if x and x not in seen:
                seen.add(x)
                uniq.append(x)
        if total >= 30 or len(music) >= 2:
            part = _episode_day_part(music)
            when = f"{part}" if part else "近窗"
            claim = f"你{when}较长时间在听音乐"
            if uniq:
                claim += f"（如：{'、'.join(uniq[:3])}）"
            claim += "——可能是兴趣，也可能是工作时的专注配乐。"
            out.append(
                Hypothesis(
                    id=uuid.uuid4().hex[:12],
                    claim=claim,
                    confidence=0.55 if uniq else 0.45,
                    scene="music",
                    kind="interest",
                    evidence=[e.to_card_line() for e in music[:5]],
                    created_at=utc_now(),
                    expires_at=expires,
                )
            )

    coding = [e for e in episodes if e.scene == "coding"]
    if coding:
        total = sum(e.duration_min for e in coding)
        if total >= 60 or len(coding) >= 3:
            part = _episode_day_part(coding)
            when = f"{part}" if part else "近窗"
            out.append(
                Hypothesis(
                    id=uuid.uuid4().hex[:12],
                    claim=(
                        f"{when}写码/终端活动偏多（约 {total:.0f} 分钟），"
                        "注意休息眼睛与适时提交。"
                    ),
                    confidence=0.5,
                    scene="coding",
                    kind="habit",
                    evidence=[e.to_card_line() for e in coding[:5]],
                    created_at=utc_now(),
                    expires_at=expires,
                )
            )

    writing = [e for e in episodes if e.scene == "writing"]
    if writing:
        chars = sum(int(e.signals.get("chars_approx") or 0) for e in writing)
        if chars >= 500 or len(writing) >= 2:
            names = []
            for e in writing:
                names.extend(e.entities[:3])
            tip = "、".join(names[:3]) if names else "文档"
            part = _episode_day_part(writing)
            when = f"{part}" if part else "最近"
            out.append(
                Hypothesis(
                    id=uuid.uuid4().hex[:12],
                    claim=f"{when}在写/改文字内容（{tip}），要不要我帮你梳一版提纲？",
                    confidence=0.5,
                    scene="writing",
                    kind="interest",
                    evidence=[e.to_card_line() for e in writing[:5]],
                    created_at=utc_now(),
                    expires_at=expires,
                )
            )

    calls = [e for e in episodes if e.scene == "call"]
    if calls:
        total = sum(e.duration_min for e in calls)
        if total >= 45:
            part = _episode_day_part(calls)
            when = f"{part}" if part else "近窗"
            out.append(
                Hypothesis(
                    id=uuid.uuid4().hex[:12],
                    claim=f"{when}会议/通话约 {total:.0f} 分钟，会后写三条纪要会更轻松。",
                    confidence=0.48,
                    scene="call",
                    kind="habit",
                    evidence=[e.to_card_line() for e in calls[:5]],
                    created_at=utc_now(),
                    expires_at=expires,
                )
            )

    video = [e for e in episodes if e.scene in {"video", "movie"}]
    if video:
        total = sum(e.duration_min for e in video)
        ents = []
        for e in video:
            ents.extend(e.entities[:2])
        if total >= 40 or len(video) >= 2:
            part = _episode_day_part(video)
            per = period_label(video[0].start) if video else ""
            when = per or part or "近窗"
            claim = f"你{when}较长时间在看视频/影像"
            if ents:
                claim += f"（{('、'.join(ents[:3]))}）"
            claim += "，感兴趣的话可以记到片单。"
            out.append(
                Hypothesis(
                    id=uuid.uuid4().hex[:12],
                    claim=claim,
                    confidence=0.45,
                    scene=video[0].scene,
                    kind="interest",
                    evidence=[e.to_card_line() for e in video[:5]],
                    created_at=utc_now(),
                    expires_at=expires,
                )
            )

    return out[:3]


def _enqueue_insight(h: Hypothesis) -> str | None:
    from localagent.aware.suggestion import enqueue, load_suggestions

    # Cool-down: same claim pending
    for item in load_suggestions():
        if item.data.get("kind") == "insight" and item.title == h.claim[:80]:
            return None
    return enqueue(
        source="insight",
        title=h.claim[:80],
        rationale="依据近期 Episode；可在 aware> 里继续聊，或 approve 确认这条洞察。",
        suggested_cmd="# aware insight ack",
        risk="low",
        data={
            "kind": "insight",
            "hypothesis_id": h.id,
            "scene": h.scene,
            "confidence": h.confidence,
            "evidence": h.evidence[:5],
        },
    )


def run_hypothesis_loop(*, force: bool = False, since_hours: float = 24) -> list[Hypothesis]:
    """Generate/store hypotheses and enqueue insight suggestions when due."""
    if not force and not should_run_hypothesis_loop():
        return []
    since = datetime.now(timezone.utc) - timedelta(hours=max(1.0, since_hours))
    episodes = load_episodes(since=since, limit=80)
    fresh = generate_hypotheses_from_episodes(episodes)
    if not fresh:
        _mark_run()
        return []

    existing = load_hypotheses(status=None)
    pending_claims = {h.claim[:60] for h in existing if h.status == "pending"}
    added: list[Hypothesis] = []
    for h in fresh:
        key = h.claim[:60]
        if key in pending_claims:
            continue
        existing.append(h)
        added.append(h)
        pending_claims.add(key)
        try:
            _enqueue_insight(h)
        except Exception:
            pass
    by_id: dict[str, Hypothesis] = {h.id: h for h in existing if h.id}
    save_hypotheses(list(by_id.values())[-40:])
    _mark_run()
    return added
