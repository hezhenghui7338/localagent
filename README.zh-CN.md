<p align="center">
  <img src="assets/logo.zh-CN.png" alt="LocalAgent" width="360">
</p>

<p align="center">
  <strong>Your AI. Your Data. Your Mac.</strong>
</p>

<p align="center">
  <a href="./README.md">English</a> · <a href="./README.zh-CN.md">中文</a>
</p>

# <img src="assets/logo-icon.png" alt="LA" width="36" valign="middle"> LocalAgent

> **完全本地 · 主动追问 · 长期懂你 — 打通本机、用户画像与互联网，真正可用。**

LocalAgent（`LA`）不是又一个 Chat 客户端，而是跑在你本机上的**主动式个人 AI**。核心叙事：

1. **完全本地化** — 默认 Ollama `qwen3.5:4b`，对话、记忆、检索与执行全链路可纯本地跑通，身份与数据不出本机  
2. **主动意识** — 少打扰优先：该做时直接做；轻微模糊则假设推进并说明；仅高代价模糊才追问 1 个关键问题  
3. **长期、多层次记忆** — Hot / Warm / Cold 分层，真正「懂你」的助手  
4. **记忆从哪来** — **ChatGPT 历史对话**、个人文档、日常对话均可入库，配合强大的 **Mem0** 记忆引擎全方位记住用户  
5. **真正可用** — 联网查询 + 本地 Shell，打通**电脑本地 · 用户画像 · 互联网**三层能力

```bash
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.2.0"
la --version                    # 确认版本：la-localagent 0.2.0
la                              # 首次若无 Ollama 会询问是否安装（可跳过）
```

| 普通本地 Chat | LocalAgent |
| --- | --- |
| 云端或半本地，数据边界模糊 | **完全本地**，身份与记忆留在本机 |
| 指代不明也硬猜、直接改文件 | **少打扰 + 该问才问**：读操作/记忆回忆直接做；高代价模糊才追问 |
| 聊完就忘 | **长期多层次记忆** + Mem0，跨会话懂你 |
| 记忆只能靠本轮聊天 | ChatGPT 历史 / 个人文档 / 对话 **多源冷启动** |
| 不会搜网、不会跑命令 | **联网搜索** + **本地 Shell**，本机 · 画像 · 联网打通 |

可选接入 OpenRouter / Cursor / Tavily 做增强，但**身份与数据始终留在本机**。

## 特性

- **完全本地化**：默认 `qwen3.5:4b`，对话、记忆写入、检索、工作区感知、Shell 执行全链路本地跑通；可选云端模型，数据仍归本机
- **主动意识**：三档决策（直接做 / 假设推进 / 追问）；文件写入另有幻觉检测兜底
- **长期多层次记忆**：Hot（核心画像）/ Warm（长期记忆）/ Cold（文档原文），按需 JIT 召回，真正懂你
- **Mem0 + 多源输入**：ChatGPT 历史、个人文档、日常对话 → 同一管线；配合强大的 **Mem0** 记忆引擎全方位记住用户
- **本机 · 画像 · 联网三层打通**：工作区感知 + `run_shell` 本地执行 + 联网搜索（默认 ddgs，可选 Tavily / SearXNG），真正可用
- **执行前确认**：`run_shell` / `write_file` 默认每次需用户审核；危险命令额外警告，确认后才执行
- **文档知识库**：软链导入个人文件，Chroma + BM25 混合检索
- **多模型对话**：Ollama / OpenRouter / Cursor 统一入口，`auto` 模式按优先级自动降级
- **可审计**：Token 消耗、费用估算、敏感文件扫描，可导出 Markdown 报告

## 要求

- Python 3.10+
- [Ollama](https://ollama.com/) + `qwen3.5:4b`（推荐，也是项目默认配置）
- 可选：[pipx](https://pipx.pypa.io/)（推荐，用于全局 `la` 命令）

## 快速开始

### 一键安装（推荐）

当前发布版本：**v0.2.0**（与 `src/localagent/__init__.py` / `la --version` 一致）。

```bash
# 安装指定版本（推荐，可复现）
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.2.0"

# 或跟踪默认分支最新提交（无版本保证）
pipx install "git+https://github.com/hezhenghui7338/localagent.git"

# 或用 pip 装进当前 Python 环境
pip install "git+https://github.com/hezhenghui7338/localagent.git@v0.2.0"

# mem0ai 已包含在主依赖中，无需额外安装
```

查看版本与升级：

```bash
la --version                  # 或 la -V → la-localagent 0.2.0

# 升到某个新 tag（改掉 @vX.Y.Z 后 --force 重装）
pipx install --force "git+https://github.com/hezhenghui7338/localagent.git@v0.2.0"

# 跟踪默认分支时，拉最新 tip
pipx upgrade la-localagent
# 或
pipx install --force "git+https://github.com/hezhenghui7338/localagent.git"

# pip 环境同理
pip install --upgrade --force-reinstall \
  "git+https://github.com/hezhenghui7338/localagent.git@v0.2.0"
```

可用版本见 GitHub [Releases](https://github.com/hezhenghui7338/localagent/releases) / [Tags](https://github.com/hezhenghui7338/localagent/tags)。

然后在**任意目录**：

```bash
la                 # 等同于 la chat；无 Ollama 时询问是否安装
la setup           # 单独引导安装/拉取（可答 n 跳过）
la setup -y        # 无需确认，直接安装并拉取 qwen3.5:4b
la chat --provider ollama
```

首次运行会在 `~/.localagent/` 创建配置、`.env` 与数据目录。填写 API Key：

```bash
# 极简参数
la config --provider ollama --base_url "http://localhost:11434" --model qwen3.5:4b --TAVILY_API_KEY "tvly-..."

# 或复制模板改写后加载
la config-example > my.json   # 查看/保存模板
la config my.json

# 查看当前配置
la config list
```

> 发布到 PyPI 后可直接：`pipx install la-localagent==0.2.0` / `pipx upgrade la-localagent`

### 源码开发安装

```bash
git clone git@github.com:hezhenghui7338/localagent.git
cd LocalAgent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

源码 checkout 时配置与数据仍在仓库内（`.env`、`data/`）；普通安装后则落在 `~/.localagent/`。

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
| 对话 `LA chat` | 否 | 默认 `qwen3.5:4b`，普通 Mac 可跑 |
| 单条记忆 `LA memory add` | 否 | 本地模型提取标题/标签 |
| 文件导入 `LA memory add-file` | 否 | 默认启发式提取，不调用 LLM |
| 记忆/知识检索 `LA memory search` | 否 | BM25 + Chroma 本地检索 |
| 工作区 `LA workspace` | 否 | 读本地 Git / 文件 / TODO |
| Agent 执行命令 `run_shell` | 否 | 本地 4B 模型自动调用 shell 并汇总输出 |
| 审计 `LA audit` | 否 | 读本地 usage.jsonl |
| 联网搜索 | 否（默认 ddgs） | 开箱可用；可选 Tavily / 自托管 SearXNG 提升质量 |

```bash
# 纯本地模式：普通 Mac + Ollama，无需付费 API
cp examples/env.local-only.example .env
ollama pull qwen3.5:4b
LA chat --provider ollama
```

### 亮点：主动意识——模糊意图先追问

普通 Chat 收到「帮我改个文件」往往会猜一个路径直接覆盖；LocalAgent 具有**主动意识**：先做一次**轻量意图预检**（默认开启），按三档决策——**act** 直接做、**assume** 带假设推进、**clarify** 只在高代价模糊时追问 **1** 个具体问题。个人偏好回忆（如「我喜欢喝什么」）一律直接查记忆，不会当成推荐场景追问。文件写入还有**幻觉检测**：若模型声称「已写入」却未调用 `write_file`，会自动重试或明确报错，而不是展示编造的空内容。

```text
> 帮我改个文件
在继续之前，我想先确认你的意图：

1. 需要修改哪个文件或提供完整路径？
2. 具体的修改内容或目标是什么？

请补充说明，我会据此继续处理。
> 修改根目录下的 test.txt 文件
明白，你需要修改工作区根目录下的 `test.txt` 文件。请告诉我具体要写入或追加什么内容。
> 文件内容增加:这是我的一个测试文本,目的是测试跨对话持续性
[chat] 思考中…
[chat] 连接模型 (auto(ollama→openrouter→aiping→cursor))…
[chat] 生成回复…
[chat] 调用 写入文件…
[chat] 综合工具结果 (第 2 轮)…
[chat] ✓ 综合工具结果 (第 2 轮)… (11.1s)
已成功将指定内容追加到 `test.txt` 文件中。当前文件内容为：

> 这是我的一个测试文本,目的是测试跨对话持续性
[via ollama/qwen3.5:4b]
```

适用场景：修改文件、重构代码、分析项目等**对象或范围不明确**的请求。可通过设 `LA_INTENT_CLARIFY=0` 关闭（默认开启）；含具体路径的请求会跳过预检，直接执行。

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

仓库提供 **产品体验教程**（八大优势 · 完整输入输出 · 约 30 分钟）与更短的 walkthrough：

| #   | 场景                   | 命令                                      |
| --- | -------------------- | --------------------------------------- |
| 1   | 单条记忆写入与召回            | `LA memory add` → `LA memory search`                  |
| 2   | Markdown 文件导入与召回     | `LA memory add-file` → `LA memory search --knowledge` |
| 3   | 联网搜索最近新闻             | `LA chat` 或 `/deepsearch`（默认无需 Key） |
| 4   | **纯本地运行** qwen3.5:4b | `LA chat --provider ollama`             |
| 5   | 回答本地工作内容             | `LA workspace` / `LA chat --cwd .`      |
| 6   | **主动追问澄清意图**         | `LA chat` → 「帮我改个文件」→ 补充说明 → 执行     |
| 7   | Agent 自动执行终端命令       | `LA chat` → 「统计当前项目代码行数」              |
| 8   | 审计报告（Ollama 零费用）     | `LA audit --since 7d`                   |

```bash
# 产品体验教程（推荐）：八大优势 · 完整输入输出
open examples/product-tour.zh-CN.md
# 更短的分步 walkthrough
open examples/walkthrough.md
```

### 亮点：Mem0 长期记忆 —— 全方位记住你

记忆输入支持 **ChatGPT 历史对话、个人文档、日常对话**；Warm 层接入强大的 [Mem0](https://github.com/mem0ai/mem0) 引擎（`mem0ai` 已含主依赖），提供 **Retain → Recall → Reflect（search + LLM）** 完整记忆链路。仓库提供一条「架构决策演变」叙事演示，覆盖写入、语义召回、时间感知、标签浏览与跨记忆推理：

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

示例文件：

- [examples/product-tour.zh-CN.md](examples/product-tour.zh-CN.md) — **产品体验教程**（八大优势 · 完整输入输出 · 约 30 分钟） · [English](examples/product-tour.md)
- [examples/walkthrough.md](examples/walkthrough.md) — **分步教程**（纯本地 qwen3.5:4b 优先）
- [examples/mem0-demo.md](examples/mem0-demo.md) — Mem0 记忆引擎深度演示（Retain / Recall / Reflect）
- [benchmarks/locomo/README.md](benchmarks/locomo/README.md) — **LoCoMo 长期记忆基准**（超长多 session 对话 QA）
- [examples/sample-project-notes.md](examples/sample-project-notes.md) — `add-file` 演示文档
- [examples/audit-report-sample.md](examples/audit-report-sample.md) — 审计报告样例（Ollama $0）
- [examples/env.local-only.example](examples/env.local-only.example) — 纯本地 `.env` 模板

### 基准：LoCoMo 长期会话记忆

用 ACL 2024 [LoCoMo](https://github.com/snap-research/locomo) 评测 Warm 层跨 session 记忆。  
**当前召回分数（2026-07-14，`conv-26`，Mem0 hybrid，n=150）**：Hit@1 **0.360** / Hit@5 **0.573** / Hit@8 **0.660**。

```bash
python -m benchmarks.locomo.run download
python -m benchmarks.locomo.measure_recall \
  --skip-ingest --sample-ids conv-26 \
  --work-dir benchmarks/data/runs/locomo-mem0
```

分 category 表与复现步骤见 [benchmarks/locomo/README.md](benchmarks/locomo/README.md)。

### Shell 自动补全

```bash
LA complete-init
source ~/.zshrc
```

之后 `LA memory` + Tab 会提示 `add` / `add-file` / `ingest` 等子命令。

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
| `LA_INTENT_CLARIFY`                     | 对话前主动追问澄清意图（默认 `1` 开启，设 `0` 关闭）              |
| `LA_DATA_DIR`                           | 自定义数据目录（测试隔离用）                                   |

## 命令

```bash
$ LA -h
```

```text
usage: LA [-h] <command> ...

LocalAgent — 本地 AI 个人助手

options:
  -h, --help       show this help message and exit

命令:
  主要参数与选项（括号内为可选）：

  <command>
    chat           [--session-id ID] [-p auto|ollama|…]  交互式对话
    memory         add|add-file|ingest|query|search|…  记忆写入/消费/查询/运维
    tasks          [--limit N] [--tail N] [list | <task_id> |
                   delete|pause|resume|restart|logs <task_id>] 查看/管理后台索引任务
    workspace      [--days N] [--cwd PATH] [--todos-only] 工作区/git/待办快照
    audit          [--since 7d] [--report PATH] [--cwd PATH] 审计摘要与报告
    config         init | list | add | remove | set-key 管理模型 YAML 配置

常用记忆子命令:
    LA memory add "<text>"
    LA memory add-file [-b] <path>
    LA memory ingest chat|file|chatgpt|all [--force]
    LA memory search <query> [--knowledge]
    LA memory query [query] [--tag TAG] [--since DATE]
    LA memory reflect <query>
    LA memory forget <id> [--yes]
    LA memory reset [chat|file|chatgpt|all]
    LA memory status | reindex | rebuild

使用 LA <command> -h 查看某个命令的完整说明。
```

进入 `LA` / `LA chat` 后，可用 `/` 前缀执行与外层相同的全部命令（Claude Code 风格；`:` 为兼容别名）。例如：`/help`、`/memory add "…"`、`/memory query`、`/provider ollama`、`/model qwen3.5:4b`、`/deepsearch <主题>`、`/q`。外层 `LA <command>` 与会话内 `/<command>` 等价（会话内禁止再开 `/chat`）。

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
└── audit/usage.jsonl          # 调用审计日志
```

## 架构

叙事主线：**完全本地** → **主动追问** → **长期多层次记忆（Mem0）** → **多源输入** → **本机 · 画像 · 联网三层打通**。

```
┌─────────────────────────────────────────┐
│              LA chat (REPL)             │
│     Ollama / OpenRouter / Cursor        │
│         （意图澄清 → 再动手）              │
└─────────────────┬───────────────────────┘
                  │ LangGraph Agent
    ┌─────────────┼─────────────┬──────────────┐
    ▼             ▼             ▼              ▼
  Hot          Warm           Cold         联网 / Shell
core_profile  Mem0     Chroma+BM25   web_search / run_shell
（用户画像）   （长期记忆）    （个人文档）    （互联网 · 本机）
```

- **Hot**：`core_profile.json`（Pinned 核心事实 / 用户画像）
- **Warm**：Mem0 记忆引擎（长期记忆；ChatGPT / 对话提取入库）
- **Cold**：Chroma + BM25（个人文档原文）
- **Agent**：LangGraph 工具循环；按需 JIT 召回记忆，并可联网、执行本地 Shell

详见 [docs/PRD.md](docs/PRD.md) 和 [docs/TDD.md](docs/TDD.md)。

## 开发

发版时同步三处（缺一不可）：

1. 改 `src/localagent/__init__.py` 里的 `__version__`（唯一版本源）
2. 打并推送同号 tag：`git tag v0.2.0 && git push origin v0.2.0`
3. 更新 README 中的 `@v…` / 当前版本说明

```bash
# 单元 + 集成测试（隔离临时目录，不依赖 Ollama）
pytest

# 端到端：subprocess 调用 LA 命令
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
