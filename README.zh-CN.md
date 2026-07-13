<p align="center">
  <img src="docs/logo.png" alt="LocalAgent" width="360">
</p>

<p align="center">
  <strong>Your AI. Your Data. Your Mac.</strong>
</p>

<p align="center">
  <a href="./README.md">English</a> · <a href="./README.zh-CN.md">中文</a>
</p>

# LocalAgent

> **一台普通 Mac + Ollama `qwen3.5:4b`，零 API 费用，就能有不错的个人 AI 助手效果。**

LocalAgent（`LA`）不是又一个 Chat 客户端。它把**对话、个人记忆、文档检索、工作区感知**串成一套完整的本地 Agent 链路——核心亮点是：**用最基础的本地 Ollama 部署，4B 小模型也能「记得住你、找得到文档、看得见当前项目在做什么」**；更重要的是，它会**在动手前先追问、确认你的真实意图**，而不是像普通 Chat 那样猜错就改、改错就毁。

```bash
ollama pull qwen3.5:4b          # 约 2.5GB，普通 Mac 可跑
pip install -e ".[full]"
cp examples/env.local-only.example .env
LA chat --provider ollama       # 纯本地，数据不出本机
```

| 普通本地 Chat | LocalAgent + qwen3.5:4b |
| --- | --- |
| 聊完就忘 | 分层记忆，跨会话召回你的事实与偏好 |
| 不知道你在做什么 | Git 状态、最近文件、待办快照 |
| 搜不到本地笔记 | Chroma + BM25 混合检索个人文档 |
| 只会一问一答 | LangGraph Agent 按需 JIT 召回上下文 |
| 指代不明也硬猜、直接改文件 | **主动追问澄清意图**，确认后再调用工具 |
| 让你自己去终端跑命令 | Agent 自动调用 `run_shell` 执行并汇总结果 |

可选接入 OpenRouter / Cursor / Tavily 做增强，但**身份与数据始终留在本机**。

## 特性

- **4B 即可用**：默认 `qwen3.5:4b`，对话、记忆写入、检索、工作区感知全链路本地跑通
- **主动澄清意图**：模糊请求先追问 1–2 个关键问题，确认后再执行；文件写入另有幻觉检测兜底，未实际调用工具不会声称「已完成」
- **分层记忆**：Hot（核心画像）/ Warm（长期记忆）/ Cold（文档原文）三层架构，按需 JIT 召回
- **文档知识库**：软链导入个人文件，Chroma + BM25 混合检索
- **工作区感知**：Git 状态、最近文件、待办任务快照
- **终端执行**：Agent 在工作区自动运行 shell 命令（统计代码、列目录、跑测试等）
- **多模型对话**：Ollama / OpenRouter / Cursor 统一入口，`auto` 模式按优先级自动降级
- **ChatGPT 冷启动**：导入历史对话与 ChatGPT「记忆」功能导出，快速建立个人记忆
- **联网搜索**：Tavily 集成，支持 `:deepsearch` 深度研究（可选）
- **可审计**：Token 消耗、费用估算、敏感文件扫描，可导出 Markdown 报告

## 要求

- Python 3.10+（Hindsight 记忆引擎需 3.11+）
- [Ollama](https://ollama.com/) + `qwen3.5:4b`（推荐，也是项目默认配置）

## 快速开始

```bash
git clone git@github.com:hezhenghui7338/localagent.git
cd LocalAgent
python3 -m venv .venv && source .venv/bin/activate

# 基础安装（BM25 + 核心 CLI）
pip install -e ".[dev]"

# 完整安装（LangGraph + Chroma 向量检索）
pip install -e ".[full,dev]"

# 可选：Hindsight 记忆引擎（Python 3.11+）
pip install -e ".[hindsight]"
```

复制环境变量模板并填入你的 API Key：

```bash
cp .env.example .env
# 编辑 .env，至少配置一个模型服务；可选配置 Ollama/OpenRouter / Cursor / Tavily（联网搜索）
```

首次运行会自动在 `data/` 下创建运行时目录。可将 `data/core_profile.example.json` 复制为 `data/core_profile.json` 作为核心画像模板。

## 功能示例

### 亮点：纯本地 qwen3.5:4b 即可用

LocalAgent 的核心链路——**对话、记忆写入、记忆召回、文档检索、工作区感知、审计统计**——均可只依赖本地 Ollama，无需任何付费 API。

| 能力 | 是否需要联网 API | 说明 |
| --- | --- | --- |
| 对话 `LA chat` | 否 | 默认 `qwen3.5:4b`，普通 Mac 可跑 |
| 单条记忆 `LA add` | 否 | 本地模型提取标题/标签 |
| 文件导入 `LA add-file` | 否 | 默认启发式提取，不调用 LLM |
| 记忆/知识检索 `LA search` | 否 | BM25 + Chroma 本地检索 |
| 工作区 `LA workspace` | 否 | 读本地 Git / 文件 / TODO |
| Agent 执行命令 `run_shell` | 否 | 本地 4B 模型自动调用 shell 并汇总输出 |
| 审计 `LA audit` | 否 | 读本地 usage.jsonl |
| 联网搜索 | 是（Tavily） | 唯一需要 API Key 的可选功能 |

```bash
# 纯本地模式：普通 Mac + Ollama，无需付费 API
cp examples/env.local-only.example .env
ollama pull qwen3.5:4b
LA chat --provider ollama
```

### 亮点：主动追问、确认意图后再动手

普通 Chat 收到「帮我改个文件」往往会猜一个路径直接覆盖；LocalAgent 会先做一次**轻量意图预检**（本地 `qwen3.5:4b`，默认开启），指代不明时**主动追问 1–2 个具体问题**，等你补充后再合并上下文、调用工具执行。文件写入还有**幻觉检测**：若模型声称「已写入」却未调用 `write_file`，会自动重试或明确报错，而不是展示编造的空内容。

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

### 亮点：Agent 自动执行终端命令

普通 Chat 只会告诉你「去终端运行 `find … | wc -l`」。LocalAgent 的 Agent 会**自己调用 `run_shell` 工具**，在工作区执行命令并把结果整理成回答——全程纯本地 `qwen3.5:4b`，无需云端 API。

```text
> 统计一下当前项目的代码行数
[chat] 思考中…
[chat] 连接模型 (auto(ollama→openrouter→aiping→cursor))…
[chat] 生成回复…
[chat] 调用 执行命令: find . -type f \( -name "*.py" -o -name …
[chat] 综合工具结果 (第 2 轮)…
[chat] ✓ 综合工具结果 (第 2 轮)… (20.4s)
当前项目（`/Users/hzh/code/LocalAgent`）中主要编程语言文件（Python、JS、TS、Go、Java、C/C++、Rust等，排除隐藏目录）的总代码行数为 **13,961 行**。
[via ollama/qwen3.5:4b]
```

适用场景：统计代码行数、列目录、查看 Git 日志、运行测试/构建等。命令在工作区目录执行（`LA_WORKSPACE` 或当前目录），默认超时 30 秒。

仓库提供完整 walkthrough，覆盖核心场景：

| #   | 场景                   | 命令                                      |
| --- | -------------------- | --------------------------------------- |
| 1   | 单条记忆写入与召回            | `LA add` → `LA search`                  |
| 2   | Markdown 文件导入与召回     | `LA add-file` → `LA search --knowledge` |
| 3   | 联网搜索最近新闻             | `LA chat` 或 `:deepsearch`（需 Tavily）     |
| 4   | **纯本地运行** qwen3.5:4b | `LA chat --provider ollama`             |
| 5   | 回答本地工作内容             | `LA workspace` / `LA chat --cwd .`      |
| 6   | **主动追问澄清意图**         | `LA chat` → 「帮我改个文件」→ 补充说明 → 执行     |
| 7   | Agent 自动执行终端命令       | `LA chat` → 「统计当前项目代码行数」              |
| 8   | 审计报告（Ollama 零费用）     | `LA audit --since 7d`                   |

```bash
# 按示例文档逐步体验
open examples/walkthrough.md
```

### 进阶：Hindsight 记忆引擎演示

LocalAgent 的 Warm 层可选 [Hindsight](https://github.com/hindsight/hindsight) 引擎，提供 **Retain → 4 路 Recall → Reflect → Consolidation** 完整记忆链路。仓库提供一条「架构决策演变」叙事演示，覆盖写入、语义召回、时间感知、标签浏览与跨记忆推理：

```bash
# 安装 Hindsight（Python 3.11+）
pip install -e ".[full,hindsight]"

# 一键演示（隔离 /tmp，不污染 data/）
bash examples/hindsight-demo.sh

# 或阅读分步教程
open examples/hindsight-demo.md
```

演示要点：

| 步骤 | 命令 | 展示能力 |
|------|------|----------|
| 写入演变链 | `LA add` × 4 | Retain + 自动标题/标签/发生时间 |
| 语义召回 | `LA search "记忆引擎选型"` | Hindsight 多路并行 recall |
| 时间感知 | `LA search "2026年5月 决定"` | 按发生时间重排序 |
| 标签浏览 | `LA memories --tag 决策` | 结构化查询 |
| 跨记忆推理 | `LA reflect "选型经历了什么变化？"` | Hindsight reflect |

示例文件：

- [examples/walkthrough.md](examples/walkthrough.md) — **分步教程**（纯本地 qwen3.5:4b 优先）
- [examples/hindsight-demo.md](examples/hindsight-demo.md) — Hindsight 记忆引擎深度演示（Retain / Recall / Reflect）
- [examples/sample-project-notes.md](examples/sample-project-notes.md) — `add-file` 演示文档
- [examples/audit-report-sample.md](examples/audit-report-sample.md) — 审计报告样例（Ollama $0）
- [examples/env.local-only.example](examples/env.local-only.example) — 纯本地 `.env` 模板

### Shell 自动补全

```bash
LA complete-init
source ~/.zshrc
```

之后 `LA add` + Tab 会提示 `add` / `add-file` 等子命令。

### Ollama 提示

- 默认模型 `qwen3.5:4b`；若未安装，LA 会尝试匹配已安装的同名 tag
- Qwen3 系列默认生成大量 thinking token，LocalAgent 默认 `OLLAMA_THINK=0` 关闭思考模式
- 本地 Ollama 较慢时，`auto` 模式会在 12 秒内降级到 OpenRouter；也可在 chat 中输入 `:provider openrouter` 手动切换

## 配置

详见 [`.env.example`](.env.example)，常用变量：

| 变量                                      | 说明                                               |
| --------------------------------------- | ------------------------------------------------ |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL`      | 本地 Ollama 地址与模型                                  |
| `MINIMAX_API_KEY` / `MINIMAX_MODEL`     | MiniMax 直连（OpenAI 兼容 API）                        |
| `OPENROUTER_API_KEY` / `CURSOR_API_KEY` | 其他云端模型降级                                         |
| `TAVILY_API_KEY`                        | 联网搜索                                             |
| `LA_MODEL_PROVIDER_PRIORITY`            | auto 模式优先级，默认 `ollama,minimax,openrouter,cursor` |
| `LA_WORKSPACE`                          | 工作区根目录（Git / 文件 / 待办 / shell 命令上下文）              |
| `LA_SHELL_TIMEOUT` / `LA_SHELL_MAX_OUTPUT` | Agent `run_shell` 超时秒数与输出截断上限（默认 30s / 12000 字符） |
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
    chat           [--session-id ID] [-p auto|ollama|openrouter|aiping|cursor]
                   交互式对话
    add            <text> 直接写入一条记忆
    add-file       [-b] <path> 软链到 kb/ 并索引
    tasks          [--limit N] [--tail N] [list | <task_id> |
                   delete|pause|resume|restart|logs <task_id>] 查看/管理后台索引任务
    sync-file      [--force] 扫描并索引 data/kb/ 下全部文档
    reset-memory   [--keep-knowledge] 清空记忆与 sync_index
    memory-status  诊断 Warm 层记忆后端（Hindsight / JSON）
    rebuild-memory
                   清空记忆后强制重建 kb/ 索引
    forget         <id> [--yes] 删除一条记忆
    rememorize-chat
                   [--session ID] [--interactive] 从对话档案重新提取记忆
    import-chatgpt
                   [path] [--dir DIR] [--force] [--interactive] 导入 ChatGPT 导出
    search         <query> [--knowledge] [--top-k N] [--verbose] 搜索记忆或知识库
    reflect        <query> 跨记忆推理（Hindsight reflect）
    memories       [query] [--tag TAG] [--since DATE] [--sort
                   newest|oldest|relevance] 浏览/查询记忆
    workspace      [--days N] [--cwd PATH] [--todos-only] 工作区/git/待办快照
    audit          [--since 7d] [--report PATH] [--cwd PATH] 审计摘要与报告
    config         init | list | add | remove | set-key 管理模型 YAML 配置

使用 LA <command> -h 查看某个命令的完整说明。
```

`LA chat` 进入 REPL 后，还可使用 `:provider`（切换模型）、`:deepsearch <主题>`（深度研究）、`:q`（退出）。

## 数据目录

运行时数据默认位于 `data/`（已在 `.gitignore` 中排除，不会提交到 Git）：

```
data/
├── kb/                        # 软链接的个人文件
├── core_profile.json          # Hot 层核心事实
├── sync_index.json            # 已索引文件登记
├── conversations/             # 对话档案
├── chatGPTdata/               # ChatGPT 导出归档
├── chatgpt_import_index.json  # 导入去重登记
├── sessions.db                # LangGraph 会话
├── chroma/                    # 向量索引
├── bm25.pkl                   # BM25 索引
└── audit/usage.jsonl          # 调用审计日志
```

## 架构

```
┌─────────────────────────────────────────┐
│              LA chat (REPL)             │
│     Ollama / OpenRouter / Cursor        │
└─────────────────┬───────────────────────┘
                  │ LangGraph Agent
    ┌─────────────┼─────────────┐
    ▼             ▼             ▼
  Hot          Warm           Cold
core_profile  Hindsight/    Chroma + BM25
              JSON memory   (文档原文)
                  │
                  ▼
            run_shell（工作区终端）
```

- **Hot**：`core_profile.json`（Pinned 核心事实）
- **Warm**：Hindsight / JSON memory（长期记忆）
- **Cold**：Chroma + BM25 混合检索（文档原文）
- **Agent**：LangGraph 工具循环，按需 JIT 召回

详见 [docs/PRD.md](docs/PRD.md) 和 [docs/TDD.md](docs/TDD.md)。

## 开发

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
- 若曾在其他环境泄露过 API Key，请立即在对应平台轮换密钥

## License

MIT
