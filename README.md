# LocalAgent

> **一台普通 Mac + Ollama `qwen3.5:4b`，零 API 费用，就能有不错的个人 AI 助手效果。**

LocalAgent（`LA`）不是又一个 Chat 客户端。它把**对话、个人记忆、文档检索、工作区感知**串成一套完整的本地 Agent 链路——核心亮点是：**用最基础的本地 Ollama 部署，4B 小模型也能「记得住你、找得到文档、看得见当前项目在做什么」**，而不只是聊完就忘。

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

可选接入 OpenRouter / Cursor / Tavily 做增强，但**身份与数据始终留在本机**。

## 特性

- **4B 即可用**：默认 `qwen3.5:4b`，对话、记忆写入、检索、工作区感知全链路本地跑通
- **分层记忆**：Hot（核心画像）/ Warm（长期记忆）/ Cold（文档原文）三层架构，按需 JIT 召回
- **文档知识库**：软链导入个人文件，Chroma + BM25 混合检索
- **工作区感知**：Git 状态、最近文件、待办任务快照
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
| 审计 `LA audit` | 否 | 读本地 usage.jsonl |
| 联网搜索 | 是（Tavily） | 唯一需要 API Key 的可选功能 |


```bash
# 纯本地模式：普通 Mac + Ollama，无需付费 API
cp examples/env.local-only.example .env
ollama pull qwen3.5:4b
LA chat --provider ollama
```

仓库提供完整 walkthrough，覆盖 6 个核心场景：


| #   | 场景                   | 命令                                      |
| --- | -------------------- | --------------------------------------- |
| 1   | 单条记忆写入与召回            | `LA add` → `LA search`                  |
| 2   | Markdown 文件导入与召回     | `LA add-file` → `LA search --knowledge` |
| 3   | 联网搜索最近新闻             | `LA chat` 或 `:deepsearch`（需 Tavily）     |
| 4   | **纯本地运行** qwen3.5:4b | `LA chat --provider ollama`             |
| 5   | 回答本地工作内容             | `LA workspace` / `LA chat --cwd .`      |
| 6   | 审计报告（Ollama 零费用）     | `LA audit --since 7d`                   |


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

- [examples/walkthrough.md](examples/walkthrough.md) — **6 场景分步教程**（纯本地 qwen3.5:4b 优先）
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

详见 `[.env.example](.env.example)`，常用变量：


| 变量                                      | 说明                                               |
| --------------------------------------- | ------------------------------------------------ |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL`      | 本地 Ollama 地址与模型                                  |
| `MINIMAX_API_KEY` / `MINIMAX_MODEL`     | MiniMax 直连（OpenAI 兼容 API）                        |
| `OPENROUTER_API_KEY` / `CURSOR_API_KEY` | 其他云端模型降级                                         |
| `TAVILY_API_KEY`                        | 联网搜索                                             |
| `LA_MODEL_PROVIDER_PRIORITY`            | auto 模式优先级，默认 `ollama,minimax,openrouter,cursor` |
| `LA_WORKSPACE`                          | 工作区根目录（Git / 文件 / 待办上下文）                         |
| `LA_DATA_DIR`                           | 自定义数据目录（测试隔离用）                                   |


## 命令

### 对话

```bash
LA chat                          # 默认 auto
LA chat --provider ollama        # 指定模型路径
LA chat --cwd ~/code/myproject   # 指定工作区
```

REPL 内命令：


| 命令                 | 说明                                                         |
| ------------------ | ---------------------------------------------------------- |
| `:provider`        | 查看 / 切换模型路径（auto | ollama | minimax | openrouter | cursor） |
| `:deepsearch <主题>` | 深度研究                                                       |
| `:q`               | 退出                                                         |


### 工作区与审计

```bash
LA workspace                     # 最近文件 + Git + 待办快照
LA workspace --todos-only
LA audit                         # 交互式审计摘要
LA audit --since 7d --report audit.md
```

### 记忆

```bash
LA add "决定采用分层记忆架构"
LA search "记忆架构"             # 结果含记忆 id
LA reflect "架构决策的演变？"     # Hindsight 跨记忆推理
LA forget <id>
LA rememorize-chat --session s-xxx
```

### ChatGPT 导出导入

从 ChatGPT **Settings → Data Controls → Export** 下载 ZIP，解压后将 JSON 放入 `data/chatGPTdata/`。


| 文件                              | 含义                  |
| ------------------------------- | ------------------- |
| `conversations.json`            | 全部对话历史 → LLM 提取个人事实 |
| `memory.json` / `memories.json` | ChatGPT「记忆」→ 直接写入   |


```bash
LA import-chatgpt ~/Downloads/conversations.json
LA import-chatgpt --dir data/chatGPTdata/   # 批量导入
LA import-chatgpt --force --interactive     # 重新导入 / 逐条确认
```

### 文件导入与检索

```bash
LA add-file ~/Documents/notes.md    # 软链 + 索引
LA add-file notes.md -b             # 后台索引
LA sync-file                        # 扫描 kb/ 增量同步
LA search "某文档内容" --knowledge
LA tasks                            # 查看索引任务
```

### 记忆维护

```bash
LA reset-memory      # 清空记忆（保留知识库）
LA rebuild-memory    # 从知识库重建记忆索引
LA memory-status     # 诊断记忆后端（Hindsight / JSON）
```

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