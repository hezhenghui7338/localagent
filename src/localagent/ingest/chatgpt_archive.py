"""Archive ChatGPT exports into the canonical data/chatGPTdata/ directory."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from localagent import config


def archive_chatgpt_export(path: Path) -> Path:
    """Copy ``path`` into ``CHATGPT_DATA_DIR`` when not already archived.

    Returns the path under the archive directory (or the original if already there).
    """
    config.ensure_data_dirs()
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"file not found: {source}")

    dest_dir = config.CHATGPT_DATA_DIR.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        if source.parent.resolve() == dest_dir or dest_dir in source.parents:
            return source
    except OSError:
        pass

    dest = dest_dir / source.name
    if dest.exists():
        try:
            if dest.resolve() == source:
                return dest
            if dest.read_bytes() == source.read_bytes():
                return dest
        except OSError:
            pass
        digest = hashlib.sha256(source.read_bytes()).hexdigest()[:8]
        dest = dest_dir / f"{source.stem}_{digest}{source.suffix}"

    shutil.copy2(source, dest)
    return dest
