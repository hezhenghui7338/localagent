"""Document loaders for supported kb/ file types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from localagent.config import SUPPORTED_SUFFIXES


@dataclass
class LoadedDoc:
    text: str
    source: str
    filename: str
    metadata: dict = field(default_factory=dict)


def _load_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _load_xlsx(path: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    parts: list[str] = []
    for sheet in wb.worksheets:
        parts.append(f"## Sheet: {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                parts.append(" | ".join(cells))
    wb.close()
    return "\n".join(parts)


def load_file(path: Path) -> LoadedDoc | None:
    path = Path(path)
    if not path.exists() or not path.is_file():
        return None

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return None

    if suffix in {".md", ".markdown", ".txt"}:
        text = _load_txt(path)
    elif suffix == ".xlsx":
        text = _load_xlsx(path)
    else:
        return None

    text = text.strip()
    if not text:
        return None

    modified_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")

    return LoadedDoc(
        text=text,
        source=str(path.resolve()),
        filename=path.name,
        metadata={"suffix": suffix, "modified_at": modified_at},
    )
