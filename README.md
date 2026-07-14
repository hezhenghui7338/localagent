<p align="center">
  <img src="assets/logo.png" alt="LocalAgent" width="360">
</p>

<p align="center">
  <strong>Your AI. Your Data. Your Mac.</strong>
</p>

<p align="center">
  <a href="./README.md">English</a> · <a href="./README.zh-CN.md">中文</a>
</p>

# <img src="assets/logo-icon.png" alt="LA" width="36" valign="middle"> LocalAgent

> **Fully local · Knows you long-term — machine · profile · internet, actually usable.**

LocalAgent (`LA`) is not another chat client. It is a **personal AI that runs on your machine**. Core narrative:

1. **Fully local** — default Ollama `qwen3.5:4b`; chat, memory, retrieval, and execution all run on-device; identity and data never leave your machine  
2. **Long-term, multi-layer memory** — Hot / Warm / Cold layers; an assistant that actually knows you across sessions  
3. **Where memory comes from** — **ChatGPT history** and **LA live chats** feed Warm memory; personal documents go to the **RAG knowledge base** (no memory extraction), powered by **Mem0**  
4. **Actually usable** — web search + local Shell, connecting **your machine · your profile · the internet**  
5. **Reliable execution** — write-file hallucination detection; approve before `run_shell` / `write_file`

```bash
# First-time install
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.3.0"
# Already installed: uninstall + reinstall is most reliable. If uv says the venv exists, set UV_VENV_CLEAR=1.
pipx uninstall la-localagent
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.3.0"
# Or: UV_VENV_CLEAR=1 pipx install --force "git+https://github.com/hezhenghui7338/localagent.git@v0.3.0"
la --version                    # expect: la-localagent 0.3.0
la                              # asks before installing Ollama (you can skip)
```

| Typical local chat | LocalAgent |
| --- | --- |
| Cloud or half-local; data boundary unclear | **Fully local** — identity and memory stay on device |
| Forgets after the session | **Long-term multi-layer memory** + Mem0 |
| Memory only from this chat | **ChatGPT history / LA chats** as cold-start; docs via RAG |
| Can't search the web or run commands | **Web search** + **local shell** — machine · profile · internet |
| Claims it “wrote a file” without changing anything | **Hallucination detection** + approve-before-write |

Optional OpenRouter / Cursor / Tavily for extras — **identity and data stay on your machine**.

## Features

- **Fully local**: default `qwen3.5:4b` — chat, memory write, retrieval, workspace awareness, and Shell execution all run on-device; optional cloud models, data still owned locally
- **Long-term multi-layer memory**: Hot (core profile) / Warm (long-term) / Cold (document source) with JIT recall — an assistant that knows you
- **Mem0 + conversation memory**: ChatGPT history and LA chats → Warm; docs via `LA rag` into Cold knowledge
- **Machine · profile · internet**: workspace awareness + `run_shell` + web search (ddgs by default; optional Tavily / SearXNG) — three layers that make it actually usable
- **Approve before execute**: `run_shell` / `write_file` require your confirmation by default; dangerous commands get an extra warning
- **Write-file hallucination detection**: if the model claims a write without calling `write_file`, it retries or errors clearly
- **Document knowledge base**: symlink personal files in; Chroma + BM25 hybrid search
- **Multi-model chat**: unified Ollama / OpenRouter / Cursor entry; `auto` mode falls back by priority
- **Auditable**: tokens/cost, agent behavior (shell/write/web), guardrail blocks, sensitive-file scan — exportable Markdown reports

## Requirements

- Python 3.10+ (Mem0 memory engine needs Python 3.10+)
- [Ollama](https://ollama.com/) + `qwen3.5:4b` (recommended; also the project default)
- Optional: [pipx](https://pipx.pypa.io/) (recommended for a global `la` command)

## Quick start

### One-command install (recommended)

Current release: **v0.3.0** (same as `src/localagent/__init__.py` / `la --version`).

```bash
# Install a pinned tag (recommended, reproducible)
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.3.0"

# Or track the default branch tip (no version pin)
pipx install "git+https://github.com/hezhenghui7338/localagent.git"

# Or with pip into the current environment
pip install "git+https://github.com/hezhenghui7338/localagent.git@v0.3.0"

# mem0ai ships with the core install — no extra memory extra required
```

Check version and upgrade:

```bash
la --version                  # or la -V → la-localagent 0.3.0

# Move to a new tag (change @vX.Y.Z)
pipx uninstall la-localagent
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.3.0"
# If --force fails with “virtual environment already exists”:
# UV_VENV_CLEAR=1 pipx install --force "git+https://github.com/hezhenghui7338/localagent.git@v0.3.0"

# When tracking the default branch, pull the latest tip
pipx upgrade la-localagent
# or
pipx install --force "git+https://github.com/hezhenghui7338/localagent.git"

# Same idea with pip
pip install --upgrade --force-reinstall \
  "git+https://github.com/hezhenghui7338/localagent.git@v0.3.0"
```

Available versions: GitHub [Releases](https://github.com/hezhenghui7338/localagent/releases) / [Tags](https://github.com/hezhenghui7338/localagent/tags).

Then from **any directory**:

```bash
la                 # same as: la chat; prompts if Ollama is missing
la setup           # guided install/pull (answer n to skip)
la setup -y        # install + pull qwen3.5:4b without prompting
la chat --provider ollama
```

First run creates `~/.localagent/` (config, `.env`, data). Set API keys:

```bash
# Minimal flags
la config --provider ollama --base_url "http://localhost:11434" --model qwen3.5:4b --TAVILY_API_KEY "tvly-..."

# Or copy the example JSON, edit, then load
la config-example > my.json
la config my.json

# Inspect current config
la config list
```

> After the package is published to PyPI: `pipx install la-localagent==0.3.0` / `pipx upgrade la-localagent`

### Develop from source

```bash
git clone git@github.com:hezhenghui7338/localagent.git
cd LocalAgent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

In a source checkout, config/data stay in the repo (`.env`, `data/`). After a normal install they live under `~/.localagent/`.

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
| Chat `LA chat` | No | Default `qwen3.5:4b`, runs on a regular Mac |
| Single memory `LA memory add` | No | Local model extracts title/tags |
| Doc import `LA rag add` | No | Cold knowledge index only; no memory extraction |
| Memory/knowledge search `LA memory search` | No | BM25 + Chroma locally |
| Workspace `LA workspace` | No | Reads local Git / files / TODOs |
| Agent commands `run_shell` | No | Local 4B model calls shell and summarizes |
| Audit `LA audit` | No | Reads local usage.jsonl + events.jsonl |
| Diagnostic logs `LA logs` | No | Reads local `data/logs/localagent.log` |
| Web search | No (ddgs by default) | Works out of the box; optional Tavily / self-hosted SearXNG |

```bash
# Fully local: regular Mac + Ollama, no paid API
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

The repo includes a **product tour** (eight strengths, full I/O, ~30 min) and a shorter walkthrough:

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
# Full product tour (recommended): 8 strengths · complete input/output
open examples/product-tour.md
# Shorter walkthrough
open examples/walkthrough.md
```

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

- [examples/product-tour.md](examples/product-tour.md) — **Product tour** (8 strengths · full I/O · ~30 min) · [中文](examples/product-tour.zh-CN.md)
- [examples/walkthrough.md](examples/walkthrough.md) — **step-by-step tutorial** (local qwen3.5:4b first)
- [examples/mem0-demo.md](examples/mem0-demo.md) / [mem0-demo.sh](examples/mem0-demo.sh) — Mem0 deep dive (Retain / Recall / Reflect)
- [examples/sample-project-notes.md](examples/sample-project-notes.md) — sample doc for `rag add`
- [examples/audit-report-sample.md](examples/audit-report-sample.md) — sample audit report (Ollama $0)
- [examples/env.local-only.example](examples/env.local-only.example) — fully local `.env` template
- [benchmarks/locomo/README.md](benchmarks/locomo/README.md) — **LoCoMo long-term memory benchmark**

### Benchmark: LoCoMo long-term conversational memory

Evaluate Warm-layer cross-session memory with ACL 2024 [LoCoMo](https://github.com/snap-research/locomo).  
**Current recall scores (2026-07-14, `conv-26`, Mem0 hybrid + cross-encoder rerank, n=150):** Hit@1 **0.433** / Hit@5 **0.627** / Hit@8 **0.673**.

```bash
python -m benchmarks.locomo.run download
python -m benchmarks.locomo.measure_recall \
  --skip-ingest --sample-ids conv-26 \
  --work-dir benchmarks/data/runs/locomo-mem0
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

```bash
$ LA -h
```

```text
usage: LA [-h] <command> ...

LocalAgent — local AI personal assistant

commands:
  chat           Interactive chat
  memory         add|ingest|query|search|…  Conversation Warm memory
  rag            add|ingest|search|…        Document Cold knowledge (no memory extract)
  tasks          Manage background index tasks
  workspace      Workspace / git / todo snapshot
  audit          Audit summary and report
  logs           View diagnostic logs (troubleshooting)
  config         Manage model YAML config

Use LA <command> -h for full help on a command.
```

`LA logs` shows runtime diagnostics (`data/logs/localagent.log`) — provider fallbacks, memory recall hits, agent retries. This is separate from `LA audit` (usage/cost/guardrails). Use `LA --debug <command>` or `LA_LOG_LEVEL=DEBUG` to mirror DEBUG lines to stderr while developing.

In `LA` / `LA chat` REPL, prefix any CLI command with `/` (Claude Code style; `:` is a legacy alias). Examples: `/help`, `/add "…"`, `/search …`, `/provider ollama`, `/model qwen3.5:4b`, `/deepsearch <topic>`, `/q`. Outer `LA <command>` and in-session `/<command>` are equivalent (`/chat` is rejected inside the session).

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

Narrative arc: **fully local** → **long-term multi-layer memory (Mem0)** → **conversation memory + document RAG** → **machine · profile · internet**.

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
    ├─ approval gate for write_file / run_shell   ← LA_TOOL_APPROVAL
    └─ synthesize answer (+ source links for web)
```

### Three-layer memory

| Layer | Store | Role | Written by |
| --- | --- | --- | --- |
| **Hot** | `core_profile.json` | Always-on identity / pinned facts | Profile pin / explicit core updates |
| **Warm** | Mem0 (default) or JSON `memory_store` (+ optional SQLite relation graph) | Long-term conversational memory | ChatGPT import · LA chat extract · `memory add` / `retain_memory` |
| **Cold** | Chroma + BM25 (+ RRF) | Personal document source text | `LA rag add` / `rag ingest` only — **no** memory extraction |

Warm and Cold stay separate on purpose: chats become durable facts about *you*; documents stay searchable source material.

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

### Warm memory pipeline (Retain → Recall → Reflect → Consolidate)

```
Write path                          Read path
─────────                           ─────────
ChatGPT export / LA chats           query
        │                              │
        ▼                              ▼
extract + enrich                  decompose (multi-hop splits)
(title / tags / entities /           │
 event time / value filter)          ▼
        │                         hybrid recall
        ▼                         (vector + lexical + temporal
Consolidation                     + entity soft boost + rerank;
(ADD / UPDATE / DELETE / NOOP)     optional graph expand if enabled)
        │                              │
        ▼                              ▼
Mem0 / JSON store                 Reflect (multi-hop search + LLM)
                                  → answer or deeper follow-ups
```

- **Retain**: extract durable facts from conversations; enrich metadata; optional consolidation against near-duplicates
- **Recall**: hybrid retrieval with temporal intent (`range` / `as_of_now` / `when_event` / …), scoped soft boosts, optional cross-encoder / embed / LLM rerank; graph expand is opt-in
- **Reflect**: multi-hop loop — recall → decide follow-up queries → synthesize (`LA memory reflect` / agent `reflect_memory`)
- **Hot injection**: core profile is merged into answers so identity survives model switches

### Agent tools & safety

| Surface | Tools | Notes |
| --- | --- | --- |
| Profile / memory | `search_memory`, `query_memories`, `retain_memory`, `reflect_memory` | JIT Warm + Hot |
| Documents | `search_knowledge` | Cold hybrid; falls back to raw `kb/` text on miss |
| Internet | `web_search`, `/deepsearch` | Default **ddgs**; optional Tavily / SearXNG |
| Machine | `workspace_context`, `run_shell`, `write_file` | Workspace-scoped; shell/write need approval |

Side-effect tools are gated (`always` / `dangerous` / `off`). Extreme commands (e.g. `rm -rf /`) are blocked outright. File writes also have hallucination detection: claiming a write without calling `write_file` triggers retry or a clear error.

### Model routing

`ModelRouter` unifies **Ollama** (default local), **MiniMax**, **OpenRouter**, and **Cursor**. In `auto` mode it follows `LA_MODEL_PROVIDER_PRIORITY` and falls back when a path is slow or unavailable. Models are compute providers; LocalAgent owns sessions, memory, and audit data on disk.

### Module map (source)

```
src/localagent/
├── cli.py / chat_repl.py / session_commands.py   # CLI + REPL + /commands
├── agent/           # LangGraph runtime
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

```bash
# Unit + integration tests (temp dirs; no Ollama required)
pytest

# End-to-end: subprocess LA commands
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
