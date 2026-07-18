#!/usr/bin/env bash
# Regenerate website demo MP4s + posters from scenes.json.
set -euo pipefail
cd "$(dirname "$0")"

python3 - <<'PY'
import importlib.util
missing = [m for m in ("PIL", "imageio", "numpy") if importlib.util.find_spec(m) is None]
if missing:
    raise SystemExit(
        "Missing packages: "
        + ", ".join(missing)
        + '\nInstall with: python3 -m pip install pillow imageio imageio-ffmpeg numpy'
    )
PY

python3 render_demos.py "$@"
ls -lh ../assets/demos/*.{mp4,jpg} 2>/dev/null || true
