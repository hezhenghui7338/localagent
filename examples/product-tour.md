# LocalAgent Product Tour

> **Goal**: In about **30 minutes**, walk through LocalAgent’s eight strengths via one coherent (fictional) user story.  
> Every step includes **full input** and **expected output** (all sample data is fictional and safe to reproduce).  
> CLI entrypoint: `la` / `LA` (equivalent).  
> [中文版](product-tour.zh-CN.md)

---

## What you will experience

| # | Strength | Section |
|---|----------|---------|
| 1 | Minimal install: install → example config → Hello World | [§1](#1-minimal-install--hello-world) |
| 2 | Remembers you across sessions: Hot profile / Warm long-term / Cold doc search | [§2](#2-cross-session-memory--hot--warm--cold) |
| 3 | Web search: even a small model can use the network appropriately | [§3](#3-web-search--small-models-can-use-the-network) |
| 4 | Real local filesystem ops + danger warnings + confirm every time | [§4](#4-local-filesystem--safety-review--approval) |
| 5 | Auditable: tokens, cost estimates, sensitive-file scan | [§5](#5-auditable--tokens-cost-sensitive-scan) |
| 6 | Proactive agent: clarify unclear intent, then execute strictly | [§6](#6-proactive-intent-clarification) |
| 7 | Multi-source memory: chat auto / `add` / `add-file` / `sync-file` / `import-chatgpt` | [§7](#7-multi-source-memory-ingest) |
| 8 | Time-aware recall priority + LLM synthesis | [§8](#8-time-aware-recall--synthesis) |

**Persona (fictional)**: You are “Alex Lin”, using LocalAgent on a Mac; prefer Americano; in May 2026 held a Shenzhen roadmap meeting; in July 2026 chose Mem0 as the memory engine.

**Tip**: Use an isolated data dir so you don’t touch daily data:

```bash
export LA_DATA_DIR=/tmp/la-product-tour
```

Anywhere below that says `data/` means `$LA_DATA_DIR/` when isolation is on.

---

## 1. Minimal install → Hello World

### 1.1 Install

**Input:**

```bash
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.2.0"
la --version
```

**Expected output:**

```text
la-localagent 0.2.0
```

> For source development: `pip install -e ".[dev]"` — same outcome.

### 1.2 Configure from the example

**Option A (recommended, JSON template):**

```bash
la config-example > /tmp/la-hello.json
# Edit then load (minimal: local Ollama)
cat > /tmp/la-hello.json <<'EOF'
{
  "provider": "ollama",
  "base_url": "http://localhost:11434",
  "model": "qwen3.5:4b",
  "api_key": "",
  "TAVILY_API_KEY": "",
  "LA_WEB_SEARCH_PROVIDER": "auto",
  "LA_SEARXNG_URL": "",
  "OPENROUTER_API_KEY": "",
  "CURSOR_API_KEY": "",
  "MINIMAX_API_KEY": ""
}
EOF
la config /tmp/la-hello.json
la config list
```

**Option B (one-liner):**

```bash
la config --provider ollama \
  --base_url "http://localhost:11434" \
  --model qwen3.5:4b
```

**Expected output (excerpt):**

```text
[config] loaded /tmp/la-hello.json
provider: ollama
base_url: http://localhost:11434
model: qwen3.5:4b
```

### 1.3 Prepare the local model (first time)

```bash
la setup -y
# or: ollama pull qwen3.5:4b
```

### 1.4 Hello World

**Input:**

```bash
la chat --provider ollama
```

Then in chat:

```text
you> In one sentence, introduce yourself and say where your data lives.
```

**Expected output (illustrative):**

```text
LocalAgent v0.2.0 …
│ qwen3.5:4b · ollama …
> In one sentence, introduce yourself and say where your data lives.
[chat] thinking…
[chat] connecting model (ollama)…
[chat] generating…
I’m LocalAgent running on your machine: chat, memory, and audit data stay in
the local data directory (e.g. ~/.localagent/ or your LA_DATA_DIR) — identity
data is not uploaded to the cloud.
[via ollama/qwen3.5:4b]
```

Type `/q` to quit. If you see the welcome screen and a reply, **install is done**.

---

## 2. Cross-session memory → Hot / Warm / Cold

Core promise: **new session or new model — same “who I am”**. Three layers:

| Layer | Stores | Typical location / command |
|-------|--------|----------------------------|
| **Hot** | Core profile & state (name, preferences, long-term goals) | `data/core_profile.json` |
| **Warm** | Structured long-term facts (Mem0 / JSON) | `la add` / chat extract / `la search` |
| **Cold** | Document passages (semantic + BM25) | `la add-file` → `la search --knowledge` |

### 2.1 Write Warm: one manual fact

**Input:**

```bash
la add "My name is Alex Lin. I prefer Americano and dislike latte."
la add "In May 2026 I held a product roadmap meeting in Shenzhen; we decided to prioritize a local personal assistant."
```

**Expected output (illustrative):**

```text
[add] remembered: My name is Alex Lin. I prefer Americano and dislike latte.
  id: a1b2c3d4 · title: Personal preference · tags: #preference/drinks
[add] remembered: In May 2026 I held a product roadmap meeting in Shenzhen…
  id: e5f6g7h8 · title: Shenzhen roadmap meeting · tags: #decision/product
```

### 2.2 Write Cold: import a document

**Input:**

```bash
la add-file examples/sample-project-notes.md
la search "three-layer memory" --knowledge
```

**Expected output (add-file):**

```text
[add-file] source: …/examples/sample-project-notes.md (1.1 KB)
[add-file] symlink: data/kb/sample-project-notes.md
  ✓ sample-project-notes.md: facts=3, chunks=5
[add-file] done
```

**Expected output (Cold search):**

```text
[search] knowledge: three-layer memory
--- hit 1 (score=0.91) ---
source: sample-project-notes.md · Architecture
LocalAgent uses a Hot / Warm / Cold memory stack:
- Hot: core_profile.json for core identity
- Warm: JSON memory / Mem0 for long-term facts
- Cold: Chroma + BM25 hybrid retrieval
```

> The sample note is bilingual-friendly; if you search in Chinese (`三层记忆架构`) you will also hit the same file.

### 2.3 Warm recall

**Input:**

```bash
la search "what do I like to drink"
```

**Expected output (illustrative):**

```text
[search] memory: what do I like to drink
Found 1 related memory (query: what do I like to drink)

### 1. Personal preference
relevance 0.88 · 2026-07-14 · preference · #preference/drinks

My name is Alex Lin. I prefer Americano and dislike latte.

source: LA memory add · id: a1b2c3d4
→ LA memory forget <id>  to delete a memory
```

### 2.4 Cross-session check (the key demo)

**Session A — add context, then quit:**

```bash
la chat --provider ollama --session-id tour-a
```

```text
you> Remember: next week I’ll demo LocalAgent’s memory layers to the team.
assistant> Got it — noted that you’ll demo the memory layers next week.
you> /q
```

**Session B — brand-new session, same person:**

```bash
la chat --provider ollama --session-id tour-b
```

```text
you> What’s my name? What do I like to drink? What meeting did I have in Shenzhen in May?
```

**Expected output (illustrative):**

```text
[chat] thinking…
[chat] calling search_memory…
You’re Alex Lin; you prefer Americano (dislike latte).
In May 2026 you held a Shenzhen product roadmap meeting and decided to prioritize a local personal assistant.
[via ollama/qwen3.5:4b]
```

> **Contrast**: A typical chat client “forgets” across sessions. LocalAgent recalls from Warm/Hot — **not from the current session transcript**.

### 2.5 See all three layers at a glance

```bash
# Hot
cat "${LA_DATA_DIR:-data}/core_profile.json" 2>/dev/null || echo "(profile enriches over chat/import)"

# Warm
la search "Alex Lin" --top-k 3

# Cold
la search "qwen3.5:4b" --knowledge --top-k 2
```

---

## 3. Web search → small models can use the network

Default: **no API key** (`ddgs`). The small model decides *when* to search and *how* to summarize; the network supplies facts.

**Input:**

```bash
la chat --provider ollama
```

```text
you> What’s the weather in Beijing today? One or two sentences, and note that it came from the web.
```

**Expected output (illustrative):**

```text
[chat] thinking…
[chat] connecting model (ollama)…
[chat] generating…
[chat] calling web_search: Beijing weather today
[chat] synthesizing tool results (round 2)…
From a live web search: today in Beijing … (temp / conditions). Source: real-time search; for reference only.
[via ollama/qwen3.5:4b]
```

**Deep research (optional):**

```text
you> /deepsearch open-source LLM news in 2026 — three bullets
assistant> [multi-step search + local model summary → structured bullets]
```

Optional upgrade: set `TAVILY_API_KEY` in config; `auto` prefers Tavily.

> **Contrast**: Even `qwen3.5:4b` can ground answers via tools instead of inventing live facts.

---

## 4. Local filesystem → safety review & approval

The agent can run real local commands / write files. **Approval is required by default**; dangerous commands get an extra warning; extreme commands are hard-blocked.

### 4.1 Safe read-only command (still needs approval)

**Input:**

```bash
la chat --cwd . --provider ollama
```

```text
you> Roughly how many lines of Python are in this project? Use the shell.
```

**Expected output:**

```text
[chat] thinking…
[chat] calling run_shell: find . -type f -name "*.py" …
[chat] waiting for your approval…
⚠ Agent wants to run a command. Confirm before it executes.
Command: find . -type f -name "*.py" -not -path "*/.*" | xargs wc -l | tail -1
Allow? [y/N] y
[chat] synthesizing tool results (round 2)…
About N lines of Python in the current project.
[via ollama/qwen3.5:4b]
```

Answer `n` and the agent will **not** run the command.

### 4.2 Dangerous command: extra warning

**Input:**

```text
you> Delete the tmp-demo folder in the workspace with rm -rf
```

**Expected output:**

```text
[chat] calling run_shell: rm -rf ./tmp-demo
[chat] waiting for your approval…
⚠ Agent wants to run a command. Confirm before it executes.
Risk: delete files/directories
Command: rm -rf ./tmp-demo
⚠ This looks dangerous. Proceed anyway? [y/N]
```

### 4.3 Hard block (never executes)

Attempts like deleting `/` are **blocked** immediately:

```text
Error: deleting the filesystem root is forbidden.
```

### 4.4 File writes also need approval

**Input (once intent is clear):**

```text
you> Create hello-tour.txt in the workspace root with one line: LocalAgent product tour
```

**Expected output (excerpt):**

```text
[chat] calling write_file…
⚠ Agent wants to write a file. Confirm before it executes.
Risk: overwrite local file
Target: hello-tour.txt (overwrite, … chars)
Preview: LocalAgent product tour
⚠ This looks dangerous. Proceed anyway? [y/N] y
Wrote hello-tour.txt.
```

Policy (`LA_TOOL_APPROVAL`, default `always`):

| Value | Behavior |
|-------|----------|
| `always` (default) | Confirm every `run_shell` / `write_file` |
| `dangerous` | Confirm only risky ops |
| `off` | Disabled (not recommended) |

---

## 5. Auditable → tokens / cost / sensitive scan

Model calls from earlier steps land in local `data/audit/usage.jsonl`.

**Input:**

```bash
la audit --since 7d
la audit --since 7d --report /tmp/la-tour-audit.md
```

**Expected output (interactive summary, illustrative):**

```text
[audit] summary (7d)
  calls: 47  tokens: 31,280  est. cost: $0.0000
    ollama: 42 calls, 28,450 tokens, $0.0000
    ddgs: 5 calls, 0 tokens, $0.0000

file safety: no high-risk items
memory health: facts=12 · knowledge_chunks=38

→ LA audit --report report.md  to export a full report
```

**Report excerpt** (same structure as [audit-report-sample.md](audit-report-sample.md)):

```markdown
## Tokens & service cost
| Provider | Calls | Tokens | Est. cost (USD) |
|----------|-------|--------|-----------------|
| ollama   | 42    | 28450  | $0.0000         |

## File safety
No high-risk items.

## Memory health
facts=12 · knowledge_chunks=38 · bm25=ready · chroma=ready
```

> **Contrast**: Ollama local calls cost **$0**; sensitive paths / accidental indexing show up under file safety; export Markdown for records.

---

## 6. Proactive intent clarification

Principle: **interrupt sparingly** — memory recall and read ops act immediately; only **high-cost ambiguity** (e.g. “edit a file” with no path) asks **one** clarifying question; then execute strictly to that intent.

### 6.1 Vague request → ask (don’t guess-write)

**Input:**

```bash
la chat --provider ollama
```

```text
you> help me edit a file
```

**Expected output:**

```text
Before I continue, I want to confirm your intent:

1. Which file should be modified, or what is the full path?
2. What exactly should change?

Please add details and I’ll continue from there.
```

### 6.2 After clarification — execute strictly

```text
you> Edit tour-note.txt in the project root; append one line: cross-session persistence test
```

**Expected output (illustrative):**

```text
[chat] thinking…
[chat] calling write_file…
⚠ Agent wants to write a file. Confirm before it executes.
…
Allow? / Proceed anyway? [y/N] y
Successfully appended to tour-note.txt.
```

### 6.3 Memory questions → no clarify, just recall

```text
you> what do I like to drink?
```

**Expected output:**

```text
[chat] calling search_memory…
You prefer Americano and dislike latte.
```

(Won’t treat this as a “recommend a drink” scenario.)

Disable clarification if needed: `LA_INTENT_CLARIFY=0`.

---

## 7. Multi-source memory ingest

| Source | Command / when | Notes |
|--------|----------------|-------|
| Chat auto-detect | during / after `la chat` | Facts from natural conversation |
| Manual one-liner | `la add "…"` | Precise write |
| Document extract | `la add-file <path>` | Symlink + Warm facts + Cold full text |
| Directory sync | `la sync-file` | Index everything under `data/kb/` |
| ChatGPT export | `la import-chatgpt <json>` | Personal memories from history |

### 7.1 Manual add (also covered in §2)

```bash
la add "In July 2026 we finalized Mem0 as the Warm-layer memory engine."
```

### 7.2 Document auto-extract

```bash
la add-file examples/sample-project-notes.md
# If multiple notes are already symlinked under kb/:
la sync-file
```

**Expected output (sync-file, illustrative):**

```text
[sync-file] scanning data/kb/ …
  ✓ sample-project-notes.md: facts=3, chunks=5 (unchanged, skip)
[sync-file] done · indexed=0 · skipped=1
```

Use `--force` to rebuild indexes.

### 7.3 ChatGPT-format import

Use an OpenAI data-export `conversations.json`, or this minimal sample:

```bash
cat > /tmp/chatgpt-sample.json <<'EOF'
[
  {
    "conversation_id": "demo-1",
    "title": "Preferences",
    "create_time": 1757058223.0,
    "update_time": 1757058263.0,
    "current_node": "a",
    "mapping": {
      "r": {"id": "r", "parent": null, "message": null},
      "u": {
        "id": "u", "parent": "r",
        "message": {
          "author": {"role": "user"},
          "content": {"content_type": "text", "parts": ["I usually use Python for data analysis and prefer VS Code as my editor."]},
          "create_time": 1757058223.1
        }
      },
      "a": {
        "id": "a", "parent": "u",
        "message": {
          "author": {"role": "assistant"},
          "content": {"content_type": "text", "parts": ["Got it."]},
          "create_time": 1757058223.2
        }
      }
    }
  }
]
EOF

la import-chatgpt /tmp/chatgpt-sample.json
la search "VS Code"
```

**Expected output (illustrative):**

```text
[import-chatgpt] parsing 1 conversation …
[import-chatgpt] extracting candidate memories …
[import-chatgpt] done · conversations=1 · memories+=1
…
[search] memory: VS Code
### 1. …
I usually use Python for data analysis and prefer VS Code as my editor.
source: import-chatgpt · …
```

### 7.4 Auto-detect from chat

```bash
la chat --session-id tour-auto --provider ollama
```

```text
you> By the way, my long-term goal is to make LocalAgent a local assistant that truly knows me.
assistant> … (normal reply)
you> /q
```

Then:

```bash
la search "long-term goal"
```

You should recall related facts (wording depends on the extract pipeline; use `la rememorize-chat --session tour-auto` to re-extract if needed).

---

## 8. Time-aware recall → synthesis

Memories carry an **event time**. If the question implies a time window (“May 2023”, “last week”, “now”), recall **raises temporal weight**, prefers that window, then the LLM synthesizes the answer.

### 8.1 Same topic, different times

```bash
la add "In May 2026, after an architecture review we tried a lightweight approach and had not yet chosen Mem0."
la add "In July 2026 we finalized Mem0: lighter and faster; reflect is search + a local LLM."
```

### 8.2 Time-scoped Warm search

**Input:**

```bash
la search "May 2026 memory engine choice" --verbose
la search "July 2026 memory engine choice" --verbose
```

**Expected behavior:**

- May query → tops the “not yet chosen / lightweight” memory (`temporal_score` higher)  
- July query → tops the “finalized Mem0” memory  

Illustrative:

```text
[search] memory: May 2026 memory engine choice
### 1. …
relevance 0.91 · temporal alignment 0.95 · 2026-05-…
In May 2026, after an architecture review we tried a lightweight approach and had not yet chosen Mem0.
```

### 8.3 Cross-memory reasoning (Reflect)

**Input:**

```bash
la reflect "How did the memory-engine choice evolve?"
```

**Expected output (illustrative):**

```text
[reflect] query: How did the memory-engine choice evolve?
Recalled 2 memories; synthesizing…

In May 2026 you were still trying a lightweight approach and had not finalized;
by July 2026 you chose Mem0 for being lighter/faster, with reflect via search + local LLM.
Overall: exploration → decision.
```

### 8.4 Ask time questions in chat

```bash
la chat --provider ollama
```

```text
you> What’s my final decision on the memory engine now? What about in May?
```

**Expected output (illustrative):**

```text
[chat] calling search_memory…
As of now you’ve finalized Mem0.
In May you were still trying a lightweight approach and had not chosen yet.
```

> **Contrast**: Not “most semantically similar wins,” but **question time-scope × memory event time** alignment, then reasoning — the key to answering “then vs now” correctly.

---

## One-shot script (optional)

Non-interactive commands in an isolated dir:

```bash
export LA_DATA_DIR=/tmp/la-product-tour
rm -rf "$LA_DATA_DIR"
mkdir -p "$LA_DATA_DIR"

la add "My name is Alex Lin. I prefer Americano and dislike latte."
la add "In May 2026 I held a product roadmap meeting in Shenzhen; we decided to prioritize a local personal assistant."
la add "In May 2026, after an architecture review we tried a lightweight approach and had not yet chosen Mem0."
la add "In July 2026 we finalized Mem0: lighter and faster."

la add-file examples/sample-project-notes.md
la search "what do I like to drink"
la search "three-layer memory" --knowledge
la search "May 2026 memory engine" --verbose
la search "July 2026 memory engine" --verbose
la reflect "How did the memory-engine choice evolve?"
la workspace --cwd .
la audit --since 7d

echo "Demo data: $LA_DATA_DIR"
```

Interactive bits (web search, shell approval, intent clarify) still need §3 / §4 / §6 by hand — that’s the “proactive agent” feel.

---

## Acceptance checklist

After the tour you should be able to check:

- [ ] Install + example config → `la chat` Hello World works  
- [ ] New `--session-id` still answers name / drink / May meeting  
- [ ] `search` vs `search --knowledge` shows Warm vs Cold  
- [ ] Small-model chat auto-calls `web_search` with grounded answers  
- [ ] Shell / write prompts for approval; dangerous ops show a risk warning  
- [ ] `la audit` shows tokens & cost (Ollama = $0)  
- [ ] “help me edit a file” clarifies first, then writes after details  
- [ ] At least one success each: `add` / `add-file` / `sync-file` / `import-chatgpt`  
- [ ] May vs July queries rank different memories; `reflect` explains the arc  

---

## Next steps

| Resource | Notes |
|----------|-------|
| [product-tour.zh-CN.md](product-tour.zh-CN.md) | Chinese version of this tour |
| [walkthrough.md](walkthrough.md) | Shorter 6-scenario intro |
| [mem0-demo.md](mem0-demo.md) | Mem0 Retain / Recall / Reflect deep dive |
| [audit-report-sample.md](audit-report-sample.md) | Full audit report sample |
| [../docs/PRD.md](../docs/PRD.md) · [../docs/TDD.md](../docs/TDD.md) | Product & technical design |
| [../benchmarks/locomo/README.md](../benchmarks/locomo/README.md) | LoCoMo long-term memory benchmark |

Open an Issue if something fails; when you’re happy, drop `LA_DATA_DIR` and start importing your own notes and ChatGPT history.
