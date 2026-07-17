# LocalAgent website

Static landing page for [https://localagent.zhenghui7338.workers.dev/](https://localagent.zhenghui7338.workers.dev/).

## Local preview

Open `index.html` in a browser, or serve the folder:

```bash
cd website
python3 -m http.server 8080
```

Then visit `http://127.0.0.1:8080`.

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
