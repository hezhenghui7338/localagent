<p align="center">
  <img src="assets/logo.zh-CN.png" alt="LocalAgent" width="360">
</p>

<p align="center">
  <strong>Local First. Memory Forever. Actions Automated.</strong>
</p>

<p align="center">
  <a href="https://localagent.zhenghui7338.workers.dev/">官网</a> ·
  <a href="./README.md">English</a> · <b>中文</b>
</p>

# <img src="assets/logo-icon.png" alt="LA" width="36" valign="middle"> LocalAgent

> **本地 AI：记得住你，也能把事办完。**

## 快速开始

Python 3.10+ · [pipx](https://pipx.pypa.io/) · 当前 **v0.5.0**

```bash
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.5.0"
la
```

有 API → `la config set-key openrouter sk-...`（或改 `~/.localagent/.env`）  
无 API → `la setup -y`（装 Ollama + `qwen3.5:4b`）

日常旁路：`la summarize <path>` · `la news brief` · `la polish`  
升级 / 开发 / 卸载 → [安装与升级](#安装与升级)

## 要求

- Python 3.10+
- **至少一种推理路径**：本机模型服务（如 Ollama）**或** 云端 API（OpenRouter / OpenAI / Cursor 等）
- **没有 API 时推荐**：[Ollama](https://ollama.com/)，默认 `qwen3.5:4b`（`la setup` 可装，可跳过）

## 特性

默认本地跑通；可选云端与联网。详解：[一键总结 · 新闻嗅探 · 一键润色](#日常实用一键总结--新闻嗅探--一键润色)。

| 我想… | 怎么做 |
| --- | --- |
| 一键装好、马上聊天 | `la` / `la setup` · [安装与升级](#安装与升级) |
| 改源码、跑测试 | [开发者安装](#开发者安装) |
| 用自己的 API Key | [配置](#配置) · `la config` |
| 跨会话被记住 | Hot / Warm / Cold + Mem0；ChatGPT 历史可 `LA memory ingest chatgpt` · [产品体验 §3–4](examples/product-tour.zh-CN.md) |
| 文档进知识库并深度召回 | `LA rag add` / `rag search` · [产品体验 §5](examples/product-tour.zh-CN.md) |
| **一键总结**文档（默认进 `sum>` 深聊） | `la summarize <path>`；`/keep` 或 `--keep` 入库；仅速读加 `--no-chat` |
| **新闻嗅探** / 今日简报 | `la news sync` → `la news brief`（TTY ↑↓ / `o` 打开 / `r` 精读深聊）；`la news schedule on` |
| **一键润色**文案（默认复制主推） | `la polish` / `/polish` · `--scene` / `--tone` / `--no-copy` |
| 联网搜索 | 默认 ddgs；`LA chat` 或 `/deepsearch` · [产品体验 §6](examples/product-tour.zh-CN.md) |
| 本机 Shell / 写文件（危险命令拦截） | `run_shell` / `write_file`；执行前确认 · [本地 Shell](#亮点actions-automated--本地-shell-真正动手) |
| 看今日待办信号 | `la status` |
| 看清 token / 费用 | `LA audit` · [产品体验 §8](examples/product-tour.zh-CN.md) |
| 多模型切换 | Ollama / OpenRouter / Cursor；`auto` 按优先级降级 |

### 产品设计

1. **Local First** — 默认零账单路径：对话 / 记忆 / 检索 / 工具可纯本地跑通；主路径三命令（`la` · `la setup` · `la chat`）；可选云端与联网——身份、记忆与审计始终留本机  
2. **Memory Forever** — Hot / Warm / Cold + Mem0 跨会话持久；该记则记、不该记则跳过；本地 RAG + ChatGPT 导入；换模型不换身份  
3. **Actions Automated** — Shell / 写文件 / 工作区；`la summarize` · `la news` · `la polish`；定时简报；执行前确认、危险硬拦、办完有回执；`la status` 看今日信号  

| 普通本地 Chat | LocalAgent |
| --- | --- |
| 云端账单与账号门槛 | **Local First** — 默认零成本 Ollama，可选自有 API |
| 聊完就忘，或只会死记 | **Memory Forever** — 会取舍的分层记忆 + 本地 RAG |
| 只会聊天，事还得你自己办 | **Actions Automated** — 工具 · 旁路 · 定时；确认门 + 硬拦截 |

可选 OpenRouter / Cursor / Tavily；**身份与数据始终留本机**。需求见 [docs/PRD.md](docs/PRD.md)；约 30 分钟跑通见 [examples/product-tour.zh-CN.md](examples/product-tour.zh-CN.md)。

### TODO · 敬请期待

- **本周期尚未做**：工作区 watcher 增量索引、外部任务源、无人值守定时 Shell。

### 我们相信什么

- AI 是革命性技术，必须拥抱；旁观一万遍，不如一键下载、亲手调试  
- 「书读百遍其义自见」不会自动发生——你需要的是实践  
- LA 只摘**低垂、成熟**的 AI 果实；不引入失控、昂贵、难维护的重栈  
- LA **只做一件事**：本地 AI——记得住你，也能把事办完。数据留本地，本地可完整跑通；不拒绝联网与新技术，但默认不设障碍  
- 消除使用 AI 的门槛，而不是设置门槛

## 安装与升级

国内访问 GitHub 不稳时先开代理（依赖含 spaCy 等，装得慢属正常）。

```bash
# pin 版本（推荐）
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.5.0"
# 或跟踪默认分支 / 用 pip
# pipx install "git+https://github.com/hezhenghui7338/localagent.git"
# pip install "git+https://github.com/hezhenghui7338/localagent.git@v0.5.0"

la --version
# 升级到新 tag：先卸再装
pipx uninstall la-localagent
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.5.0"
# --force 且报 venv 已存在时：UV_VENV_CLEAR=1 pipx install --force "…"
# 跟踪默认分支：pipx upgrade la-localagent
```

版本：[Releases](https://github.com/hezhenghui7338/localagent/releases) / [Tags](https://github.com/hezhenghui7338/localagent/tags)。首次运行会建 `~/.localagent/`。

```bash
la                 # = la chat
la setup           # 引导装 Ollama（可跳过）
la setup -y
la config --provider ollama --base_url "http://localhost:11434" --model qwen3.5:4b
# 或：la config-example > my.json && la config my.json && la config list
```

> PyPI 发布后：`pipx install la-localagent==0.5.0`

### 开发者安装

```bash
git clone git@github.com:hezhenghui7338/localagent.git
cd LocalAgent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# 或：uv sync --extra dev
```

源码 checkout：配置/数据在仓库内（`.env`、`data/`）；普通安装在 `~/.localagent/`。测试见 [开发](#开发)。

### 卸载

```bash
pipx uninstall la-localagent   # 或：pip uninstall la-localagent
rm -rf ~/.localagent           # 可选：清配置与数据；源码安装则删仓库内 .env / data/
ollama rm qwen3.5:4b           # 可选：Ollama 独立，不会随 LA 自动卸
```

## 功能示例

### 亮点：Local First

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

### 亮点：Actions Automated —— 本地 Shell 真正动手

普通 Chat 只会告诉你「去终端运行 `find … | wc -l`」。LocalAgent 的 Agent 会**自己调用 `run_shell` 工具**，在工作区执行命令并把结果整理成回答——全程纯本地 `qwen3.5:4b`，无需云端 API。办完后附带 Action receipt；安全操作可会话内 approve-once。

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

### 日常实用：一键总结 · 新闻嗅探 · 一键润色

这三个旁路能力不走「漫长 Agent 工具循环」，专为**每天会用到**的场景设计：读文档、刷资讯、改文案。

#### 1. 一键总结 `la summarize` —— 3 分钟读懂 + 围绕文档深聊

```bash
la summarize ~/Documents/方案.pdf          # 速读卡 → 进入 sum> 文档对话
la summarize notes.md --no-chat            # 只要卡片，不进对话（可多文件）
la summarize report.xlsx --keep            # 总结后同时入库（长期召回）
```

- 输出：最多三句话总结 + 带 〔§章节 | p.页〕索引的结构化要点
- **默认不入库**；在 `sum>` 里 `/keep` 或启动时加 `--keep`
- 在 `sum>` 里直接提问即可围绕该文件深入讨论（`/summary` 重看卡片，`/exit` 结束）

#### 2. 新闻嗅探 `la news` —— 从信任信源到今日简报

默认订阅 [BestBlogs](https://www.bestblogs.dev/) AI 精选 RSS（可改 `LA_NEWS_RSS_URL`）：

```bash
la news sync                 # 拉取最新条目
la news brief                # TTY：交互浏览器（推荐）
la news brief --no-ui        # 一次性打印全部简报
la news schedule on          # 每天 08:00 自动 sync（可 off）
la news interests --add Agent # 兴趣加权
```

交互简报键位：

| 键 | 作用 |
|----|------|
| ↑↓ / j k | 切换文章（一屏只看当前条） |
| o / Enter | 系统浏览器打开原文 |
| s | 速读卡 |
| r | 精读 → 进入与 summarize 同款深聊；`/exit` 回到简报 |
| b / x / c | 收藏 / 跳过 / 复制链接 |
| q | 退出 |

进入 `la` / `la chat` 时，若早间已 sync，会提示「今日更新已准备好」。

#### 3. 一键润色 `la polish` —— 改完就能发

```bash
la polish "催一下进度的草稿"                    # 识别场景，主推进剪贴板
la polish --scene email --tone 更正式 "……"
la polish --no-copy --file draft.txt           # 不写剪贴板（脚本友好）
```

会话内：`/polish --scene email 您好，上次说的方案…`

输出含【识别】【主推】【备选】【改动】；TTY 下可按 `2`/`3` 把备选拷到剪贴板。简历场景不会编造原文没有的数字。

仓库提供 **产品体验教程**（用户故事驱动 · 完整输入输出 · 约 30 分钟）与更短的 walkthrough：

| #   | 场景                   | 命令                                      |
| --- | -------------------- | --------------------------------------- |
| 1   | 单条记忆写入与召回            | `LA memory add` → `LA memory search`                  |
| 2   | Markdown 知识库导入与召回   | `LA rag add` → `LA rag search` |
| 3   | **一键总结**本地文档         | `la summarize <path>` → `sum>` 深聊 |
| 4   | **新闻嗅探**今日简报         | `la news sync` → `la news brief` |
| 5   | **一键润色**邮件/朋友圈草稿    | `la polish "草稿"` / `/polish` |
| 6   | 联网搜索最近新闻             | `LA chat` 或 `/deepsearch`（默认无需 Key） |
| 7   | **纯本地运行** qwen3.5:4b | `LA chat --provider ollama`             |
| 8   | Agent 自动执行终端命令       | `LA chat` → 「统计当前项目代码行数」              |
| 9   | 审计报告（Ollama 零费用）     | `LA audit --since 7d`                   |

```bash
# 产品体验教程（推荐）：用户故事 · 完整输入输出
open examples/product-tour.zh-CN.md
# 更短的分步 walkthrough（中文）
open examples/walkthrough.zh-CN.md
# English walkthrough
open examples/walkthrough.md
```

更完整的叙事与验收对照见 [docs/PRD.md](docs/PRD.md)。

### 亮点：Memory Forever —— 全方位记住你

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

- 默认模型 `qwen3.5:4b`；若未安装，LA 会改用本机已有对话模型（优先已加载到内存的），仅在没有任何可用模型时才提示拉取默认模型
- Qwen3 系列默认生成大量 thinking token，LocalAgent 默认 `OLLAMA_THINK=0` 关闭思考模式
- 本地 Ollama 较慢时，`auto` 模式默认 **12 秒**内降级到下一优先级（如 OpenRouter）。可改：`.env` 里 `LA_OLLAMA_CHAT_TIMEOUT=20`，或 `config/model_servers.yaml` 里 ollama 的 `chat_timeout: 20`；也可在 chat 中 `/provider openrouter` 手动切换

## 配置

详见 [`.env.example`](.env.example)，常用变量：

| 变量                                      | 说明                                               |
| --------------------------------------- | ------------------------------------------------ |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL`      | 本地 Ollama 地址与模型                                  |
| `OPENAI_API_KEY` / `OPENAI_MODEL`       | OpenAI 直连（或任意兼容端点，见 `model_servers.yaml`） |
| `OPENROUTER_API_KEY` / `CURSOR_API_KEY` | 其他云端模型降级                                         |
| `TAVILY_API_KEY`                        | 可选；配置后 `auto` 优先用 Tavily 联网搜索           |
| `LA_WEB_SEARCH_PROVIDER`                | 联网后端：`auto`（默认）/ `ddgs` / `tavily` / `searxng` |
| `LA_SEARXNG_URL`                        | 可选；自托管 SearXNG 地址（如 `http://localhost:8080`） |
| `LA_OLLAMA_CHAT_TIMEOUT`                | auto 下本地 Ollama 首包超时秒数（默认 `12`，超时则降级） |
| `LA_MODEL_PROVIDER_PRIORITY`            | auto 模式优先级，默认 `ollama,openai,openrouter,cursor` |
| `LA_WORKSPACE`                          | 工作区根目录（Git / 文件 / 待办 / shell 命令上下文）              |
| `LA_SHELL_TIMEOUT` / `LA_SHELL_MAX_OUTPUT` | Agent `run_shell` 超时秒数与输出截断上限（默认 30s / 12000 字符） |
| `LA_TOOL_APPROVAL`                      | 工具执行前用户确认：`always`（默认，每次）/ `dangerous`（仅危险）/ `off` |
| `LA_DATA_DIR`                           | 自定义数据目录（测试隔离用）                                   |
| `LA_NEWS_RSS_URL`                       | 新闻嗅探 RSS（默认 BestBlogs AI 精选）                      |
| `LA_NEWS_AUTO_SYNC` / `_HOUR`           | 早间自动 sync 意图与时刻（配合 `la news schedule on`）       |
| `LA_SUMMARIZE_SHORT_MAX_CHARS`          | 一键总结短路径字数上限（默认 12000）                            |
| `LA_LOG_LEVEL`                          | 诊断日志级别：`INFO`（默认）/ `DEBUG` / `WARNING` …           |

## 命令

日常以对话为主。外层命令与会话内 `/command` 同路径（如 `/memory add` ≡ `LA memory add`）。会话快捷方式：`/add` → `memory add`，`/search` → `memory search`（会话内禁止再开 `/chat`）。

```bash
$ LA -h
```

```text
usage: LA [-h] <command> ...

LocalAgent — 本地个人 AI 助手

主路径：
  la / la chat     对话
  la setup [-y]    安装/拉取本地 Ollama 模型
  la config …      纯本地或自有 API

日常：
  LA memory add|search|pending|approve|reject|forget
  LA memory ingest chatgpt <path>   # 导入 ChatGPT 导出
  LA rag add|search                 # 文档 → Cold 知识库
  la summarize <path>               # 一键总结 → 文档对话（默认不入库）
  la news sync|brief|schedule       # 新闻嗅探 / 今日简报
  la polish "草稿"                   # 一键润色（默认复制主推）
  LA audit                          # 花费 / 安全报告

运维（高级）：
  memory ingest chat|all · query · reflect · status · reindex · reset · graph
  rag ingest|rebuild|reset · tasks · workspace · logs · websearch
  news skim|read|mark|interests|status|sources
```

`LA logs` 查看运行时诊断日志（`data/logs/localagent.log`）——provider 降级、记忆召回命中、agent 重试等。与 `LA audit`（用量/费用/护栏）不同。开发时可 `LA --debug <command>` 或设置 `LA_LOG_LEVEL=DEBUG`，DEBUG 日志会同步打到 stderr。

对话输入基于 [prompt_toolkit](https://github.com/prompt-toolkit/python-prompt-toolkit)（Unicode 安全编辑与 Tab 补全，规避 macOS libedit 的 CJK 问题）。

## 数据目录

运行时数据默认位于 `data/`（已在 `.gitignore` 中排除，不会提交到 Git）：

```
data/
├── kb/                        # 软链接的个人文件
├── core_profile.json          # Hot 层核心事实
├── news/                      # 新闻嗅探：articles.sqlite · profile · sync_state · cache/
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

有副作用的工具受门控（`always` / `dangerous` / `off`）。极端危险命令（如 `rm -rf /`）直接拦截。

### 模型路由

`ModelRouter` 统一 **Ollama**（默认本地）、**OpenAI**、**OpenRouter**、**Cursor**。`auto` 模式按 `LA_MODEL_PROVIDER_PRIORITY` 降级。算力默认本机（Ollama），可扩展到 OpenAI / OpenRouter / Cursor 等；模型与 LocalAgent 正交——小模型可跑通基本任务，更好的模型效果更好。会话、记忆与审计由 LocalAgent 落盘保管。

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
2. 打并推送同号 tag：`git tag v0.5.0 && git push origin v0.5.0`
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
