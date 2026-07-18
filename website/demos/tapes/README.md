# VHS tapes (optional)

Canonical demo content lives in [`../scenes.json`](../scenes.json).

Primary render path (no VHS required):

```bash
cd website/demos
python3 render_demos.py
```

If you have [VHS](https://github.com/charmbracelet/vhs) and `ffmpeg` installed, you can author `.tape` files here that mirror `scenes.json` and export MP4s into `../../assets/demos/`. Keep frame size **800×468** and dark theme so results match the site chrome.
