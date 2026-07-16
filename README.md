<a id="english"></a>

<p align="center">
  <img src="assets/logo.png" alt="LocalAgent" width="360">
</p>

<p align="center">
  <strong>Your AI. Your Data. Your Machine.</strong>
</p>

<p align="center">
  <b>English</b> · <a href="#zh-cn">中文</a>
</p>

# <img src="assets/logo-icon.png" alt="LA" width="36" valign="middle"> LocalAgent

> **Fully local · Truly easy · Knows you long-term — a personal AI hub on your machine; data and compute stay on-device by default.**

LocalAgent (`LA`) is not another chat client. It is a **personal AI hub on your machine**. Requirements live in [docs/PRD.md](docs/PRD.md); a ~30-minute runnable story is in [examples/product-tour.md](examples/product-tour.md).

### Product design

1. **Fully local** — zero-bill / zero-account default path: chat, memory, retrieval, and execution run on-device; identity and data stay local; compute defaults to local, with optional cloud/network extras — a pure-local path always remains  
2. **Truly easy** — one-command install, ready immediately; daily path is just `la` / `la setup` / `la chat` — less is more  
3. **Long-term, multi-layer memory** — Hot / Warm / Cold + Mem0: remember you, and decide what to keep, what to drop, and when to step in  
4. **External tools** — local Shell, write_file, workspace awareness; approve before side effects; block dangerous commands; audit cost and behavior  
5. **RAG** — local documents into a knowledge base; deep recall during chat

| Typical local chat | LocalAgent |
| --- | --- |
| Cloud bills and account friction | **Zero-cost local default** (Ollama); bring your own API if you want |
| Too many commands after install | **Three-command main path**: `la` · `la setup` · `la chat` |
| Forgets — or memorizes everything blindly | **Multi-layer memory** that knows you and prioritizes |
| Can't act or search | **Local tools** + optional web search |
| Docs and chats are separate silos | **RAG** + conversation archives for deep recall |

Optional OpenRouter / Cursor / Tavily for extras — **identity and data stay on your machine**.

**Not in this release:** workspace file-watcher incremental indexing, and external task sources.

### User stories

| I want to… | Where |
| --- | --- |
| Install once and chat | [User install](#user-install-recommended) |
| Hack on the source / run tests | [Developer install](#developer-install) |
| Run with my own API keys | [Configuration](#configuration) · `la config` |
| Be profiled and remembered across sessions | [Mem0 long-term memory](#mem0-long-term-memory--remembers-you-end-to-end) · [Product tour §3](examples/product-tour.md) |
| Search the web | [Feature highlights](#feature-highlights) · [Product tour §6](examples/product-tour.md) |
| Use local Shell / write files | [Local Shell](#local-execution--shell-that-actually-acts) · [Product tour §7](examples/product-tour.md) |
| Import ChatGPT history so LA knows me faster | `LA memory ingest chatgpt` · [Product tour §4](examples/product-tour.md) |
| Have dangerous commands blocked | [Agent tools & safety](#agent-tools--safety) · [Product tour §7](examples/product-tour.md) |
| See token / cost spend | `LA audit` · [Product tour §8](examples/product-tour.md) |
| Put local docs in a KB and recall deeply | `LA rag add` · [Product tour §5](examples/product-tour.md) |

### What we believe

- AI is revolutionary — embrace it; hearing about it a thousand times beats nothing next to downloading LA and debugging it yourself  
- “Read it a hundred times and meaning appears” does not happen by itself — you need practice  
- LA only picks **low-hanging, mature** fruit; no uncontrolled, expensive, hard-to-own stacks  
- LA does **one thing**: a personal AI hub on your machine. Data stays local; the full loop runs offline. Networking and new tech are welcome — barriers are not  
- Remove obstacles to using AI; the author is still learning too — let's grow together  

```bash
# First-time install (pin a tag — reproducible and easier to debug)
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"
# Already installed: uninstall + reinstall is most reliable. If uv says the venv exists, set UV_VENV_CLEAR=1.
la --version                    # expect: la-localagent 0.4.0
la                              # asks before installing Ollama (you can skip)
```

## Features

- **Fully local**: default `qwen3.5:4b` — chat, memory write, retrieval, workspace awareness, and Shell execution all run on-device; optional cloud models, data still owned locally
- **Truly easy**: main path `la` / `la setup` / `la chat`; advanced power via subcommands without blocking daily use
- **Long-term multi-layer memory**: Hot (core profile) / Warm (facts) / Cold (docs + conversation archives) with JIT recall
- **Mem0 + conversation memory**: ChatGPT history and LA chats → Warm facts **and** Cold searchable archives; docs via `LA rag` into Cold
- **External tools + safety**: workspace + `run_shell` + write_file; approve before execute; hard-block dangerous commands; write-file hallucination detection
- **Web search**: ddgs by default (no key); optional Tavily / SearXNG
- **Document knowledge base (RAG)**: symlink personal files; Chroma + BM25 hybrid search
- **Multi-model chat**: unified Ollama / OpenRouter / Cursor entry; `auto` mode falls back by priority
- **Auditable**: tokens/cost, agent behavior, guardrail blocks, sensitive-file scan — exportable Markdown reports

## Requirements

- Python 3.10+ (Mem0 memory engine needs Python 3.10+)
- [Ollama](https://ollama.com/) + `qwen3.5:4b` (recommended; also the project default)
- Optional: [pipx](https://pipx.pypa.io/) (recommended for a global `la` command)

## Quick start

### User install (recommended)

Current release: **v0.4.0** (same as `src/localagent/__init__.py` / `la --version`).

**Faster setup**: always pin a tag (e.g. `@v0.4.0`) instead of tracking the default branch tip; if upgrading, `pipx uninstall` then reinstall is more reliable than wrestling with `--force`.

```bash
# Install a pinned tag (recommended, reproducible)
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"

# Or track the default branch tip (no version pin)
pipx install "git+https://github.com/hezhenghui7338/localagent.git"

# Or with pip into the current environment
pip install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"
```

Check version and upgrade:

```bash
la --version                  # or la -V → la-localagent 0.4.0

# Move to a new tag (change @vX.Y.Z)
pipx uninstall la-localagent
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"
# If --force fails with “virtual environment already exists”:
# UV_VENV_CLEAR=1 pipx install --force "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"

# When tracking the default branch, pull the latest tip
pipx upgrade la-localagent
```

Available versions: GitHub [Releases](https://github.com/hezhenghui7338/localagent/releases) / [Tags](https://github.com/hezhenghui7338/localagent/tags).

Then from **any directory** (three-command main path):

```bash
la                 # same as: la chat; prompts if Ollama is missing
la setup           # guided install/pull (answer n to skip)
la setup -y        # install + pull qwen3.5:4b without prompting
la chat --provider ollama
```

First run creates `~/.localagent/` (config, `.env`, data). Pure local needs no keys; to use your own APIs:

```bash
# Minimal flags (local-only)
la config --provider ollama --base_url "http://localhost:11434" --model qwen3.5:4b

# Or copy the example JSON, edit, then load (OPENROUTER_API_KEY / CURSOR_API_KEY / TAVILY_API_KEY …)
la config-example > my.json
la config my.json
la config list
```

> After the package is published to PyPI: `pipx install la-localagent==0.4.0` / `pipx upgrade la-localagent`

### Developer install

```bash
git clone git@github.com:hezhenghui7338/localagent.git
cd LocalAgent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# or: uv sync --extra dev
```

In a source checkout, config/data stay in the repo (`.env`, `data/`). After a normal install they live under `~/.localagent/`. See [Development](#development) for tests.

### Uninstall

Remove the CLI (pick the method you used to install):

```bash
# pipx
pipx uninstall la-localagent

# pip (current environment)
pip uninstall la-localagent
```

Optional: delete local config and data (API keys, memory, knowledge base, etc.). **If you keep this directory, a reinstall will reuse the old data.**

```bash
# Normal install (pipx / pip)
rm -rf ~/.localagent

# Source checkout: delete the repo, or clean `.env` and `data/` inside it
```

Ollama and pulled models are separate; uninstalling LocalAgent does **not** remove them. To clean those up as well:

```bash
ollama rm qwen3.5:4b   # remove the model if you want
# On macOS, uninstall the Ollama app separately if desired
```

## Feature highlights

### Fully local

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

### Write-file hallucination detection

A typical chat often claims it “wrote” a file without changing anything. LocalAgent has **hallucination detection** for file writes: if the model claims create/update/append without calling `write_file`, it retries or errors clearly instead of showing fabricated empty content. Shell and file writes also ask for your approval by default.

```text
> append one line to test.txt at the project root: cross-session persistence test
[chat] working…
[chat] calling write_file…
⚠ Agent wants to write a file. Confirm before it executes.
Allow write? [y/N] y
Successfully appended the specified content to `test.txt`.
[via ollama/qwen3.5:4b]
```

Best for create/edit/append file work. Read-only asks and memory recall go straight to the agent — no pre-check gate.

### Local execution — Shell that actually acts

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

The repo includes a **product tour** (user-story driven, full I/O, ~30 min) and a shorter walkthrough:

| # | Scenario | Command |
| --- | --- | --- |
| 1 | Write & recall a single memory | `LA memory add` → `LA memory search` |
| 2 | Import & recall a Markdown file | `LA rag add` → `LA rag search` |
| 3 | Search recent news online | `LA chat` or `/deepsearch` (no API key required by default) |
| 4 | **Fully local** qwen3.5:4b | `LA chat --provider ollama` |
| 5 | Answer about local work | `LA workspace` / `LA chat --cwd .` |
| 6 | Agent runs terminal commands | `LA chat` → “count project LOC” |
| 7 | Write file + hallucination check | `LA chat` → clear path & content → approve |
| 8 | Audit report (Ollama $0) | `LA audit --since 7d` |

```bash
# Full product tour (recommended): user stories · complete input/output
open examples/product-tour.md
# Shorter walkthrough (English)
open examples/walkthrough.md
# Chinese walkthrough
open examples/walkthrough.zh-CN.md
```

Full narrative and acceptance criteria: [docs/PRD.md](docs/PRD.md).
### Mem0 long-term memory — remembers you end-to-end

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

- Default model is `qwen3.5:4b`; if missing, LA tries to match an installed tag with the same name
- Qwen3 often emits many thinking tokens; LocalAgent defaults `OLLAMA_THINK=0` to disable thinking mode
- When local Ollama is slow, `auto` falls back to OpenRouter within ~12s; or switch manually in chat with `/provider openrouter`

## Configuration

See [`.env.example`](.env.example). Common variables:

| Variable | Description |
| --- | --- |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Local Ollama URL and model |
| `MINIMAX_API_KEY` / `MINIMAX_MODEL` | MiniMax direct (OpenAI-compatible API) |
| `OPENROUTER_API_KEY` / `CURSOR_API_KEY` | Other cloud fallbacks |
| `TAVILY_API_KEY` | Optional; when set, `auto` prefers Tavily for web search |
| `LA_WEB_SEARCH_PROVIDER` | Web backend: `auto` (default) / `ddgs` / `tavily` / `searxng` |
| `LA_SEARXNG_URL` | Optional self-hosted SearXNG URL (e.g. `http://localhost:8080`) |
| `LA_MODEL_PROVIDER_PRIORITY` | `auto` priority; default `ollama,minimax,openrouter,cursor` |
| `LA_WORKSPACE` | Workspace root (Git / files / todos / shell context) |
| `LA_SHELL_TIMEOUT` / `LA_SHELL_MAX_OUTPUT` | Agent `run_shell` timeout (s) and output cap (default 30s / 12000 chars) |
| `LA_TOOL_APPROVAL` | Approve before tools run: `always` (default) / `dangerous` / `off` |
| `LA_DATA_DIR` | Custom data dir (for test isolation) |
| `LA_LOG_LEVEL` | Diagnostic log level: `INFO` (default) / `DEBUG` / `WARNING` … |

## Commands

Daily use is chat-first. Outer commands and in-session `/command` share the same paths (e.g. `/memory add` ≡ `LA memory add`). Session-only shortcuts: `/add` → `memory add`, `/search` → `memory search` (`/chat` is rejected inside the session).

```bash
$ LA -h
```

```text
usage: LA [-h] <command> ...

LocalAgent — personal AI hub on your machine

Main path:
  la / la chat     Chat
  la setup [-y]    Install/pull local Ollama model
  la config …      Local-only or bring-your-own API

Everyday:
  LA memory add|search|pending|approve|reject|forget
  LA memory ingest chatgpt <path>   # Import ChatGPT export
  LA rag add|search                 # Documents → Cold KB
  LA audit                          # Spend / safety report

Maintenance (advanced):
  memory ingest chat|all · query · reflect · status · reindex · reset · graph
  rag ingest|rebuild|reset · tasks · workspace · logs · websearch
```

`LA logs` shows runtime diagnostics (`data/logs/localagent.log`) — provider fallbacks, memory recall hits, agent retries. This is separate from `LA audit` (usage/cost/guardrails). Use `LA --debug <command>` or `LA_LOG_LEVEL=DEBUG` to mirror DEBUG lines to stderr while developing.

Interactive input uses [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit) (Unicode-safe editing / Tab completion; avoids macOS libedit CJK bugs).

## Data directory

Runtime data defaults to `data/` (gitignored — not committed):

```
data/
├── kb/                        # Symlinked personal files
├── core_profile.json          # Hot-layer core facts
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

Side-effect tools are gated (`always` / `dangerous` / `off`). Extreme commands (e.g. `rm -rf /`) are blocked outright. File writes also have hallucination detection: claiming a write without calling `write_file` triggers retry or a clear error.

### Model routing

`ModelRouter` unifies **Ollama** (default local), **MiniMax**, **OpenRouter**, and **Cursor**. In `auto` mode it follows `LA_MODEL_PROVIDER_PRIORITY` and falls back when a path is slow or unavailable. Models are compute providers; LocalAgent owns sessions, memory, and audit data on disk.

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

---

<a id="zh-cn"></a>

<p align="center">
  <img src="assets/logo.zh-CN.png" alt="LocalAgent" width="360">
</p>

<p align="center">
  <strong>Your AI. Your Data. Your Machine.</strong>
</p>

<p align="center">
  <a href="#english">English</a> · <b>中文</b>
</p>

# <img src="assets/logo-icon.png" alt="LA" width="36" valign="middle"> LocalAgent

> **完全本地 · 真正易用 · 长期懂你 — 本机个人 AI 中枢，数据与算力默认留在本地。**

LocalAgent（`LA`）不是又一个 Chat 客户端，而是跑在你本机上的**个人 AI 中枢**。需求展开见 [docs/PRD.md](docs/PRD.md)；约 30 分钟可跑通故事见 [examples/product-tour.zh-CN.md](examples/product-tour.zh-CN.md)。

### 产品设计

1. **完全本地化** — 默认零账单、零账号门槛：对话 / 记忆 / 检索 / 执行可纯本地跑通；数据与身份留本机；算力默认本地，可选联网与云端模型增强，但始终有纯本地路径  
2. **真正易用** — 一键安装、立即可用；日常主路径只要 `la` / `la setup` / `la chat`，少即是多  
3. **长期、多层次记忆** — Hot / Warm / Cold + Mem0：不仅记住你，更智能地判断该记什么、别记什么、何时介入  
4. **支持外部工具** — 本地 Shell、写文件、工作区感知；执行前确认，危险命令拦截；可审计花费与行为  
5. **支持 RAG** — 本地文档进知识库，对话时可深度召回原文

| 普通本地 Chat | LocalAgent |
| --- | --- |
| 云端账单与账号门槛 | **默认零成本本地路径**（Ollama），可选自有 API |
| 装完还要学一堆命令 | **主路径三命令**：`la` · `la setup` · `la chat` |
| 聊完就忘，或只会死记 | **多层次记忆**，懂你且会取舍 |
| 不会动手、不会搜网 | **本机工具** + 可选联网 |
| 文档与对话各管各的 | **RAG 知识库** + 对话归档，深度召回 |

可选接入 OpenRouter / Cursor / Tavily 做增强，但**身份与数据始终留在本机**。

**本周期尚未做**：工作区 watcher 增量索引、外部任务源。

### 用户故事

| 我想… | 入口 |
| --- | --- |
| 一键装好、马上聊天 | [用户安装](#用户安装推荐) |
| 作为开发者改源码、跑测试 | [开发者安装](#开发者安装) |
| 用自己的 API Key 也能跑 | [配置](#配置) · `la config` |
| 被 profile、跨会话记住 | [Mem0 长期记忆](#亮点mem0-长期记忆--全方位记住你) · [产品体验 §3](examples/product-tour.zh-CN.md) |
| 联网搜索 | [功能示例](#功能示例) · [产品体验 §6](examples/product-tour.zh-CN.md) |
| 用本地 Shell / 写文件 | [本地 Shell](#亮点本机执行--本地-shell-真正动手) · [产品体验 §7](examples/product-tour.zh-CN.md) |
| 导入 ChatGPT 对话，更快认识我 | `LA memory ingest chatgpt` · [产品体验 §4](examples/product-tour.zh-CN.md) |
| 危险命令被拦住 | [Agent 工具与安全](#agent-工具与安全) · [产品体验 §7](examples/product-tour.zh-CN.md) |
| 看清花了多少 token / 费用 | `LA audit` · [产品体验 §8](examples/product-tour.zh-CN.md) |
| 把本地文档放进知识库并深度召回 | `LA rag add` · [产品体验 §5](examples/product-tour.zh-CN.md) |

### 我们相信什么

- AI 是革命性技术，必须拥抱；旁观一万遍，不如一键下载、亲手调试  
- 「书读百遍其义自见」不会自动发生——你需要的是实践  
- LA 只摘**低垂、成熟**的 AI 果实；不引入失控、昂贵、难维护的重栈  
- LA **只做一件事**：本机个人 AI 中枢。数据留本地，本地可完整跑通；不拒绝联网与新技术，但默认不设障碍  
- 消除使用 AI 的门槛，而不是设置门槛；作者也在持续学习——让我们一起成长  

```bash
# 首次安装（pin 版本，可复现、也更快定位问题）
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"
# 已装旧版：优先卸载再装；若 uv 报 venv 已存在：UV_VENV_CLEAR=1 pipx install --force "…"
la --version                    # 确认版本：la-localagent 0.4.0
la                              # 首次若无 Ollama 会询问是否安装（可跳过）
```

## 特性

- **完全本地化**：默认 `qwen3.5:4b`，对话、记忆写入、检索、工作区感知、Shell 执行全链路本地跑通；可选云端模型，数据仍归本机
- **真正易用**：主路径 `la` / `la setup` / `la chat`；高级能力用子命令，不挡日常使用
- **长期多层次记忆**：Hot（核心画像）/ Warm（长期记忆）/ Cold（文档 + 对话归档），按需 JIT 召回
- **Mem0 + 对话记忆**：ChatGPT 历史与 LA 日常对话 → Warm 事实 **与** Cold 可检索归档；文档经 `LA rag` 进 Cold
- **外部工具 + 安全**：工作区感知 + `run_shell` + 写文件；执行前确认；危险命令硬拦截；写文件幻觉检测
- **联网搜索**：默认 ddgs（无需 Key）；可选 Tavily / SearXNG
- **文档知识库（RAG）**：软链导入个人文件，Chroma + BM25 混合检索
- **多模型对话**：Ollama / OpenRouter / Cursor 统一入口，`auto` 模式按优先级自动降级
- **可审计**：Token/费用、Agent 行为、护栏拦截与敏感文件扫描，可导出 Markdown 报告

## 要求

- Python 3.10+
- [Ollama](https://ollama.com/) + `qwen3.5:4b`（推荐，也是项目默认配置）
- 可选：[pipx](https://pipx.pypa.io/)（推荐，用于全局 `la` 命令）

## 快速开始

### 用户安装（推荐）

当前发布版本：**v0.4.0**（与 `src/localagent/__init__.py` / `la --version` 一致）。

**加速建议**：始终 pin 到 tag（如下 `@v0.4.0`），避免跟踪默认分支时反复拉全量历史；已装旧版时优先 `pipx uninstall` 再装，比纠结 `--force` 更稳。

```bash
# 安装指定版本（推荐，可复现）
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"

# 或跟踪默认分支最新提交（无版本保证）
pipx install "git+https://github.com/hezhenghui7338/localagent.git"

# 或用 pip 装进当前 Python 环境
pip install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"
```

查看版本与升级：

```bash
la --version                  # 或 la -V → la-localagent 0.4.0

# 升到某个新 tag（改掉 @vX.Y.Z）
pipx uninstall la-localagent
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"
# 若坚持 --force 且报 “virtual environment already exists”，加：
# UV_VENV_CLEAR=1 pipx install --force "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"

# 跟踪默认分支时，拉最新 tip
pipx upgrade la-localagent
```

可用版本见 GitHub [Releases](https://github.com/hezhenghui7338/localagent/releases) / [Tags](https://github.com/hezhenghui7338/localagent/tags)。

然后在**任意目录**（主路径三命令）：

```bash
la                 # 等同于 la chat；无 Ollama 时询问是否安装
la setup           # 单独引导安装/拉取（可答 n 跳过）
la setup -y        # 无需确认，直接安装并拉取 qwen3.5:4b
la chat --provider ollama
```

首次运行会在 `~/.localagent/` 创建配置、`.env` 与数据目录。纯本地可先不填 Key；要用自有 API 时：

```bash
# 极简参数（纯本地）
la config --provider ollama --base_url "http://localhost:11434" --model qwen3.5:4b

# 或复制模板改写后加载（可填 OPENROUTER_API_KEY / CURSOR_API_KEY / TAVILY_API_KEY …）
la config-example > my.json
la config my.json
la config list
```

> 发布到 PyPI 后可直接：`pipx install la-localagent==0.4.0` / `pipx upgrade la-localagent`

### 开发者安装

```bash
git clone git@github.com:hezhenghui7338/localagent.git
cd LocalAgent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# 或：uv sync --extra dev
```

源码 checkout 时配置与数据仍在仓库内（`.env`、`data/`）；普通安装后则落在 `~/.localagent/`。测试见下方 [开发](#开发)。

### 卸载

卸掉 CLI（按你当初的安装方式选一种）：

```bash
# pipx
pipx uninstall la-localagent

# pip（当前环境）
pip uninstall la-localagent
```

可选：删除本机配置与数据（API Key、记忆、知识库等）。**不删则重装后会沿用旧数据。**

```bash
# 普通安装（pipx / pip）
rm -rf ~/.localagent

# 源码开发安装：删仓库，或清理仓库内的 .env、data/
```

Ollama 与已拉取的模型是独立软件，卸载 LocalAgent **不会**自动移除它们。若也要清理：

```bash
ollama rm qwen3.5:4b   # 按需删除模型
# macOS 再按需卸载 Ollama 应用本身
```

## 功能示例

### 亮点：完全本地化

LocalAgent 的核心链路——**对话、记忆写入、记忆召回、文档检索、工作区感知、Shell 执行、审计统计**——均可只依赖本地 Ollama，无需任何付费 API。数据与身份不出本机。

| 能力 | 是否需要联网 API | 说明 |
| --- | --- | --- |
| 对话 `LA chat` | 否 | 默认 `qwen3.5:4b`，本机可跑 |
| 单条记忆 `LA memory add` | 否 | 本地模型提取标题/标签 |
| 文档入库 `LA rag add` | 否 | 仅 Cold 知识库索引，不提取记忆 |
| 记忆/知识检索 `LA memory search` | 否 | BM25 + Chroma 本地检索 |
| 工作区 `LA workspace` | 否 | 读本地 Git / 文件 / TODO |
| Agent 执行命令 `run_shell` | 否 | 本地 4B 模型自动调用 shell 并汇总输出 |
| 审计 `LA audit` | 否 | 读本地 usage.jsonl + events.jsonl |
| 诊断日志 `LA logs` | 否 | 读本地 `data/logs/localagent.log` |
| 联网搜索 | 否（默认 ddgs） | 开箱可用；可选 Tavily / 自托管 SearXNG 提升质量 |

```bash
# 纯本地模式：本机 + Ollama，无需付费 API
cp examples/env.local-only.example .env
ollama pull qwen3.5:4b
LA chat --provider ollama
```

### 亮点：写文件幻觉检测

普通 Chat 常会声称「已写入」却从未真正改文件。LocalAgent 对文件写入有**幻觉检测**：若模型声称已创建/修改/追加却未调用 `write_file`，会自动重试或明确报错，而不是展示编造的空内容。写文件与 Shell 默认还会在执行前请你确认。

```text
> 修改根目录下的 test.txt，追加一行：跨对话持续性测试
[chat] 处理中…
[chat] 调用 写入文件…
⚠ Agent 请求写入文件，需你确认后才会执行。
是否允许写入？ [y/N] y
已成功将指定内容追加到 `test.txt`。
[via ollama/qwen3.5:4b]
```

适用场景：创建/修改/追加文件等写操作；读操作与记忆回忆则直接执行，不再做额外预检。

### 亮点：本机执行 —— 本地 Shell 真正动手

普通 Chat 只会告诉你「去终端运行 `find … | wc -l`」。LocalAgent 的 Agent 会**自己调用 `run_shell` 工具**，在工作区执行命令并把结果整理成回答——全程纯本地 `qwen3.5:4b`，无需云端 API。

```text
> 统计一下当前项目的代码行数
[chat] 思考中…
[chat] 连接模型 (auto(ollama→openrouter→aiping→cursor))…
[chat] 生成回复…
[chat] 调用 执行命令: find . -type f \( -name "*.py" -o -name …
[chat] 等待用户确认操作…
⚠ Agent 请求执行命令，需你确认后才会执行。
命令: find . -type f \( -name "*.py" -o -name "*.js" \) …
是否允许执行？ [y/N] y
[chat] 综合工具结果 (第 2 轮)…
[chat] ✓ 综合工具结果 (第 2 轮)… (20.4s)
当前项目（`/Users/hzh/code/LocalAgent`）中主要编程语言文件（Python、JS、TS、Go、Java、C/C++、Rust等，排除隐藏目录）的总代码行数为 **13,961 行**。
[via ollama/qwen3.5:4b]
```

适用场景：统计代码行数、列目录、查看 Git 日志、运行测试/构建等。命令在工作区目录执行（`LA_WORKSPACE` 或当前目录），默认超时 30 秒。**默认每次执行前都会询问你是否允许**；`rm` / `sudo` / 强制 git 等危险命令会额外警告。可通过 `LA_TOOL_APPROVAL=dangerous` 仅审核危险操作，或 `off` 关闭（不推荐）。

仓库提供 **产品体验教程**（用户故事驱动 · 完整输入输出 · 约 30 分钟）与更短的 walkthrough：

| #   | 场景                   | 命令                                      |
| --- | -------------------- | --------------------------------------- |
| 1   | 单条记忆写入与召回            | `LA memory add` → `LA memory search`                  |
| 2   | Markdown 知识库导入与召回   | `LA rag add` → `LA rag search` |
| 3   | 联网搜索最近新闻             | `LA chat` 或 `/deepsearch`（默认无需 Key） |
| 4   | **纯本地运行** qwen3.5:4b | `LA chat --provider ollama`             |
| 5   | 回答本地工作内容             | `LA workspace` / `LA chat --cwd .`      |
| 6   | Agent 自动执行终端命令       | `LA chat` → 「统计当前项目代码行数」              |
| 7   | 写文件 + 幻觉检测            | `LA chat` → 明确路径与内容 → 确认写入           |
| 8   | 审计报告（Ollama 零费用）     | `LA audit --since 7d`                   |

```bash
# 产品体验教程（推荐）：用户故事 · 完整输入输出
open examples/product-tour.zh-CN.md
# 更短的分步 walkthrough（中文）
open examples/walkthrough.zh-CN.md
# English walkthrough
open examples/walkthrough.md
```

更完整的叙事与验收对照见 [docs/PRD.md](docs/PRD.md)。

### 亮点：Mem0 长期记忆 —— 全方位记住你

记忆输入支持 **ChatGPT 历史对话与 LA 日常对话**；个人文档请用 `LA rag` 进知识库。Warm 层接入强大的 [Mem0](https://github.com/mem0ai/mem0) 引擎（`mem0ai` 已含主依赖），提供 **Retain → Recall → Reflect（search + LLM）** 完整记忆链路。仓库提供一条「架构决策演变」叙事演示，覆盖写入、语义召回、时间感知、标签浏览与跨记忆推理：

```bash
# 源码开发
pip install -e ".[dev]"

# 一键演示（隔离 /tmp，不污染 data/）
bash examples/mem0-demo.sh

# 或阅读分步教程
open examples/mem0-demo.md
```

演示要点：

| 步骤 | 命令 | 展示能力 |
|------|------|----------|
| 写入演变链 | `LA memory add` × 4 | Retain + 自动标题/标签/发生时间 |
| 语义召回 | `LA memory search "记忆引擎选型"` | Mem0 语义召回 |
| 时间感知 | `LA memory search "2026年5月 决定"` | 按发生时间重排序 |
| 标签浏览 | `LA memory query --tag 决策` | 结构化查询 |
| 跨记忆推理 | `LA memory reflect "选型经历了什么变化？"` | Mem0 search + LLM reflect |

**文档放哪**

| 目录 | 用途 |
| --- | --- |
| [`examples/`](examples/) | 动手材料：教程、样例输入/输出、演示脚本、配置模板 |
| [`docs/`](docs/) | 面向贡献者的设计文档：[PRD](docs/PRD.md)、[TDD](docs/TDD.md) |

`examples/` 内容：

- [examples/product-tour.zh-CN.md](examples/product-tour.zh-CN.md) — **产品体验教程**（用户故事 · 完整输入输出 · 约 30 分钟） · [English](examples/product-tour.md)
- [examples/walkthrough.zh-CN.md](examples/walkthrough.zh-CN.md) — **分步教程**（纯本地 qwen3.5:4b 优先） · [English](examples/walkthrough.md)
- [examples/mem0-demo.md](examples/mem0-demo.md) / [mem0-demo.sh](examples/mem0-demo.sh) — Mem0 记忆引擎深度演示（Retain / Recall / Reflect）
- [examples/sample-project-notes.md](examples/sample-project-notes.md) — `rag add` 演示文档
- [examples/audit-report-sample.md](examples/audit-report-sample.md) — 审计报告样例（Ollama $0）
- [examples/env.local-only.example](examples/env.local-only.example) — 纯本地 `.env` 模板
- [benchmarks/stm/README.md](benchmarks/stm/README.md) — **短期记忆（STM）基准**（可进 CI）
- [benchmarks/locomo/README.md](benchmarks/locomo/README.md) — **LoCoMo 长期记忆基准**（超长多 session 对话 QA）

### 基准：短期记忆（STM）

当日/会话内回顾（`history` + 今日 conversations）。秒级、无需 LLM：

```bash
python -m benchmarks.stm
```

说明见 [benchmarks/stm/README.md](benchmarks/stm/README.md)。

### 基准：LoCoMo 长期会话记忆

用 ACL 2024 [LoCoMo](https://github.com/snap-research/locomo) 评测跨 session 长期记忆。
**主指标 = Warm∪Cold 联合证据 hit@k**（RRF 融合）。Warm-only / Cold-only 仅作归因诊断。
**当前 Warm-only 基线（2026-07-14，`conv-26`，Mem0 hybrid + CE，n=150）**：Hit@1 **0.433** / Hit@5 **0.627** / Hit@8 **0.673** — Joint 基线待重跑（见 HISTORY）。

```bash
python -m benchmarks.locomo.run download
python -m benchmarks.locomo.measure_recall \
  --skip-ingest --sample-ids conv-26 \
  --work-dir benchmarks/data/runs/locomo-mem0 \
  --diagnostics --label joint
```

分 category 表与复现步骤见 [benchmarks/locomo/README.md](benchmarks/locomo/README.md)。历次跑分见 [benchmarks/locomo/HISTORY.md](benchmarks/locomo/HISTORY.md)。

### Shell 自动补全

首次运行任意 `LA` 命令时会自动安装 Tab 补全（写入 `~/.zshrc` / `~/.bashrc`，并挂到 `.venv/bin/activate`）。之后 `source .venv/bin/activate`（或新开终端），`LA memory` / `LA rag` + Tab 即可提示子命令。

若需手动重装/修复：

```bash
LA complete-init
source .venv/bin/activate   # 或: source ~/.zshrc
```

### Ollama 提示

- 默认模型 `qwen3.5:4b`；若未安装，LA 会尝试匹配已安装的同名 tag
- Qwen3 系列默认生成大量 thinking token，LocalAgent 默认 `OLLAMA_THINK=0` 关闭思考模式
- 本地 Ollama 较慢时，`auto` 模式会在 12 秒内降级到 OpenRouter；也可在 chat 中输入 `/provider openrouter` 手动切换

## 配置

详见 [`.env.example`](.env.example)，常用变量：

| 变量                                      | 说明                                               |
| --------------------------------------- | ------------------------------------------------ |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL`      | 本地 Ollama 地址与模型                                  |
| `MINIMAX_API_KEY` / `MINIMAX_MODEL`     | MiniMax 直连（OpenAI 兼容 API）                        |
| `OPENROUTER_API_KEY` / `CURSOR_API_KEY` | 其他云端模型降级                                         |
| `TAVILY_API_KEY`                        | 可选；配置后 `auto` 优先用 Tavily 联网搜索           |
| `LA_WEB_SEARCH_PROVIDER`                | 联网后端：`auto`（默认）/ `ddgs` / `tavily` / `searxng` |
| `LA_SEARXNG_URL`                        | 可选；自托管 SearXNG 地址（如 `http://localhost:8080`） |
| `LA_MODEL_PROVIDER_PRIORITY`            | auto 模式优先级，默认 `ollama,minimax,openrouter,cursor` |
| `LA_WORKSPACE`                          | 工作区根目录（Git / 文件 / 待办 / shell 命令上下文）              |
| `LA_SHELL_TIMEOUT` / `LA_SHELL_MAX_OUTPUT` | Agent `run_shell` 超时秒数与输出截断上限（默认 30s / 12000 字符） |
| `LA_TOOL_APPROVAL`                      | 工具执行前用户确认：`always`（默认，每次）/ `dangerous`（仅危险）/ `off` |
| `LA_DATA_DIR`                           | 自定义数据目录（测试隔离用）                                   |
| `LA_LOG_LEVEL`                          | 诊断日志级别：`INFO`（默认）/ `DEBUG` / `WARNING` …           |

## 命令

日常以对话为主。外层命令与会话内 `/command` 同路径（如 `/memory add` ≡ `LA memory add`）。会话快捷方式：`/add` → `memory add`，`/search` → `memory search`（会话内禁止再开 `/chat`）。

```bash
$ LA -h
```

```text
usage: LA [-h] <command> ...

LocalAgent — 本机个人 AI 中枢

主路径：
  la / la chat     对话
  la setup [-y]    安装/拉取本地 Ollama 模型
  la config …      纯本地或自有 API

日常：
  LA memory add|search|pending|approve|reject|forget
  LA memory ingest chatgpt <path>   # 导入 ChatGPT 导出
  LA rag add|search                 # 文档 → Cold 知识库
  LA audit                          # 花费 / 安全报告

运维（高级）：
  memory ingest chat|all · query · reflect · status · reindex · reset · graph
  rag ingest|rebuild|reset · tasks · workspace · logs · websearch
```

`LA logs` 查看运行时诊断日志（`data/logs/localagent.log`）——provider 降级、记忆召回命中、agent 重试等。与 `LA audit`（用量/费用/护栏）不同。开发时可 `LA --debug <command>` 或设置 `LA_LOG_LEVEL=DEBUG`，DEBUG 日志会同步打到 stderr。

对话输入基于 [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit)（Unicode 安全编辑与 Tab 补全，规避 macOS libedit 的 CJK 问题）。

## 数据目录

运行时数据默认位于 `data/`（已在 `.gitignore` 中排除，不会提交到 Git）：

```
data/
├── kb/                        # 软链接的个人文件
├── core_profile.json          # Hot 层核心事实
├── sync_index.json            # 已索引文件登记
├── conversations/             # 对话档案
├── chatGPTdata/               # ChatGPT 导出归档
├── chatgpt_import_index.json  # ChatGPT 导入去重登记
├── chat_ingest_index.json     # 对话记忆化进度登记
├── sessions.db                # LangGraph 会话
├── chroma/                    # 向量索引
├── bm25.pkl                   # BM25 索引
├── task_logs/                 # 后台 ingest 任务日志
├── logs/
│   └── localagent.log         # 诊断日志（LA logs / --debug）
└── audit/
    ├── usage.jsonl            # 模型/搜索用量
    └── events.jsonl           # 工具决策 / 护栏事件
```

## 架构

叙事主线：**完全本地（零成本可玩）** → **真正易用** → **智能多层次记忆** → **外部工具** → **RAG**。

### 系统总览

```
┌──────────────────────────────────────────────────────────────────┐
│                         LA CLI / chat REPL                       │
│                     斜杠命令 · 执行前确认 UI                        │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │   LangGraph Agent     │
                    │  JIT 工具 · 工具循环   │
                    └───────────┬───────────┘
                                │
              ┌─────────────────┼─────────────────┐
              ▼                 ▼                 ▼
     ┌────────────────┐ ┌──────────────┐ ┌────────────────┐
     │  ModelRouter   │ │ 记忆栈       │ │ 行动面         │
     │ Ollama → 云端  │ │ Hot/Warm/Cold│ │ 联网 · Shell · │
     │ (auto 降级)    │ │              │ │ write_file     │
     └────────────────┘ └──────┬───────┘ └────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
           Hot              Warm             Cold
     core_profile.json    Mem0（可回退     Chroma + BM25
     （Pinned 核心事实）   JSON）           （+ RRF 混合检索）
                          对话提取入库      kb 文档 + 对话归档
```

### 请求路径（`LA chat`）

```
用户输入
    │
    ▼
Agent 循环
    ├─ 按需预加载 JIT 上下文（画像 / 记忆 / 联网 / 工作区）
    ├─ 经 ModelRouter 调用模型
    ├─ 工具调用（search_memory、search_knowledge、web_search、
    │            workspace_context、retain_memory、write_file、run_shell …）
    ├─ Observe 启发式压缩后再回填（LA_OBSERVE_BUDGET_CHARS；不额外调 LLM）
    ├─ write_file / run_shell 执行前确认   ← LA_TOOL_APPROVAL
    └─ 综合作答（联网结果须标注来源链接）
```

### 三层记忆

| 层 | 存储 | 作用 | 写入来源 |
| --- | --- | --- | --- |
| **Hot** | `core_profile.json` | 始终在场的身份 / Pinned 事实 | Profile pin / 显式核心更新 |
| **Warm** | Mem0（默认）或 JSON `memory_store`（+ 可选 SQLite 关系图） | 长期对话记忆 | ChatGPT 导入 · LA 对话提取 · `memory add` / `retain_memory` |
| **Cold** | Chroma + BM25（+ RRF） | 个人文档原文 + 对话归档（摘要/轮次块） | `LA rag add` / `rag ingest`（文档）；ChatGPT / LA 对话 ingest 时先写 Cold |

Warm 与 Cold 刻意分离：对话提取为「关于你」的 Warm 事实；文档与对话原文留在 Cold，可深度检索。

#### 可选 Warm 关系图（默认关闭）

代码能力保留；**默认关闭**（`LA_MEMORY_GRAPH=0`）。日常召回质量主要靠混合检索 + cross-encoder（`pip install 'la-localagent[rerank]'`），而不是图。

| | |
| --- | --- |
| 是什么 | 本地 SQLite `data/memory_graph.db`：实体/槽位边 + 对话 `NEXT_TURN`，1–2 跳扩候选池 |
| 为何默认关 | 公平 LoCoMo 下 Hit@1 持平、Hit@5/8 仅小幅上升；开图会多一轮精排（更慢） |
| 何时开 | 做多跳/人物关系实验时；先 `LA memory graph rebuild` |
| CLI | `LA memory graph stats` · `LA memory graph rebuild` |

需要时再开：

```bash
# .env
LA_MEMORY_GRAPH=1
LA_MEMORY_GRAPH_BOOST=0
LA_MEMORY_GRAPH_PROTECT_TOP=1
LA_MEMORY_GRAPH_FORCE_IN_TOP=3
LA_MEMORY_RERANK_BACKEND=cross_encoder   # 公平排序必需

LA memory graph rebuild
```

#### 可选 Neo4j 精确图查询（默认关闭）

对**计数、聚合、可形式化多跳**，LA 可用 Cypher 结构化查询返回**计算结果**（而非从文本片段采样作答）。与上方 SQLite hop 扩池相互独立。

| | |
| --- | --- |
| 是什么 | Neo4j（或 `LA_NEO4J_URI=memory://` 进程内图）+ Cypher 模板 |
| 何时用 | 「多少次 / 列出所有 / 同时提到」类精确问 |
| Agent 工具 | `query_memory_graph`（禁止用 `search_memory` 估算数字） |
| CLI | `LA memory graph neo4j stats\|rebuild` · `LA memory graph query "…"` |
| 安装 | `pip install 'la-localagent[neo4j]'` |

```bash
# .env
LA_NEO4J=1
LA_NEO4J_URI=bolt://localhost:7687   # 本地实验可用 memory://
# LA_NEO4J_USER=neo4j
# LA_NEO4J_PASSWORD=password

LA memory graph neo4j rebuild
LA memory graph query "提到过几次 Caroline？"
```

开放语义问仍走 Warm 混合召回 / Cold RAG。

### Warm 记忆管线（Retain → Recall → Reflect → Consolidate）

```
写入路径                              读取路径
────────                              ────────
ChatGPT 导出 / LA 对话                查询
        │                                │
        ▼                                ▼
提取 + 富化（enrich）                    查询分解（多跳拆分）
（标题 / 标签 / 实体 /                   │
 事件时间 / 价值过滤）                    ▼
        │                             混合召回
        ▼                             （向量 + 词法 + 时间意图
Consolidation                         + 实体 soft boost + rerank；
（ADD / UPDATE / DELETE / NOOP）       可选图扩展，需显式开启）
        │                                │
        ▼                                ▼
Mem0 / JSON 存储                      Reflect（多跳检索 + LLM）
                                      → 作答或继续追问检索
```

- **Retain**：从对话提取可沉淀事实；补全元数据；可选与近重复记忆做 consolidation
- **Recall**：混合检索 + 时间意图（`range` / `as_of_now` / `when_event` / …）、scoped soft boost、可选 cross-encoder / embed / LLM rerank；图扩展为可选
- **Reflect**：多跳循环 — 召回 → 决定是否追问检索 → 综合（`LA memory reflect` / Agent `reflect_memory`）
- **Hot 注入**：核心画像并入回答，换模型不丢「我是谁」

### Agent 工具与安全

| 能力面 | 工具 | 说明 |
| --- | --- | --- |
| 画像 / 记忆 | `search_memory`、`query_memories`、`retain_memory`、`reflect_memory` | JIT Warm + Hot |
| 文档 | `search_knowledge` | Cold 混合检索；索引未命中可回退 `kb/` 原文 |
| 联网 | `web_search`、`/deepsearch` | 默认 **ddgs**；可选 Tavily / SearXNG |
| 本机 | `workspace_context`、`run_shell`、`write_file` | 限定工作区；Shell/写文件需确认 |

有副作用的工具受门控（`always` / `dangerous` / `off`）。极端危险命令（如 `rm -rf /`）直接拦截。文件写入另有幻觉检测：未真正调用 `write_file` 却声称已写入时，会重试或明确报错。

### 模型路由

`ModelRouter` 统一 **Ollama**（默认本地）、**MiniMax**、**OpenRouter**、**Cursor**。`auto` 模式按 `LA_MODEL_PROVIDER_PRIORITY` 降级。模型只是算力供应商；会话、记忆与审计数据由 LocalAgent 落盘保管。

### 源码模块一览

```
src/localagent/
├── cli.py / chat_repl.py / session_commands.py   # CLI + REPL + /命令
├── agent/           # Agent 运行时 + Observe 压缩
├── models/          # ModelRouter（本地 → 云端降级）
├── memory/          # Hot 画像 · Warm 后端 · 召回/Reflect/Consolidate
├── knowledge/       # Cold Chroma + BM25 + RRF
├── ingest/          # rag add/ingest 管线（仅 Cold）
├── tools/           # Agent 工具 + 执行确认
├── workspace/       # Git / 最近文件 / todos
├── persist/         # 对话档案 · sessions · ChatGPT 归档
└── audit/           # 用量 · 安全扫描 · 报告
```

设计文档（非用户上手教程）：[docs/PRD.md](docs/PRD.md) 与 [docs/TDD.md](docs/TDD.md)。动手教程在 [`examples/`](examples/)。

## 开发

发版时同步三处（缺一不可）：

1. 改 `src/localagent/__init__.py` 里的 `__version__`（唯一版本源）
2. 打并推送同号 tag：`git tag v0.4.0 && git push origin v0.4.0`
3. 更新 README 中的 `@v…` / 当前版本说明

GitHub Actions CI 跑 `uv run pytest`（单元+集成，含 STM；排除 `e2e` / `e2e_live`），另有独立 **e2e-offline** job（`pytest tests/e2e -m e2e`）。实机 Ollama 测试仅本机运行。

```bash
# 单元 + 集成测试（隔离临时目录，不依赖 Ollama；含 STM）
pytest

# 端到端：subprocess 调用 LA 命令（CI e2e-offline job 也会跑）
pytest tests/e2e -m e2e

# 含真实 Ollama 对话（需本地已 pull 对话模型）
pytest tests/e2e -m e2e_live
```

## 安全与隐私

- **切勿提交** `.env` 或 `data/` 下的运行时数据；仓库已通过 `.gitignore` 排除
- API Key 仅保存在本机 `.env` 中
- 记忆与对话档案默认仅存本地，不上传云端
- **本地执行门禁**：Agent 的 `run_shell` / `write_file` 默认每次需你确认（`LA_TOOL_APPROVAL=always`）；危险命令会额外警告。极端破坏性命令（如 `rm -rf /`）直接禁止。非交互环境在未提供确认回调时拒绝执行
- 若曾在其他环境泄露过 API Key，请立即在对应平台轮换密钥

## License

MIT
