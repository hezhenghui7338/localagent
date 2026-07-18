# LocalAgent website

Static landing page for [https://localagent.zhenghui7338.workers.dev/](https://localagent.zhenghui7338.workers.dev/).

## Sections

- **Hero / Features / Install / Contact** — brand + pillars + quick start
- **Demo (`#demo`)** — three wow-moments (setup / memory / deep-read). Default is **step-through terminal**; optional **Video** mode lazy-loads short MP4 clips (EN + ZH). Deep links: `#demo-setup`, `#demo-memory`, `#demo-deepread`

## Local preview

Open `index.html` in a browser, or serve the folder:

```bash
cd website
python3 -m http.server 8080
```

Then visit `http://127.0.0.1:8080`.

## Regenerate demo videos

- **`assets/demos/`** — shipped short clips (`{setup,memory,deepread}.{en,zh}.mp4` + `.poster.jpg`). Target ~800×468, ~8–12s; the page only fetches an MP4 after **Video**.
- **`/demos/`** — render toolchain (`scenes.json`, `render_demos.py`). Ignored by Cloudflare via `.assetsignore` (`/demos/` only — do not use bare `demos/`, or `assets/demos/` will be excluded too).

Source of truth for terminal content: [`demos/scenes.json`](demos/scenes.json).

```bash
# once: python3 -m pip install pillow imageio imageio-ffmpeg numpy
cd website/demos
./render.sh
# or: python3 render_demos.py
# or only one: python3 render_demos.py --only setup.en
```

Optional [VHS](https://github.com/charmbracelet/vhs) stubs live under `demos/tapes/`; keep output size **800×468** to match the site.

## Deploy on Cloudflare Pages / Workers

Current production URL:

**https://localagent.zhenghui7338.workers.dev/**

Typical Pages setup:

1. In [Cloudflare Dashboard](https://dash.cloudflare.com/) → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**.
2. Select the `hezhenghui7338/localagent` repository.
3. Build settings:
   - **Framework preset**: None
   - **Build command**: leave empty
   - **Build output directory**: `website`
4. Save and deploy. Cloudflare will republish on pushes to the connected branch.

### Optional custom domain

1. Open the Pages project → **Custom domains** → **Set up a custom domain**.
2. Add your domain (e.g. `localagent.dev`) and follow DNS / SSL prompts.
3. When ready, update README / `pyproject.toml` Homepage links to the custom domain.
