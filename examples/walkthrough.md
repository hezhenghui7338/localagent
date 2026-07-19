# LocalAgent feature walkthrough

> **Local First. Memory Forever. Actions Automated.** — Local AI that remembers and gets things done.

Short scenarios for a **fast path** (Local → Memory → Actions), including the daily trio (summarize · news · polish). Full user stories live in [product-tour.md](product-tour.md) (Chinese: [product-tour.zh-CN.md](product-tour.zh-CN.md)). Sample data is fictional and safe to reproduce.

Chinese version: [walkthrough.zh-CN.md](walkthrough.zh-CN.md).

**Prerequisites:**

```bash
# 1. Install LocalAgent (global `la` command)
pipx install "git+https://github.com/hezhenghui7338/localagent.git"
# Or from source: pip install -e ".[dev]"

# 2. First `la` / `la setup` asks whether to install Ollama and pull a RAM-matched model (you can skip)
la setup
# Or non-interactive: la setup -y

# 3. Optional pure-local config
# Normal install: edit ~/.localagent/.env or:
#   la config --provider ollama --base_url "http://localhost:11434" --model qwen3.5:4b
# Source checkout: cp examples/env.local-only.example .env
```

---

## Highlight: Local First

LocalAgent’s core path — **chat, memory write, memory recall, document retrieval, workspace awareness, audit** — can run on local Ollama alone, with no paid API. Use `la status` / `/status` for today’s signals and data layers (Hot/Warm/Cold/Aware).

| Capability | Needs cloud API? | Notes |
| --- | --- | --- |
| Chat `LA chat` | No | Default `qwen3.5:4b`, runs on your machine |
| Single memory `LA ingest text` | No | Local model extracts title/tags |
| Doc import `LA ingest doc` | No | Heuristic extract by default; no LLM required |
| Memory search `LA memory search` | No | BM25 + Chroma locally |
| Workspace `LA workspace` | No | Reads local Git / files / TODOs |
| Aware `la aware` | No (local model optional) | Default: current state + last 3h activity; `--detail` for per-source dump |
| Audit `LA audit` | No | Reads local usage.jsonl |
| Summarize `la summarize` | No (local model) | Digest card + `sum>` dialogue |
| News sniff `la news` | Network only for sync | RSS → brief; deep-read can summarize locally |
| Polish `la polish` | No (local model) | Scene rewrite + clipboard |
| Web search | No (ddgs by default) | Works out of the box; optional Tavily / SearXNG |

```bash
# Force pure-local chat (no cloud fallback)
LA chat --provider ollama
```

**Not in this release:** workspace file-watcher incremental indexing, and external task sources.

---

## 1. Remember one fact, then recall it

Good for a single decision, preference, or plan.

```bash
LA ingest text "In July 2026 we decided to add an examples/ directory so new users can get started quickly"

LA memory search "examples directory"
```

**Expected recall:**

```text
[search] retrieving: examples directory
Found 1 related memory (query: examples directory)

### 1. Add examples directory
relevance 0.82 · 2026-07-11 · fact · #docs/LocalAgent

In July 2026 we decided to add an examples/ directory so new users can get started quickly

source: LA ingest text · id: a1b2c3d4
→ LA memory forget <id>  to delete a memory
```

In `LA chat` you can also ask naturally; the agent JIT-recalls as needed:

```text
you> What did I decide about examples earlier?
assistant> In July 2026 you decided to add an examples/ directory so new users can get started quickly.
```

---

## 2. Add a Markdown file to the knowledge base

Good for project notes, journals, and long docs. Files are symlinked into `data/kb/` and indexed into **Cold** only (no Warm fact extraction).

```bash
LA ingest doc examples/sample-project-notes.md

LA rag search "three-layer memory"
```

**Expected (`ingest doc`):**

```text
[ingest doc] source=doc · cold=5 · warm=0 · files=1
[ingest doc] archived: data/kb/sample-project-notes.md
```

**Expected (knowledge search):**

```text
[rag search] knowledge: three-layer memory
--- result 1 (score=0.91) ---
source: sample-project-notes.md · architecture
LocalAgent uses Hot / Warm / Cold memory:
- Hot: core_profile.json for pinned profile
- Warm: long-term facts (Mem0)
- Cold: Chroma + BM25 hybrid retrieval
```

---

## 3. Search the web for recent news

> **No API key by default**: uses open-source `ddgs`. If `TAVILY_API_KEY` is set, `auto` prefers Tavily. Or self-host SearXNG with `LA_SEARXNG_URL`.

```bash
# Optional higher quality
TAVILY_API_KEY=tvly-xxx

# Or force free / self-hosted
# LA_WEB_SEARCH_PROVIDER=ddgs
# LA_SEARXNG_URL=http://localhost:8080
```

**A — Ask in chat** (agent calls `web_search`):

```bash
LA chat --provider ollama
```

```text
you> What were 3 important AI news items in the past week? Keep it brief.
assistant> [calls web_search → summarizes]
      1. ...
      2. ...
      3. ...
```

**B — Deep research**

```text
you> /deepsearch July 2026 open-source LLM releases
assistant> [multi-step search + local model synthesis]
```

Web results stay in the turn context and are **not** auto-saved to long-term memory.

---

## 4. Local model on your machine

`la setup` picks a model by system RAM when none is configured (override with `OLLAMA_MODEL`). Recommended settings (also in `examples/env.local-only.example`):

```bash
OLLAMA_MODEL=qwen3.5:4b           # or whatever la setup recommended
OLLAMA_THINK=0                    # disable thinking to avoid long waits
LA_MODEL_PROVIDER_PRIORITY=ollama # do not fall back to cloud
```

**RAM → recommended model** (used by `la setup` when nothing is configured):

| System RAM | Model | Notes |
| --- | --- | --- |
| &lt; 6 GB | `qwen3.5:0.8b` (Mini) | Basic chat; weak multi-tool Agent |
| 6–10 GB | `qwen3.5:2b` | Lightweight Q&A |
| 10–18 GB | `qwen3.5:4b` | Default quality tier |
| ≥ 18 GB | `qwen3.5:9b` | High-RAM quality tier |

```bash
ollama run qwen3.5:4b "Hello — introduce yourself in one sentence"

LA chat --provider ollama
```

---

## 5. Answer questions about local work

LocalAgent can see recent files, Git status, and TODO comments — without uploading code to the cloud.

```bash
LA workspace --cwd .

# Opt-in sensing: overview → aware>; grant apps for focus / Now Playing
la aware grant fs terminal browser apps -y
la aware tick --no-chat
la aware --no-chat
la aware

LA chat --cwd . --provider ollama
```

**Expected (`workspace`):**

```text
Workspace: /Users/you/code/localagent
Files changed in last 7 days:
  - 2026-07-11 17:40  README.md
  - 2026-07-11 17:37  examples/walkthrough.md
  - 2026-07-11 16:20  src/localagent/cli.py

Git branch: main
Working tree: clean

Todos (2, showing first 10):
  - [checkbox] examples/sample-project-notes.md:28  add examples directory
  - [todo] examples/sample-project-notes.md:29  support more doc formats
```

```text
you> What did I change recently in this project? Any todos?
assistant> [calls workspace_context]
      In the last 7 days you edited README.md, examples/walkthrough.md, …
      Working tree is clean on main.
      Two todos: add examples directory; support more doc formats.
```

---

## 6. Audit spend (Ollama is $0)

Every model call is logged to `data/audit/usage.jsonl`. Estimated cost for Ollama is always **$0**.

```bash
LA audit --since 7d

LA audit --since 7d --report examples/my-audit.md
```

**Expected summary:**

```text
[audit] summary (7d)
  calls: 47  tokens: 31,280  est. cost: $0.0200
    ollama: 42 calls, 28,450 tokens, $0.0000
    tavily: 5 calls, 0 tokens, $0.0500

file safety: no high-risk items
memory health: facts=12

→ LA audit --report report.md  for a full report
```

Sample report: [audit-report-sample.md](audit-report-sample.md).

- `ollama` line: **$0.0000** — local chat and memory, zero bill
- `tavily` / `ddgs` / `searxng`: web search; ddgs/searxng are free; only Tavily bills

---

## 7. Daily trio: summarize · news · polish

### Summarize

```bash
la summarize examples/sample-project-notes.md
# sum> What is the core decision in this note?
# sum> /exit
```

### News sniff

```bash
la news sync
la news brief --no-ui --limit 5    # use --no-ui for scripts; omit on TTY for interactive UI
```

### Polish

```bash
la polish --no-copy --scene email "Hi — could you send the proposal this week?"
```

---

## One-shot demo (optional)

Uses an isolated data dir so you do not touch daily `data/`:

```bash
export LA_DATA_DIR=/tmp/la-demo
pip install -e ".[dev]" -q

LA ingest text "In July 2026 we decided to add an examples/ directory"
LA memory search "examples"
LA ingest doc examples/sample-project-notes.md
LA rag search "three-layer memory"
LA workspace --cwd .
LA audit --since 7d

echo "Done. Data under $LA_DATA_DIR"
```

---

## Next steps

- Import your own Markdown: `LA ingest doc ~/Documents/notes.md`
- Import ChatGPT history: `LA ingest chatgpt conversations.json`
- Design docs: [docs/PRD.md](../docs/PRD.md) · [docs/TDD.md](../docs/TDD.md)
