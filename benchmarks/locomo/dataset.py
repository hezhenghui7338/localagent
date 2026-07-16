"""LoCoMo dataset download and helpers."""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Iterator

LOCOMO_DATA_URL = (
    "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
)
DEFAULT_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "locomo10.json"


def download_locomo(*, dest: Path | None = None, force: bool = False) -> Path:
    """Download official locomo10.json if missing."""
    path = dest or DEFAULT_DATA_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return path
    with urllib.request.urlopen(LOCOMO_DATA_URL, timeout=120) as resp:
        payload = resp.read()
    path.write_bytes(payload)
    return path


def load_samples(path: Path | str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected a list of conversations in {path}")
    return data


def iter_sessions(conversation: dict[str, Any]) -> Iterator[tuple[int, str, list[dict[str, Any]]]]:
    """Yield (session_num, date_time, turns) in chronological order."""
    session_nums = sorted(
        int(key.split("_")[-1])
        for key in conversation
        if key.startswith("session_") and not key.endswith("_date_time")
    )
    for num in session_nums:
        turns = conversation.get(f"session_{num}") or []
        if not isinstance(turns, list) or not turns:
            continue
        date_time = str(conversation.get(f"session_{num}_date_time") or "")
        yield num, date_time, turns


def format_turn(
    turn: dict[str, Any],
    *,
    date_time: str,
    session_num: int,
) -> str:
    """Serialize one dialog turn into a retainable memory string."""
    speaker = str(turn.get("speaker") or "Speaker")
    text = str(turn.get("text") or "").strip()
    dia_id = str(turn.get("dia_id") or "")
    caption = str(turn.get("blip_caption") or "").strip()
    parts = [
        f"[session={session_num} date={date_time} dia_id={dia_id}]",
        f'{speaker} said, "{text}"',
    ]
    if caption:
        parts.append(f"and shared an image described as: {caption}")
    return " ".join(parts)


def _locomo_occurred_at(date_time: str) -> str | None:
    """Parse LoCoMo session timestamps into ISO dates for temporal recall."""
    from localagent.memory.temporal import extract_occurred_at

    return extract_occurred_at(date_time)


def _dialog_entities_and_slots(
    *,
    speaker: str,
    utterance: str,
    caption: str = "",
) -> tuple[list[str], dict[str, str]]:
    """Rule-based entities + slots for graph-friendly Warm metadata."""
    from localagent.memory.entities import extract_entities

    _SKIP = frozenset(
        {
            "session",
            "yesterday",
            "today",
            "tomorrow",
            "good",
            "hey",
            "thanks",
            "yeah",
            "okay",
            "ok",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        }
    )
    blob = " ".join(part for part in (utterance, caption) if part).strip()
    extracted = []
    for ent in extract_entities(blob, limit=10):
        if len(ent) > 40:
            continue
        lower = ent.casefold()
        if lower in _SKIP or lower.startswith("hey "):
            continue
        # Drop date-like fragments (e.g. "8 May, 2023").
        if re.search(r"\d{4}|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", ent, re.I):
            continue
        # Drop almost-full-sentence extractions.
        if " " in ent and len(ent.split()) >= 6:
            continue
        extracted.append(ent)
    entities: list[str] = []
    seen: set[str] = set()
    for name in ([speaker] if speaker else []) + extracted:
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        entities.append(name)

    slots = {
        "subject": speaker or "",
        "action": "",
        "object": "",
        "location": "",
    }
    for name in entities:
        if name.casefold() == (speaker or "").casefold():
            continue
        slots["object"] = name
        break
    return entities[:8], slots


def format_session_summary(
    *,
    session_num: int,
    date_time: str,
    turns: list[dict[str, Any]],
) -> str:
    """Compact session-level Warm fact for multi-hop / list questions."""
    from localagent.memory.entities import extract_entities

    speakers: list[str] = []
    dia_ids: list[str] = []
    corpus_parts: list[str] = []
    for turn in turns:
        speaker = str(turn.get("speaker") or "").strip()
        if speaker and speaker not in speakers:
            speakers.append(speaker)
        dia = str(turn.get("dia_id") or "").strip()
        if dia:
            dia_ids.append(dia)
        text = str(turn.get("text") or "").strip()
        caption = str(turn.get("blip_caption") or "").strip()
        if text:
            corpus_parts.append(text)
        if caption:
            corpus_parts.append(caption)

    topics = [
        e
        for e in extract_entities(" ".join(corpus_parts), limit=12)
        if len(e) <= 40 and e not in speakers
    ]
    topic_bit = ", ".join(topics[:8]) if topics else "(general chat)"
    dia_bit = ", ".join(dia_ids[:24]) if dia_ids else "none"
    speaker_bit = " and ".join(speakers) if speakers else "speakers"
    return (
        f"[session={session_num} date={date_time} kind=session_summary] "
        f"{speaker_bit} discussed: {topic_bit}. "
        f"Dialog turns: {dia_bit}."
    )


def iter_memory_items(sample: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield structured memory items for ingest."""
    conversation = sample["conversation"]
    sample_id = str(sample.get("sample_id") or "unknown")
    speaker_a = conversation.get("speaker_a")
    speaker_b = conversation.get("speaker_b")
    if speaker_a or speaker_b:
        yield {
            "text": (
                f"This is a long-term conversation between {speaker_a} and {speaker_b}. "
                f"sample_id={sample_id}"
            ),
            "metadata": {
                "source": "locomo",
                "sample_id": sample_id,
                "kind": "conversation_meta",
                "source_file": f"locomo:{sample_id}",
                "section_heading": "locomo",
                "entities": [n for n in (speaker_a, speaker_b) if n],
            },
        }

    for session_num, date_time, turns in iter_sessions(conversation):
        occurred = _locomo_occurred_at(date_time)
        summary_text = format_session_summary(
            session_num=session_num,
            date_time=date_time,
            turns=turns,
        )
        summary_entities: list[str] = []
        for turn in turns:
            speaker = str(turn.get("speaker") or "").strip()
            if speaker and speaker not in summary_entities:
                summary_entities.append(speaker)
        summary_meta: dict[str, Any] = {
            "source": "locomo",
            "sample_id": sample_id,
            "kind": "session_summary",
            "session": session_num,
            "date_time": date_time,
            "source_file": f"locomo:{sample_id}:s{session_num}:summary",
            "section_heading": f"session_{session_num}_summary",
            "chunk_id": f"s{session_num}-summary",
            "entities": summary_entities,
            "slots": {
                "subject": summary_entities[0] if summary_entities else "",
                "action": "discussed",
                "object": "",
                "location": "",
            },
        }
        if occurred:
            summary_meta["occurred_at"] = occurred
        yield {"text": summary_text, "metadata": summary_meta}

        for turn in turns:
            text = format_turn(turn, date_time=date_time, session_num=session_num)
            speaker = str(turn.get("speaker") or "").strip()
            utterance = str(turn.get("text") or "").strip()
            caption = str(turn.get("blip_caption") or "").strip()
            entities, slots = _dialog_entities_and_slots(
                speaker=speaker,
                utterance=utterance,
                caption=caption,
            )
            metadata: dict[str, Any] = {
                "source": "locomo",
                "sample_id": sample_id,
                "kind": "dialog",
                "session": session_num,
                "date_time": date_time,
                "dia_id": turn.get("dia_id"),
                "speaker": turn.get("speaker"),
                "source_file": f"locomo:{sample_id}:s{session_num}",
                "section_heading": f"session_{session_num}",
                "chunk_id": str(turn.get("dia_id") or f"s{session_num}"),
                "entities": entities,
                "slots": slots,
            }
            if occurred:
                metadata["occurred_at"] = occurred
            yield {
                "text": text,
                "metadata": metadata,
            }


def format_sample_cold_markdown(sample: dict[str, Any]) -> str:
    """Markdown transcript for Cold RAG indexing (preserves dia_id)."""
    conversation = sample["conversation"]
    sample_id = str(sample.get("sample_id") or "unknown")
    speaker_a = conversation.get("speaker_a") or "A"
    speaker_b = conversation.get("speaker_b") or "B"
    lines: list[str] = [
        f"# LoCoMo {sample_id}",
        "",
        f"Speakers: {speaker_a}, {speaker_b}",
        "",
    ]
    for session_num, date_time, turns in iter_sessions(conversation):
        lines.append(f"## Session {session_num} · {date_time}")
        lines.append("")
        for turn in turns:
            speaker = str(turn.get("speaker") or "Speaker")
            dia_id = str(turn.get("dia_id") or "")
            text = str(turn.get("text") or "").strip()
            caption = str(turn.get("blip_caption") or "").strip()
            lines.append(f"### {dia_id} · {speaker}")
            lines.append("")
            lines.append(text)
            if caption:
                lines.append("")
                lines.append(f"(image: {caption})")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def filter_samples(
    samples: list[dict[str, Any]],
    *,
    sample_ids: list[str] | None = None,
    max_samples: int | None = None,
) -> list[dict[str, Any]]:
    selected = samples
    if sample_ids:
        wanted = set(sample_ids)
        selected = [s for s in selected if s.get("sample_id") in wanted]
    if max_samples is not None:
        selected = selected[: max(0, max_samples)]
    return selected
