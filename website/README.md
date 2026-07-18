# LocalAgent website

Static landing page for [https://localagent.zhenghui7338.workers.dev/](https://localagent.zhenghui7338.workers.dev/).

## Local preview

Open `index.html` in a browser, or serve the folder:

```bash
cd website
python3 -m http.server 8080
```

Then visit `http://127.0.0.1:8080`.

## Deploy on Cloudflare Workers

Current production URL:

**https://localagent.zhenghui7338.workers.dev/**

This site is a static asset Worker. Repo root `wrangler.jsonc` points `assets.directory` at `./website`.

### CLI

```bash
npx wrangler deploy
```

### Git / Dashboard

1. In [Cloudflare Dashboard](https://dash.cloudflare.com/) → **Workers & Pages** → connect the `hezhenghui7338/localagent` repository as a **Worker**.
2. Ensure the project uses the root `wrangler.jsonc` (no build command needed).
3. Deploy / push; Cloudflare will upload files under `website/`.

### Optional custom domain

1. Open the Worker → **Settings** → **Domains & Routes** (or **Custom domains**).
2. Add your domain (e.g. `localagent.dev`) and follow DNS / SSL prompts.
3. When ready, update README / `pyproject.toml` Homepage links to the custom domain.
