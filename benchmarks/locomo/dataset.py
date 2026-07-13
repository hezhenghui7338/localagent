"""LoCoMo dataset download and helpers."""

from __future__ import annotations

import json
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
            },
        }

    for session_num, date_time, turns in iter_sessions(conversation):
        for turn in turns:
            text = format_turn(turn, date_time=date_time, session_num=session_num)
            yield {
                "text": text,
                "metadata": {
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
                },
            }


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
