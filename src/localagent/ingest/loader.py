"""Document loaders for supported kb/ file types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from localagent import config
from localagent.config import IMAGE_SUFFIXES, SUPPORTED_SUFFIXES


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


def _load_pdf(path: Path) -> tuple[str, dict]:
    """Extract text per page; inject ## [p.N] markers for citeable summarize."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts: list[str] = []
    page_count = len(reader.pages)
    non_empty = 0
    for index, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        text = raw.strip()
        if not text:
            continue
        non_empty += 1
        parts.append(f"## [p.{index}]\n{text}")
    meta = {"page_count": page_count, "pages_with_text": non_empty}
    return "\n\n".join(parts), meta


def load_file(path: Path) -> LoadedDoc | None:
    path = Path(path)
    if not path.exists() or not path.is_file():
        return None

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return None

    extra_meta: dict = {}
    if suffix in {".md", ".markdown", ".txt"}:
        text = _load_txt(path)
    elif suffix == ".xlsx":
        text = _load_xlsx(path)
    elif suffix == ".pdf":
        text, extra_meta = _load_pdf(path)
    elif suffix in IMAGE_SUFFIXES:
        if not config.VL_ENABLED:
            return None
        from localagent.ingest.vision import caption_image

        text = caption_image(path)
    else:
        return None

    text = text.strip()
    if not text:
        return None

    modified_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    metadata = {"suffix": suffix, "modified_at": modified_at, **extra_meta}

    return LoadedDoc(
        text=text,
        source=str(path.resolve()),
        filename=path.name,
        metadata=metadata,
    )
