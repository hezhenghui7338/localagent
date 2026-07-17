# LocalAgent website

Static landing page for [localagent.dev](https://localagent.dev).

## Local preview

Open `index.html` in a browser, or serve the folder:

```bash
cd website
python3 -m http.server 8080
```

Then visit `http://127.0.0.1:8080`.

## Deploy on Cloudflare Pages

1. In [Cloudflare Dashboard](https://dash.cloudflare.com/) → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**.
2. Select the `hezhenghui7338/localagent` repository.
3. Build settings:
   - **Framework preset**: None
   - **Build command**: leave empty
   - **Build output directory**: `website`
4. Save and deploy. Cloudflare will republish on pushes to the connected branch.

### Custom domain `localagent.dev`

1. Open the Pages project → **Custom domains** → **Set up a custom domain**.
2. Add `localagent.dev` (and optionally `www.localagent.dev`).
3. If the domain is already on Cloudflare DNS, accept the suggested DNS records.
4. If DNS is elsewhere, either move nameservers to Cloudflare or add the CNAME / A records Cloudflare shows.
5. Wait for SSL to become **Active**, then open https://localagent.dev.

No GitHub Actions are required; Cloudflare’s Git integration handles deploys.
