<p align="center">
  <img src="assets/logo.png" alt="LocalAgent" width="360">
</p>

<p align="center">
  <strong>Local First. Memory Forever. Actions Automated.</strong>
</p>

<p align="center">
  <a href="https://localagent.zhenghui7338.workers.dev/">Website</a> ·
  <b>English</b> · <a href="./README.zh-CN.md">中文</a>
</p>

# <img src="assets/logo-icon.png" alt="LA" width="36" valign="middle"> LocalAgent

> **Local AI that remembers and gets things done.**

## Quick start

Python 3.10+ · [pipx](https://pipx.pypa.io/) · current **v0.4.0**

```bash
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"
la
```

Have an API → `la config set-key openrouter sk-...` (or edit `~/.localagent/.env`)  
No API → `la setup -y` (Ollama + `qwen3.5:4b`)

Daily side-paths: `la summarize <path>` · `la news brief` · `la polish`  
Upgrade / dev / uninstall → [Install & upgrade](#install--upgrade)

## Requirements

- Python 3.10+
- **At least one model backend**: your own API (OpenRouter / OpenAI / Cursor, …) **or** a local model server
- **If you have no API**, [Ollama](https://ollama.com/) is recommended (default `qwen3.5:4b`; `la setup` can install — skippable)

## Features

Runs fully local by default; optional cloud and web. Details: [summarize · news · polish](#daily-essentials-summarize--news--polish).

| I want to… | How |
| --- | --- |
| Install once and chat | `la` / `la setup` · [Install & upgrade](#install--upgrade) |
| Hack on the source / run tests | [Developer install](#developer-install) |
| Use my own API keys | [Configuration](#configuration) · `la config` |
| Be remembered across sessions | Hot / Warm / Cold + Mem0; import ChatGPT via `LA memory ingest chatgpt` · [Product tour §3–4](examples/product-tour.md) |
| Put docs in a KB and recall deeply | `LA rag add` / `rag search` · [Product tour §5](examples/product-tour.md) |
| **Summarize** a doc (`sum>` dialogue by default) | `la summarize <path>`; `/keep` or `--keep` to archive; `--no-chat` for digest-only |
| **News sniff** / daily brief | `la news sync` → `la news brief` (TTY ↑↓ / `o` open / `r` deep-read); `la news schedule on` |
| **Polish** copy (clipboard by default) | `la polish` / `/polish` · `--scene` / `--tone` / `--no-copy` |
| Search the web | ddgs by default; `LA chat` or `/deepsearch` · [Product tour §6](examples/product-tour.md) |
| Local Shell / write files (dangerous ops blocked) | `run_shell` / `write_file`; approve before execute · [Actions](#actions-automated--shell-that-actually-acts) |
| See today’s action signals | `la status` |
| See tokens / cost | `LA audit` · [Product tour §8](examples/product-tour.md) |
| Switch models | Ollama / OpenRouter / Cursor; `auto` falls back by priority |

### Product design

1. **Local First** — zero-bill / zero-account default: chat, memory, retrieval, and tools run on-device; three-command main path (`la` · `la setup` · `la chat`); optional cloud/network — identity, memory, and audit stay local  
2. **Memory Forever** — Hot / Warm / Cold + Mem0 across sessions; knows what to keep, what to drop, and when to step in; local RAG + ChatGPT import; switch models, keep identity  
3. **Actions Automated** — Shell / write_file / workspace; `la summarize` · `la news` · `la polish`; scheduled brief; confirm before side effects, block danger, show a receipt when done; `la status` for today’s signals  

| Typical local chat | LocalAgent |
| --- | --- |
| Cloud bills and account friction | **Local First** — zero-cost Ollama default; bring your own API if you want |
| Forgets — or memorizes everything blindly | **Memory Forever** — layered memory with judgment + local RAG |
| Only talks; you still do the work | **Actions Automated** — tools, side-paths, schedule; confirm + hard blocks |

Optional OpenRouter / Cursor / Tavily — **identity and data stay on your machine**. Spec: [docs/PRD.md](docs/PRD.md); ~30-min tour: [examples/product-tour.md](examples/product-tour.md).

### TODO / Coming soon

- **Not in this release:** workspace file-watcher incremental indexing, external task sources, unattended scheduled Shell.

### What we believe

- AI is revolutionary — embrace it; hearing about it a thousand times beats nothing next to downloading LA and debugging it yourself  
- “Read it a hundred times and meaning appears” does not happen by itself — you need practice  
- LA only picks **low-hanging, mature** fruit; no uncontrolled, expensive, hard-to-own stacks  
- LA does **one thing**: local AI that remembers and gets things done. Data stays local; the full loop runs offline. Networking and new tech are welcome — barriers are not  
- Remove obstacles to using AI

## Install & upgrade

If GitHub is slow/blocked, use a proxy first (heavy deps; install can take a while).

```bash
# pin a tag (recommended)
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"
# or track default branch / use pip
# pipx install "git+https://github.com/hezhenghui7338/localagent.git"
# pip install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"

la --version
# upgrade to a new tag: uninstall then reinstall
pipx uninstall la-localagent
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"
# if --force fails with “venv already exists”: UV_VENV_CLEAR=1 pipx install --force "…"
# tracking default branch: pipx upgrade la-localagent
```

Versions: [Releases](https://github.com/hezhenghui7338/localagent/releases) / [Tags](https://github.com/hezhenghui7338/localagent/tags). First run creates `~/.localagent/`.

```bash
la                 # = la chat
la setup           # guided Ollama install (skippable)
la setup -y
la config --provider ollama --base_url "http://localhost:11434" --model qwen3.5:4b
# or: la config-example > my.json && la config my.json && la config list
```

> After PyPI publish: `pipx install la-localagent==0.4.0`

### Developer install

```bash
git clone git@github.com:hezhenghui7338/localagent.git
cd LocalAgent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# or: uv sync --extra dev
```

Source checkout: config/data in-repo (`.env`, `data/`). Normal install: `~/.localagent/`. Tests: [Development](#development).

### Uninstall

```bash
pipx uninstall la-localagent   # or: pip uninstall la-localagent
rm -rf ~/.localagent           # optional: wipe config/data; source install → clean `.env` / `data/` in-repo
ollama rm qwen3.5:4b           # optional: Ollama is separate and is not removed with LA
```

## Feature highlights

### Local First

LocalAgent’s core path — **chat, memory write, memory recall, document retrieval, workspace awareness, Shell execution, audit stats** — can run on local Ollama alone, with no paid API. Identity and data stay on your machine.

| Capability | Needs cloud API? | Notes |
| --- | --- | --- |
| Chat `LA chat` | No | Default `qwen3.5:4b`, runs on your machine |
| Single memory `LA memory add` | No | Local model extracts title/tags |
| Doc import `LA rag add` | No | Cold knowledge index only; no memory extraction |
| Memory/knowledge search `LA memory search` | No | BM25 + Chroma locally |
| Workspace `LA workspace` | No | Reads local Git / files / TODOs |
| Agent commands `run_shell` | No | Local 4B model calls shell and summarizes |
| Audit `LA audit` | No | Reads local usage.jsonl + events.jsonl |
| Diagnostic logs `LA logs` | No | Reads local `data/logs/localagent.log` |
| Web search | No (ddgs by default) | Works out of the box; optional Tavily / self-hosted SearXNG |

```bash
# Fully local: your machine + Ollama, no paid API
cp examples/env.local-only.example .env
ollama pull qwen3.5:4b
LA chat --provider ollama
```

### Actions Automated — Shell that actually acts

A typical chat only tells you to run `find … | wc -l` yourself. LocalAgent’s agent **calls `run_shell`**, executes in the workspace, and turns the output into an answer — fully local `qwen3.5:4b`, no cloud API.

```text
> count the lines of code in this project
[chat] thinking…
[chat] connecting model (auto(ollama→openrouter→aiping→cursor))…
[chat] generating…
[chat] calling run_shell: find . -type f \( -name "*.py" -o -name …
[chat] waiting for your approval…
⚠ Agent wants to run a command. Confirm before it executes.
Command: find . -type f \( -name "*.py" -o -name "*.js" \) …
Allow? [y/N] y
[chat] synthesizing tool results (round 2)…
[chat] ✓ synthesizing tool results (round 2)… (20.4s)
In the current project (`/Users/hzh/code/LocalAgent`), main language files (Python, JS, TS, Go, Java, C/C++, Rust, etc., excluding hidden dirs) total **13,961 lines**.
[via ollama/qwen3.5:4b]
```

Use cases: LOC counts, listing directories, Git logs, running tests/builds. Commands run in the workspace (`LA_WORKSPACE` or cwd); default timeout 30s. **Every shell/file write asks for approval by default**; `rm` / `sudo` / force-git and similar get an extra warning. Set `LA_TOOL_APPROVAL=dangerous` to only gate risky ops, or `off` to disable (not recommended).

### Daily essentials: summarize · news · polish

Three side-path commands built for **everyday** use — read a doc, skim a brief, polish a draft — without a long agent tool loop.

#### 1. One-click summarize — 3-minute digest + document dialogue

```bash
la summarize ~/Documents/plan.pdf          # digest card → sum> dialogue
la summarize notes.md --no-chat            # card only (multi-file ok)
la summarize report.xlsx --keep            # also archive to KB
```

- Output: up to three sentences + key points with 〔§section | p.page〕 cites
- **Not kept by default**; `/keep` in `sum>` or pass `--keep`
- Ask follow-ups in `sum>` (`/summary` re-show card, `/exit` leave)

#### 2. News sniff — trusted sources → today's brief

Default feed: [BestBlogs](https://www.bestblogs.dev/) AI RSS (override with `LA_NEWS_RSS_URL`):

```bash
la news sync
la news brief                  # TTY: interactive browser (recommended)
la news brief --no-ui          # dump all items at once
la news schedule on            # auto-sync at 08:00 (off to disable)
```

Keys in the interactive brief: ↑↓ navigate · `o` open in browser · `s` skim · `r` deep-read chat · `b`/`x`/`c` bookmark/skip/copy · `q` quit.

Chat startup notifies when today's sync is ready.

#### 3. One-click polish — rewrite ready to send

```bash
la polish "nudge about the proposal"
la polish --scene email --tone more-formal "…"
la polish --no-copy --file draft.txt
```

In-session: `/polish --scene email …`. Primary rewrite is copied to the clipboard by default; press `2`/`3` to copy an alternate. Resume mode never invents numbers not in the draft.

The repo includes a **product tour** (user-story driven, full I/O, ~30 min) and a shorter walkthrough:

| # | Scenario | Command |
| --- | --- | --- |
| 1 | Write & recall a single memory | `LA memory add` → `LA memory search` |
| 2 | Import & recall a Markdown file | `LA rag add` → `LA rag search` |
| 3 | **Summarize** a local doc | `la summarize <path>` → `sum>` |
| 4 | **News sniff** daily brief | `la news sync` → `la news brief` |
| 5 | **Polish** email / Moments draft | `la polish "draft"` / `/polish` |
| 6 | Search recent news online | `LA chat` or `/deepsearch` |
| 7 | **Fully local** qwen3.5:4b | `LA chat --provider ollama` |
| 8 | Agent runs terminal commands | `LA chat` → “count project LOC” |
| 9 | Audit report (Ollama $0) | `LA audit --since 7d` |

```bash
# Full product tour (recommended): user stories · complete input/output
open examples/product-tour.md
# Shorter walkthrough (English)
open examples/walkthrough.md
# Chinese walkthrough
open examples/walkthrough.zh-CN.md
```

Full narrative and acceptance criteria: [docs/PRD.md](docs/PRD.md).
### Memory Forever — remembers you end-to-end

Memory inputs include **ChatGPT history and LA live chats**. Personal documents use `LA rag` for Cold knowledge. The Warm layer is powered by the [Mem0](https://github.com/mem0ai/mem0) engine (`mem0ai` is a core dependency): **Retain → Recall → Reflect (search + LLM)**. The repo includes an “architecture decision evolution” narrative demo covering write, semantic recall, time awareness, tag browsing, and cross-memory reasoning:

```bash
# From a source checkout
pip install -e ".[dev]"

# One-shot demo (isolated under /tmp — does not touch data/)
bash examples/mem0-demo.sh

# Or read the step-by-step guide
open examples/mem0-demo.md
```

Demo highlights:

| Step | Command | Shows |
|------|---------|-------|
| Write evolution chain | `LA memory add` × 4 | Retain + auto title/tags/event time |
| Semantic recall | `LA memory search "memory engine choice"` | Mem0 semantic recall |
| Time awareness | `LA memory search "May 2026 decision"` | Re-rank by event time |
| Tag browse | `LA memory query --tag decision` | Structured query |
| Cross-memory reasoning | `LA memory reflect "how did the choice evolve?"` | Mem0 reflect |

**Where docs live**

| Directory | Purpose |
| --- | --- |
| [`examples/`](examples/) | Hands-on materials: tutorials, sample inputs/outputs, demo scripts, config templates |
| [`docs/`](docs/) | Design docs for contributors: [PRD](docs/PRD.md), [TDD](docs/TDD.md) |

`examples/` contents:

- [examples/product-tour.md](examples/product-tour.md) — **Product tour** (user stories · full I/O · ~30 min) · [中文](examples/product-tour.zh-CN.md)
- [examples/walkthrough.md](examples/walkthrough.md) — **step-by-step tutorial** (local qwen3.5:4b first) · [中文](examples/walkthrough.zh-CN.md)
- [examples/mem0-demo.md](examples/mem0-demo.md) / [mem0-demo.sh](examples/mem0-demo.sh) — Mem0 deep dive (Retain / Recall / Reflect)
- [examples/sample-project-notes.md](examples/sample-project-notes.md) — sample doc for `rag add`
- [examples/audit-report-sample.md](examples/audit-report-sample.md) — sample audit report (Ollama $0)
- [examples/env.local-only.example](examples/env.local-only.example) — fully local `.env` template
- [benchmarks/stm/README.md](benchmarks/stm/README.md) — **STM short-term memory benchmark** (CI-friendly)
- [benchmarks/locomo/README.md](benchmarks/locomo/README.md) — **LoCoMo long-term memory benchmark**

### Benchmark: short-term memory (STM)

Daily / same-session recall (history + today's conversations). Fast, no LLM required:

```bash
python -m benchmarks.stm
```

Details: [benchmarks/stm/README.md](benchmarks/stm/README.md).

### Benchmark: LoCoMo long-term conversational memory

Evaluate cross-session LTM with ACL 2024 [LoCoMo](https://github.com/snap-research/locomo).
**Primary metric = Joint Warm∪Cold evidence hit@k** (RRF fusion). Warm-only / Cold-only are diagnostics.
**Current Warm-only baseline (2026-07-14, `conv-26`, Mem0 hybrid + CE, n=150):** Hit@1 **0.433** / Hit@5 **0.627** / Hit@8 **0.673** — Joint baseline pending re-run (see HISTORY).

```bash
python -m benchmarks.locomo.run download
python -m benchmarks.locomo.measure_recall \
  --skip-ingest --sample-ids conv-26 \
  --work-dir benchmarks/data/runs/locomo-mem0 \
  --diagnostics --label joint
```

Per-category table and reproduction steps: [benchmarks/locomo/README.md](benchmarks/locomo/README.md). Historical runs: [benchmarks/locomo/HISTORY.md](benchmarks/locomo/HISTORY.md).

### Shell completion

Shell tab completion is installed automatically on the first `LA` run (writes `~/.zshrc` / `~/.bashrc` and hooks into `.venv/bin/activate`). After `source .venv/bin/activate` (or a new terminal), `LA memory` / `LA rag` + Tab suggests subcommands.

To reinstall or repair manually:

```bash
LA complete-init
source .venv/bin/activate   # or: source ~/.zshrc
```

### Ollama tips

- Default model is `qwen3.5:4b`. If it is missing, LA reuses any installed chat model (preferring one already loaded in Ollama), and only prompts to pull the default when none are available
- Qwen3 often emits many thinking tokens; LocalAgent defaults `OLLAMA_THINK=0` to disable thinking mode
- When local Ollama is slow, `auto` falls back to the next provider (e.g. OpenRouter) after **12s** by default. Override with `LA_OLLAMA_CHAT_TIMEOUT=20` in `.env`, or `chat_timeout: 20` under ollama in `config/model_servers.yaml`; or switch manually with `/provider openrouter`

## Configuration

See [`.env.example`](.env.example). Common variables:

| Variable | Description |
| --- | --- |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Local Ollama URL and model |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | OpenAI direct (or any compatible endpoint via `model_servers.yaml`) |
| `OPENROUTER_API_KEY` / `CURSOR_API_KEY` | Other cloud fallbacks |
| `TAVILY_API_KEY` | Optional; when set, `auto` prefers Tavily for web search |
| `LA_WEB_SEARCH_PROVIDER` | Web backend: `auto` (default) / `ddgs` / `tavily` / `searxng` |
| `LA_SEARXNG_URL` | Optional self-hosted SearXNG URL (e.g. `http://localhost:8080`) |
| `LA_OLLAMA_CHAT_TIMEOUT` | Local Ollama first-byte timeout in `auto` (default `12`; then fall back) |
| `LA_MODEL_PROVIDER_PRIORITY` | `auto` priority; default `ollama,openai,openrouter,cursor` |
| `LA_WORKSPACE` | Workspace root (Git / files / todos / shell context) |
| `LA_SHELL_TIMEOUT` / `LA_SHELL_MAX_OUTPUT` | Agent `run_shell` timeout (s) and output cap (default 30s / 12000 chars) |
| `LA_TOOL_APPROVAL` | Approve before tools run: `always` (default) / `dangerous` / `off` |
| `LA_DATA_DIR` | Custom data dir (for test isolation) |
| `LA_NEWS_RSS_URL` | News sniff RSS (default BestBlogs AI curated) |
| `LA_NEWS_AUTO_SYNC` / `_HOUR` | Morning auto-sync intent + hour (`la news schedule on`) |
| `LA_SUMMARIZE_SHORT_MAX_CHARS` | Summarize short-path char cap (default 12000) |
| `LA_LOG_LEVEL` | Diagnostic log level: `INFO` (default) / `DEBUG` / `WARNING` … |

## Commands

Daily use is chat-first. Outer commands and in-session `/command` share the same paths (e.g. `/memory add` ≡ `LA memory add`). Session-only shortcuts: `/add` → `memory add`, `/search` → `memory search` (`/chat` is rejected inside the session).

```bash
$ LA -h
```

```text
usage: LA [-h] <command> ...

LocalAgent — personal AI assistant on your machine

Main path:
  la / la chat     Chat
  la setup [-y]    Install/pull local Ollama model
  la config …      Local-only or bring-your-own API

Everyday:
  LA memory add|search|pending|approve|reject|forget
  LA memory ingest chatgpt <path>   # Import ChatGPT export
  LA rag add|search                 # Documents → Cold KB
  la summarize <path>               # One-click summarize → doc dialogue
  la news sync|brief|schedule       # News sniff / daily brief
  la polish "draft"                 # One-click polish (copies primary)
  LA audit                          # Spend / safety report

Maintenance (advanced):
  memory ingest chat|all · query · reflect · status · reindex · reset · graph
  rag ingest|rebuild|reset · tasks · workspace · logs · websearch
  news skim|read|mark|interests|status|sources
```

`LA logs` shows runtime diagnostics (`data/logs/localagent.log`) — provider fallbacks, memory recall hits, agent retries. This is separate from `LA audit` (usage/cost/guardrails). Use `LA --debug <command>` or `LA_LOG_LEVEL=DEBUG` to mirror DEBUG lines to stderr while developing.

Interactive input uses [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) (Unicode-safe editing / Tab completion; avoids macOS libedit CJK bugs).

## Data directory

Runtime data defaults to `data/` (gitignored — not committed):

```
data/
├── kb/                        # Symlinked personal files
├── core_profile.json          # Hot-layer core facts
├── news/                      # News sniff: articles.sqlite · profile · sync_state · cache/
├── sync_index.json            # Indexed file registry
├── conversations/             # Chat archives
├── chatGPTdata/               # ChatGPT export archive
├── chatgpt_import_index.json  # Import dedupe registry
├── sessions.db                # LangGraph sessions
├── chroma/                    # Vector index
├── bm25.pkl                   # BM25 index
├── task_logs/                 # Background ingest task logs
├── logs/
│   └── localagent.log         # Diagnostic log (LA logs / --debug)
└── audit/
    ├── usage.jsonl            # Model/search usage
    └── events.jsonl           # Tool decisions / guardrails
```

## Architecture

Narrative arc: **fully local (zero-cost by default)** → **truly easy** → **smart multi-layer memory** → **external tools** → **RAG**.

### System overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         LA CLI / chat REPL                       │
│                   slash commands · approval UI                   │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   LangGraph Agent     │
                    │  JIT tools · tool loop│
                    └───────────┬───────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
     ┌────────────────┐ ┌──────────────┐ ┌────────────────┐
     │  ModelRouter   │ │ Memory stack │ │ Action surface │
     │ Ollama → cloud │ │ Hot/Warm/Cold│ │ web · shell ·  │
     │ (auto fallback)│ │              │ │ write_file     │
     └────────────────┘ └──────┬───────┘ └────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
           Hot              Warm             Cold
     core_profile.json    Mem0 (+ JSON     Chroma + BM25
     (pinned facts)       fallback)        (+ RRF hybrid)
                          conversations    data/kb/ docs
```

### Request path (`LA chat`)

```
user message
    │
    ▼
Agent loop
    ├─ preload JIT context when useful (profile / memory / web / workspace)
    ├─ model call via ModelRouter
    ├─ tool calls (search_memory, search_knowledge, web_search,
    │              workspace_context, retain_memory, write_file, run_shell, …)
    ├─ compress observations (heuristic; LA_OBSERVE_BUDGET_CHARS) before feedback
    ├─ approval gate for write_file / run_shell   ← LA_TOOL_APPROVAL
    └─ synthesize answer (+ source links for web)
```

### Three-layer memory

| Layer | Store | Role | Written by |
| --- | --- | --- | --- |
| **Hot** | `core_profile.json` | Always-on identity / pinned facts | Profile pin / explicit core updates |
| **Warm** | Mem0 (default) or JSON `memory_store` (+ optional SQLite relation graph) | Long-term conversational **facts** | ChatGPT / LA chat extract · `memory add` / `retain_memory` |
| **Cold** | Chroma + BM25 (+ RRF) | Searchable source material (docs, conversation archives) | `LA rag add` / `rag ingest` (kb/) · `memory ingest chat|chatgpt` / session exit (summary + body chunks) |

Warm holds durable facts about *you*. Cold holds **retrievable originals**: personal documents plus LA/ChatGPT transcripts (with a summary chunk for large chats). Warm extract failure no longer discards the transcript — Cold still indexes it. Use `LA rag search` / `search_knowledge` for archive text; `LA memory search` for facts.

`LA rag rebuild` re-indexes `kb/` **and** conversation archives into Cold. `LA memory reset chat|chatgpt` also removes the matching Cold conversation chunks.

#### Optional Warm relation graph (off by default)

Code path is kept; **default is off** (`LA_MEMORY_GRAPH=0`). Day-to-day quality comes from hybrid recall + cross-encoder (`pip install 'la-localagent[rerank]'`), not the graph.

| | |
| --- | --- |
| What | Local SQLite `data/memory_graph.db` — entity/slot edges + dialog `NEXT_TURN`; 1–2 hop pool expansion |
| Why optional | Fair LoCoMo runs show only small Hit@5/8 gains while Hit@1 stays flat; adds a second CE pass (latency) |
| When to enable | Experiments on multi-hop / relationship questions after `LA memory graph rebuild` |
| CLI | `LA memory graph stats` · `LA memory graph rebuild` |

Enable only when needed:

```bash
# .env
LA_MEMORY_GRAPH=1
LA_MEMORY_GRAPH_BOOST=0
LA_MEMORY_GRAPH_PROTECT_TOP=1
LA_MEMORY_GRAPH_FORCE_IN_TOP=3
LA_MEMORY_RERANK_BACKEND=cross_encoder   # required for fair ranking

LA memory graph rebuild
```

#### Optional Neo4j precise queries (off by default)

For **counts, aggregations, and formal multi-hop**, LA can replace text retrieval with a structured Cypher query that returns a **computed** result (not a sampled answer). This is independent of the SQLite hop-expand graph above.

| | |
| --- | --- |
| What | Neo4j (or `LA_NEO4J_URI=memory://` in-process) + Cypher templates |
| When | 「how many / list all / mentioned together」 style questions |
| Agent tool | `query_memory_graph` (do not estimate numbers via `search_memory`) |
| CLI | `LA memory graph neo4j stats\|rebuild` · `LA memory graph query "…"` |
| Install | `pip install 'la-localagent[neo4j]'` |

```bash
# .env
LA_NEO4J=1
LA_NEO4J_URI=bolt://localhost:7687   # or memory:// for local experiments
# LA_NEO4J_USER=neo4j
# LA_NEO4J_PASSWORD=password

LA memory graph neo4j rebuild
LA memory graph query "How many times was Caroline mentioned?"
```

Open-ended semantic questions still use Warm hybrid recall / Cold RAG.

### Warm memory pipeline (Retain → Recall → Reflect → Consolidate)

```
Write path                          Read path
─────────                           ─────────
ChatGPT export / LA chats           query
        │                              │
        ├─► Cold: summary + body       ├─► Warm hybrid recall (facts)
        │   chunks (always)            └─► Cold hybrid (docs + archives)
        ▼
extract + enrich (Warm facts)
(title / tags / entities /
 event time / value filter)
        │
        ▼
Consolidation → Mem0 / JSON
```

- **Retain**: extract durable facts from conversations; enrich metadata; optional consolidation against near-duplicates. Transcripts are also indexed into Cold so missing facts still leave searchable archives.
- **Recall**: Warm hybrid retrieval for facts; Cold hybrid (`rag search` / `search_knowledge`) for kb docs and conversation body/summary chunks with provenance metadata
- **Reflect**: multi-hop loop — recall → decide follow-up queries → synthesize (`LA memory reflect` / agent `reflect_memory`)
- **Hot injection**: core profile is merged into answers so identity survives model switches

### Agent tools & safety

| Surface | Tools | Notes |
| --- | --- | --- |
| Profile / memory | `search_memory`, `query_memories`, `retain_memory`, `reflect_memory` | JIT Warm + Hot |
| Documents / archives | `search_knowledge` | Cold hybrid (kb + chat + ChatGPT); falls back to raw `kb/` text on miss |
| Internet | `web_search`, `/deepsearch` | Default **ddgs**; optional Tavily / SearXNG |
| Machine | `workspace_context`, `run_shell`, `write_file` | Workspace-scoped; shell/write need approval |

Side-effect tools are gated (`always` / `dangerous` / `off`). Extreme commands (e.g. `rm -rf /`) are blocked outright.

### Model routing

`ModelRouter` unifies **Ollama** (default local), **OpenAI**, **OpenRouter**, and **Cursor**. In `auto` mode it follows `LA_MODEL_PROVIDER_PRIORITY` and falls back when a path is slow or unavailable. Models are compute providers; LocalAgent owns sessions, memory, and audit data on disk.

### Module map (source)

```
src/localagent/
├── cli.py / chat_repl.py / session_commands.py   # CLI + REPL + /commands
├── agent/           # Agent runtime + Observe compression
├── models/          # ModelRouter (local → cloud fallback)
├── memory/          # Hot profile · Warm backends · recall/reflect/consolidate
├── knowledge/       # Cold Chroma + BM25 + RRF
├── ingest/          # rag add/ingest pipeline (Cold only)
├── tools/           # Agent tools + approval
├── workspace/       # Git / recent files / todos
├── persist/         # conversations · sessions · ChatGPT archives
└── audit/           # usage · security scan · reports
```

Design docs (not end-user tutorials): [docs/PRD.md](docs/PRD.md) and [docs/TDD.md](docs/TDD.md). Hands-on walkthroughs live under [`examples/`](examples/).

## Development

GitHub Actions CI runs `uv run pytest` (unit + integration, including STM; excludes `e2e` / `e2e_live`) and a separate **e2e-offline** job (`pytest tests/e2e -m e2e`). Live Ollama tests stay local-only.

```bash
# Unit + integration tests (temp dirs; no Ollama required; includes STM)
pytest

# End-to-end: subprocess LA commands (also run in CI e2e-offline job)
pytest tests/e2e -m e2e

# Live Ollama chat (needs a pulled chat model locally)
pytest tests/e2e -m e2e_live
```

## Security & privacy

- **Never commit** `.env` or runtime data under `data/`; both are gitignored
- API keys live only in local `.env`
- Memories and chat archives stay on-device by default — not uploaded
- **Local execution gate**: `run_shell` / `write_file` require your confirmation by default (`LA_TOOL_APPROVAL=always`); dangerous commands get an extra warning. Extremely destructive commands (e.g. `rm -rf /`) are blocked outright. Non-interactive runs without an approval callback are denied
- If a key was ever exposed elsewhere, rotate it on that platform immediately

## License

MIT
