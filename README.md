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

> **Fully local · Asks first · Knows you long-term — machine · profile · internet, actually usable.**

LocalAgent (`LA`) is not another chat client. It is a **proactive personal AI that runs on your machine**. Core narrative:

1. **Fully local** — default Ollama `qwen3.5:4b`; chat, memory, retrieval, and execution all run on-device; identity and data never leave your machine  
2. **Proactive awareness** — interrupt sparingly: act when clear, assume+state when mild ambiguity is reversible, ask one question only when a wrong guess is costly  
3. **Long-term, multi-layer memory** — Hot / Warm / Cold layers; an assistant that actually knows you across sessions  
4. **Where memory comes from** — **ChatGPT history**, personal documents, and live chats all ingest into one pipeline, powered by the **Mem0** memory engine  
5. **Actually usable** — web search + local Shell, connecting **your machine · your profile · the internet**

```bash
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.2.0"
la --version                    # expect: la-localagent 0.2.0
la                              # asks before installing Ollama (you can skip)
```

| Typical local chat | LocalAgent |
| --- | --- |
| Cloud or half-local; data boundary unclear | **Fully local** — identity and memory stay on device |
| Guesses unclear references and edits anyway | **Asks first**, then calls tools after confirmation |
| Forgets after the session | **Long-term multi-layer memory** + Mem0 |
| Memory only from this chat | **ChatGPT history / docs / chats** as cold-start sources |
| Can't search the web or run commands | **Web search** + **local shell** — machine · profile · internet |

Optional OpenRouter / Cursor / Tavily for extras — **identity and data stay on your machine**.

## Features

- **Fully local**: default `qwen3.5:4b` — chat, memory write, retrieval, workspace awareness, and Shell execution all run on-device; optional cloud models, data still owned locally
- **Proactive awareness**: three-way gate (act / assume / clarify); file writes also have hallucination detection
- **Long-term multi-layer memory**: Hot (core profile) / Warm (long-term) / Cold (document source) with JIT recall — an assistant that knows you
- **Mem0 + multi-source ingest**: ChatGPT history, personal docs, and live chats → one pipeline; powered by the **Mem0** memory engine
- **Machine · profile · internet**: workspace awareness + `run_shell` + web search (ddgs by default; optional Tavily / SearXNG) — three layers that make it actually usable
- **Approve before execute**: `run_shell` / `write_file` require your confirmation by default; dangerous commands get an extra warning
- **Document knowledge base**: symlink personal files in; Chroma + BM25 hybrid search
- **Multi-model chat**: unified Ollama / OpenRouter / Cursor entry; `auto` mode falls back by priority
- **Auditable**: token usage, cost estimates, sensitive-file scan — exportable Markdown reports

## Requirements

- Python 3.10+ (Mem0 memory engine needs Python 3.10+)
- [Ollama](https://ollama.com/) + `qwen3.5:4b` (recommended; also the project default)
- Optional: [pipx](https://pipx.pypa.io/) (recommended for a global `la` command)

## Quick start

### One-command install (recommended)

Current release: **v0.2.0** (same as `src/localagent/__init__.py` / `la --version`).

```bash
# Install a pinned tag (recommended, reproducible)
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.2.0"

# Or track the default branch tip (no version pin)
pipx install "git+https://github.com/hezhenghui7338/localagent.git"

# Or with pip into the current environment
pip install "git+https://github.com/hezhenghui7338/localagent.git@v0.2.0"

# mem0ai ships with the core install — no extra memory extra required
```

Check version and upgrade:

```bash
la --version                  # or la -V → la-localagent 0.2.0

# Move to a new tag (change @vX.Y.Z, then --force reinstall)
pipx install --force "git+https://github.com/hezhenghui7338/localagent.git@v0.2.0"

# When tracking the default branch, pull the latest tip
pipx upgrade la-localagent
# or
pipx install --force "git+https://github.com/hezhenghui7338/localagent.git"

# Same idea with pip
pip install --upgrade --force-reinstall \
  "git+https://github.com/hezhenghui7338/localagent.git@v0.2.0"
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

> After the package is published to PyPI: `pipx install la-localagent==0.2.0` / `pipx upgrade la-localagent`

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
| File import `LA memory add-file` | No | Heuristic extraction by default; no LLM |
| Memory/knowledge search `LA memory search` | No | BM25 + Chroma locally |
| Workspace `LA workspace` | No | Reads local Git / files / TODOs |
| Agent commands `run_shell` | No | Local 4B model calls shell and summarizes |
| Audit `LA audit` | No | Reads local usage.jsonl |
| Web search | No (ddgs by default) | Works out of the box; optional Tavily / self-hosted SearXNG |

```bash
# Fully local: regular Mac + Ollama, no paid API
cp examples/env.local-only.example .env
ollama pull qwen3.5:4b
LA chat --provider ollama
```

### Proactive awareness — interrupt sparingly

A typical chat that hears “help me edit a file” often guesses a path and overwrites it. LocalAgent has **proactive awareness**: a **light intent pre-check** (on by default) chooses among **act** / **assume** / **clarify**. It asks **one** concrete question only when a wrong guess is costly; mild ambiguity proceeds with stated assumptions. Personal preference recall (e.g. “what do I like to drink?”) goes straight to memory. File writes also have **hallucination detection**: if the model claims it “wrote” something without calling `write_file`, it retries or errors clearly instead of showing fabricated empty content.

```text
> help me edit a file
Before I continue, I want to confirm your intent:

1. Which file should be modified, or what is the full path?
2. What exactly should change?

Please add details and I’ll continue from there.
> edit test.txt in the project root
Got it — you want to modify `test.txt` at the workspace root. Tell me what to write or append.
> append: this is a test note for cross-session persistence
[chat] thinking…
[chat] connecting model (auto(ollama→openrouter→aiping→cursor))…
[chat] generating…
[chat] calling write_file…
[chat] synthesizing tool results (round 2)…
[chat] ✓ synthesizing tool results (round 2)… (11.1s)
Successfully appended the specified content to `test.txt`. Current contents:

> this is a test note for cross-session persistence
[via ollama/qwen3.5:4b]
```

Best for requests where the **target or scope is unclear** (edit files, refactor, analyze a project). Disable with `LA_INTENT_CLARIFY=0` (default on). Requests that already include a concrete path skip the pre-check.

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
| 2 | Import & recall a Markdown file | `LA memory add-file` → `LA memory search --knowledge` |
| 3 | Search recent news online | `LA chat` or `/deepsearch` (no API key required by default) |
| 4 | **Fully local** qwen3.5:4b | `LA chat --provider ollama` |
| 5 | Answer about local work | `LA workspace` / `LA chat --cwd .` |
| 6 | **Proactive awareness** | `LA chat` → “help me edit a file” → clarify → execute |
| 7 | Agent runs terminal commands | `LA chat` → “count project LOC” |
| 8 | Audit report (Ollama $0) | `LA audit --since 7d` |

```bash
# Full product tour (recommended): 8 strengths · complete input/output
open examples/product-tour.md
# Shorter walkthrough
open examples/walkthrough.md
```

### Mem0 long-term memory — remembers you end-to-end

Memory inputs include **ChatGPT history, personal documents, and live chats**. The Warm layer is powered by the [Mem0](https://github.com/mem0ai/mem0) engine (`mem0ai` is a core dependency): **Retain → Recall → Reflect (search + LLM)**. The repo includes an “architecture decision evolution” narrative demo covering write, semantic recall, time awareness, tag browsing, and cross-memory reasoning:

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

Example files:

- [examples/product-tour.md](examples/product-tour.md) — **Product tour** (8 strengths · full I/O · ~30 min) · [中文](examples/product-tour.zh-CN.md)
- [examples/walkthrough.md](examples/walkthrough.md) — **step-by-step tutorial** (local qwen3.5:4b first)
- [examples/mem0-demo.md](examples/mem0-demo.md) — Mem0 deep dive (Retain / Recall / Reflect)
- [benchmarks/locomo/README.md](benchmarks/locomo/README.md) — **LoCoMo long-term memory benchmark**
- [examples/sample-project-notes.md](examples/sample-project-notes.md) — sample doc for `add-file`
- [examples/audit-report-sample.md](examples/audit-report-sample.md) — sample audit report (Ollama $0)
- [examples/env.local-only.example](examples/env.local-only.example) — fully local `.env` template

### Benchmark: LoCoMo long-term conversational memory

Evaluate Warm-layer cross-session memory with ACL 2024 [LoCoMo](https://github.com/snap-research/locomo).  
**Current recall scores (2026-07-13, `conv-26`, JSON backend, n=150):** Hit@1 **0.307** / Hit@5 **0.473** / Hit@8 **0.540**.

```bash
python -m benchmarks.locomo.run download
python -m benchmarks.locomo.measure_recall \
  --skip-ingest --sample-ids conv-26 \
  --work-dir benchmarks/data/runs/locomo-cursor
```

Per-category table and reproduction steps: [benchmarks/locomo/README.md](benchmarks/locomo/README.md).

### Shell completion

```bash
LA complete-init
source ~/.zshrc
```

After that, `LA memory add` + Tab suggests `add` / `add-file` and other subcommands.

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
| `LA_INTENT_CLARIFY` | Clarify intent before acting (default `1`; set `0` to disable) |
| `LA_DATA_DIR` | Custom data dir (for test isolation) |

## Commands

```bash
$ LA -h
```

```text
usage: LA [-h] <command> ...

LocalAgent — local AI personal assistant

options:
  -h, --help       show this help message and exit

commands:
  Main args and options (brackets = optional):

  <command>
    chat           [--session-id ID] [-p auto|ollama|openrouter|aiping|cursor]
                   Interactive chat
    add            <text> Write one memory directly
    add-file       [-b] <path> Symlink into kb/ and index
    tasks          [--limit N] [--tail N] [list | <task_id> |
                   delete|pause|resume|restart|logs <task_id>] Manage background index tasks
    sync-file      [--force] Scan and index all docs under data/kb/
    reset-memory   [--keep-knowledge] Clear memory and sync_index
    memory-status  Diagnose Warm memory backend (Mem0 / JSON)
    rebuild-memory
                   Clear memory then force-rebuild kb/ index
    forget         <id> [--yes] Delete one memory
    rememorize-chat
                   [--session ID] [--interactive] Re-extract memory from chat archives
    import-chatgpt
                   [path] [--dir DIR] [--force] [--interactive] Import ChatGPT export
    search         <query> [--knowledge] [--top-k N] [--verbose] Search memory or knowledge base
    reflect        <query> Cross-memory reasoning (Mem0 reflect)
    memories       [query] [--tag TAG] [--since DATE] [--sort
                   newest|oldest|relevance] Browse / query memories
    workspace      [--days N] [--cwd PATH] [--todos-only] Workspace / git / todo snapshot
    audit          [--since 7d] [--report PATH] [--cwd PATH] Audit summary and report
    config         init | list | add | remove | set-key Manage model YAML config

Use LA <command> -h for full help on a command.
```

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
└── audit/usage.jsonl          # Call audit log
```

## Architecture

Narrative arc: **fully local** → **ask first** → **long-term multi-layer memory (Mem0)** → **multi-source ingest** → **machine · profile · internet**.

```
┌─────────────────────────────────────────┐
│              LA chat (REPL)             │
│     Ollama / OpenRouter / Cursor        │
│         (clarify intent → then act)     │
└─────────────────┬───────────────────────┘
                  │ LangGraph Agent
    ┌─────────────┼─────────────┬──────────────┐
    ▼             ▼             ▼              ▼
  Hot          Warm           Cold         Web / Shell
core_profile  Mem0     Chroma+BM25   web_search / run_shell
(profile)     (long-term)   (docs)        (internet · machine)
```

- **Hot**: `core_profile.json` (pinned core facts / user profile)
- **Warm**: Mem0 memory engine (long-term; ChatGPT / chat extract)
- **Cold**: Chroma + BM25 (personal document source)
- **Agent**: LangGraph tool loop; JIT memory recall, plus web search and local Shell

See [docs/PRD.md](docs/PRD.md) and [docs/TDD.md](docs/TDD.md).

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
