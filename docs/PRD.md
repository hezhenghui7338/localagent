# LocalAgent 需求文档（PRD v1）

**产品名**：LocalAgent（CLI 入口：`LA`）  
**定位**：本地、持久化的 AI 个人助手。数据留在本机，记忆与知识可积累、可更新，用户掌控写入。

## 0. 核心定位（用户真正关心的事）

LocalAgent 不是「又一个 Chat 客户端」，而是**跨模型、跨会话、跨来源**的个人 AI 中枢。无论用户连的是本地 Ollama 还是线上 OpenRouter / Cursor 等模型，**身份、记忆、工作上下文与审计数据都留在本机**，由 LocalAgent 统一编排。

| # | 用户关切 | 产品承诺 | 现状 / 方向 |
|---|----------|----------|-------------|
| 1 | **能不能和我的模型服务对话** | 统一入口 `LA chat`，支持本地 Ollama 与多种线上模型；REPL 内可切换 provider，auto 模式按优先级降级 | ✅ Ollama / OpenRouter / Cursor；`:provider` 切换 |
| 2 | **Agent 能不能记住我** | 记忆模块与具体模型解耦：Hot / Warm / Cold 分层，对话结束提取候选 → pending 确认；支持 ChatGPT 历史冷启动 | ✅ 记忆栈 + import-chatgpt；持续优化召回与 JIT |
| 3 | **我需要联网** | 对话中按需触发联网搜索（Tavily 等），`:deepsearch` 深度研究；结果进入当轮上下文，不未经确认写入长期记忆 | ✅ Tavily 集成 |
| 4 | **我需要操作本地文件与工作上下文** | 读写工作目录、感知文件变更、Git 历史、待办任务；回答「我最近干了啥、目录里变了什么、有什么 todo」 | ✅ workspace 命令 + Agent `workspace_context` 工具 |
| 5 | **我需要审计与报告** | 汇总各模型/API 花费、token 消耗、敏感文件与权限风险，可出具可读报告（CLI 导出或 HTML/Markdown） | ✅ `LA audit` + 自动 usage 日志 |

**一句话**：LocalAgent = **多模型对话入口** + **本地持久记忆** + **联网能力** + **工作区感知** + **可审计的个人 AI 运营面板**。

---

## 1. 产品目标

在上述核心定位下，具体目标包括：

1. **多模型对话**：本地 Ollama 与线上模型服务统一接入，切换模型不丢失「我是谁」
2. **持久记忆**：导入个人文件与历史对话后，在未来任意模型对话中被自然调用；助手记住「我是谁、我说过什么」，但不喧宾夺主
3. **联网补全**：实时信息从网上来，与本地记忆/文件互补
4. **工作区感知**：操作与理解用户工作目录——最近活动、文件 diff、Git 记录、待办任务
5. **可审计**：服务花费、token 消耗、文件安全性可追踪、可报告
6. **用户掌控写入**：记忆与知识的关键变更须经用户确认（pending 确认门）
7. **ChatGPT 冷启动**：直接导入 ChatGPT 历史对话，作为记忆的主要来源之一
8. **主动意图澄清**：收到用户问题时先分析意图；意图不清晰时主动追问，澄清后再执行原任务

### 1.1 能力详述（对应核心定位）

#### 1.1.1 多模型对话

- 支持 **Ollama**（本地）、**OpenRouter**、**Cursor** 等；通过 `.env` 与 `LA_MODEL_PROVIDER_PRIORITY` 配置优先级
- `LA chat` / `:provider` 在 `auto | ollama | openrouter | cursor` 间切换
- 模型不可用时按优先级自动降级，并在 REPL 中提示当前实际路径
- **原则**：模型是「算力供应商」，LocalAgent 是「会话与记忆 owner」

#### 1.1.2 记忆模块

- **Hot**：`core_profile.json` —  pinned 核心事实（姓名、偏好、长期目标等）
- **Warm**：结构化长期记忆（Hindsight / JSON memory）— 从对话与导入中提取
- **Cold**：Chroma + BM25 — 个人文档原文（`data/kb/`）
- 对话退出时自动提取候选 → `pending` → `approve/reject`；ChatGPT 批量导入走同一确认门
- **原则**：换模型不换身份；记忆写入可审计、可撤销（reset / rebuild）

#### 1.1.3 联网

- Tavily（或同类）作为默认搜索后端；Agent 在需要实时信息时自动调用
- `:deepsearch <主题>` 多步检索与归纳
- 联网结果默认**不**自动入库；若含可沉淀事实，仍走 pending 确认

#### 1.1.4 本地文件与工作上下文（重点演进）

用户期望 Agent 能回答并协助：

| 场景 | 期望行为 |
|------|----------|
| 我最近干了啥 | 汇总近期改动的文件、Git commit、对话中提取的任务 |
| 文件出现了怎样的变化 | 工作目录 diff / 最近修改列表 / 与上次 sync 对比 |
| Git 记录是怎样的 | `git log`、`git status`、分支与未提交变更的自然语言摘要 |
| 有什么待办 | 聚合 TODO 注释、markdown checkbox、对话 pending、外部任务源（后续） |

**规划能力**（待实现）：

- 工作区根目录配置（如 `LA_WORKSPACE` 或 `LA chat --cwd`）
- 文件变更索引（mtime + 可选 git diff 快照）
- Git 摘要工具（只读，不替代 git CLI）
- Todo 扫描（`TODO:`、`FIXME:`、`- [ ]` 等）与对话任务关联
- 与现有 `add-file` / `sync-file` 知识库索引协同，避免重复造轮子

#### 1.1.5 审计与报告（重点演进）

用户需要**可出具的报告**，而非只在日志里散落数据：

| 审计维度 | 采集内容 | 报告呈现 |
|----------|----------|----------|
| **服务花费** | 各 provider 调用次数、估算费用（按公开价目或用户自定义单价） | 按日/周/月汇总，分 provider 饼图或表格 |
| **Token 消耗** | 输入/输出 token（含 Ollama 本地估算、线上 API 回传） | 按会话、按模型、按命令类型 breakdown |
| **文件安全** | kb 与工作区路径权限、敏感模式（密钥、`.env` 误索引）、软链目标 | 风险项列表 + 建议 remediation |
| **记忆健康** | pending 积压、重复记忆、索引失败文件 | 运维向摘要 |

**规划命令**（待实现）：

```bash
LA audit              # 交互式摘要
LA audit --report out.md   # 导出 Markdown/HTML 报告
LA audit --since 7d        # 时间范围
```

**原则**：审计数据存本地（如 `data/audit/`），不上传；报告默认只含聚合统计，不含完整对话正文（除非用户显式包含）。

#### 1.1.6 主动意图澄清（关键 Agent 特质）

用户抛出问题时，Agent **不应盲目开工**，而应先判断「用户到底想做什么」。这是 LocalAgent 区别于普通 Chat 客户端的核心行为之一。

**触发条件**（意图不清晰）：

| 信号 | 示例 |
|------|------|
| 指代不明 | 「帮我改一下」「把它优化掉」——未说明改什么 |
| 范围缺失 | 「分析一下」「写个报告」——未说明对象、时间范围或输出格式 |
| 多义解读 | 「看看项目」——浏览结构？查 Git？跑测试？ |
| 目标冲突 | 同时隐含多种互斥操作，无法安全默认 |

**期望行为**：

1. **分析**：每轮用户输入进入 Agent 主流程前，轻量评估意图是否足够明确（结合近期对话上下文）
2. **追问**：不明确时，用 1–2 个具体问题向用户澄清（不调用工具、不执行副作用操作）
3. **等待**：将原始问题暂存，进入「待澄清」状态
4. **合并**：用户补充后，将原始问题与澄清内容合并，再进入正常的工具调用与回答流程
5. **放行**：意图已足够明确的问题（含具体路径、明确命令、简单寒暄）直接处理，避免过度打断

**配置**：

- `LA_INTENT_CLARIFY=1`（默认开启）；设为 `0` 可关闭预检，仅依赖 system prompt 兜底

**原则**：

- 澄清优先于行动：宁可多问一句，也不基于错误假设改文件、跑命令或写入记忆
- 追问要短、要具体：一次最多 2 个问题，避免问卷式轰炸
- 澄清轮次计入对话历史，便于后续轮次继承上下文

## 2. 极简 CLI

| 命令 | 作用 |
|------|------|
| `LA chat` | 对话 REPL；记忆/知识 JIT；联网自动触发 |
| `LA add "..."` | 直接加记忆（即时生效） |
| `LA add-file <path>` | 软链 + 立即索引单文件（显示进度） |
| `LA add-file -b <path>` | 软链后后台索引 |
| `LA tasks [id]` | 查看索引任务状态 |
| `LA sync-file` | 索引 `data/kb/` 全部文档（增量） |
| `LA sync-file --force` | 强制全量重索引 |
| `LA reset-memory` | 清空记忆 + sync_index |
| `LA rebuild-memory` | reset + sync-file --force |
| `LA pending/approve/reject` | 对话提取确认门 |
| `LA rememorize-chat` | 从 LocalAgent 对话 jsonl 再提取记忆 |
| `LA import-chatgpt <path>` | 导入 ChatGPT 导出 JSON，提取记忆候选 |
| `LA import-chatgpt --dir data/chatGPTdata/` | 批量导入目录下全部导出文件 |
| `LA search <query>` | 调试记忆/知识检索 |
| `LA workspace` | 工作区快照：最近文件、Git、待办 |
| `LA audit` | Token/费用/安全/记忆健康审计；`--report out.md` |

## 3. 多源输入

| 来源 | 入口 | 写入路径 | 记忆流程 |
|------|------|----------|----------|
| 个人文件 | `add-file` / `sync-file` | `data/kb/` | 直接索引，不走 pending |
| LocalAgent 对话 | `LA chat` 退出 | `data/conversations/*.jsonl` | 提取候选 → pending → approve |
| **ChatGPT 导出** | `import-chatgpt` | `data/chatGPTdata/`（原始归档） | 解析 → 提取候选 → pending → approve |

### 3.1 ChatGPT 对话导入（重要）

用户从 ChatGPT **Settings → Data Controls → Export** 获得 `conversations.json`（可拆分为多个文件，如 `conversations-002.json`），放入 `data/chatGPTdata/` 作为记忆输入。

**样例文件**：`data/chatGPTdata/conversations-002.json`（100 条对话，供开发与验收参考）

**格式要点**（OpenAI 官方导出结构）：

- 顶层为 **对话数组**，每条含 `title`、`create_time`、`update_time`、`conversation_id`
- 消息存于 **`mapping`** 树：`current_node` 指向最新节点，沿 `parent` 回溯得时间序
- 每条消息：`message.author.role`（`user` / `assistant`）、`message.content.parts[]`（文本）
- **`is_do_not_remember: true`** 的对话须跳过，不提取记忆
- assistant 回复中的联网引用（`content_references`、cite 标记等）解析时剥离，只保留可读正文

**导入行为**：

1. 解析 JSON，按对话重建 user/assistant 轮次（含 `title`、时间戳作上下文）
2. 优先从 **user 消息** 提取个人事实、偏好、计划；assistant 内容仅作语境，不整段入库
3. 每条对话产出一批记忆候选 → **pending 确认门**（与 `chat` 退出提取一致）
4. 原始 JSON **只读归档**，不修改；已处理对话记录 `conversation_id` 防重复导入
5. 可选 `--force` 对已有记录重新提取

**与 LocalAgent 对话的区别**：

- LocalAgent jsonl：实时增量、结构简单（`role` + `content`）
- ChatGPT JSON：历史批量、树形 mapping、需专用解析器；是**记忆冷启动**的核心路径

## 4. 验收标准

### 4.1 已实现

- `add-file` 软链存在 + 记忆/RAG 已写入 + sync_index 有记录
- `sync-file` 第二次执行跳过未变更文件
- `chat` 对话持久化到 `data/conversations/*.jsonl`
- LocalAgent 对话与 ChatGPT 导入的提取均走 approve 确认门
- `import-chatgpt data/chatGPTdata/conversations-002.json` 能解析 100 条对话并生成 pending 候选
- 跳过 `is_do_not_remember: true` 的对话；同一 `conversation_id` 重复导入不重复入队（除非 `--force`）
- `LA chat` 可在 Ollama / OpenRouter / Cursor 间切换或 auto 降级
- 联网搜索与 `:deepsearch` 可用（配置 `TAVILY_API_KEY` 后）

**主动意图澄清**

- 模糊请求（如「帮我改一下」）触发 1–2 条澄清追问，不调用工具
- 用户补充后，Agent 基于合并后的意图继续原任务
- 明确请求（含文件路径、具体命令）不触发多余追问
- `LA_INTENT_CLARIFY=0` 时跳过预检，行为与旧版一致

### 4.2 核心定位 — 待验收（工作区 + 审计）

**工作上下文**

- 配置工作区后，Agent 能列出「最近 N 天修改的文件」并自然语言摘要
- 能回答当前 Git 分支、未提交变更、最近 commit 摘要（只读）
- 能扫描并汇总工作区内 TODO / checkbox 待办

**审计与报告**

- 每次模型调用记录 provider、模型、估算 token 与费用到本地 audit 日志
- `LA audit --report` 生成含花费、token、安全扫描结果的 Markdown 报告
- 报告可指定时间范围；敏感文件误索引项可被列出并给出修复建议

> 以上能力已实现；持续增强项：工作区 watcher 增量索引、HTML 报告、外部任务源接入。
