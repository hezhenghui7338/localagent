# LocalAgent 需求文档（PRD v1）

**产品名**：LocalAgent（CLI 入口：`LA`）  
**定位**：完全本地的个人 AI 助手——用长期多层次记忆懂你，并能打通本机、用户画像与互联网。

## 0. 核心定位（用户真正关心的事）

LocalAgent 不是「又一个 Chat 客户端」，而是跑在本机上的**个人 AI 中枢**。叙事主线按五件事展开：

| # | 用户关切 | 产品承诺 | 现状 / 方向 |
|---|----------|----------|-------------|
| 1 | **是不是完全本地** | 默认本地 Ollama；对话、记忆写入/召回、文档检索、工作区感知均可离线跑通；可选接入线上模型，但**身份、记忆、审计数据始终留在本机** | ✅ 纯本地路径 + Ollama / OpenRouter / Cursor 统一入口 |
| 2 | **能不能可靠地动手改文件 / 跑命令** | 用户输入直接进入 Agent；`run_shell` / `write_file` 执行前确认；写文件另有幻觉检测兜底 | ✅ 工具确认门 + 幻觉检测重试 |
| 3 | **能不能长期、多层次地记住我** | Hot（核心画像）/ Warm（长期记忆）/ Cold（文档原文）分层；配合强大的 **Mem0** 记忆引擎，跨会话 JIT 召回「懂你」的上下文 | ✅ 分层记忆栈 + Mem0；持续优化召回 |
| 4 | **记忆从哪来、能不能全方位认识我** | 记忆引擎输入支持 **ChatGPT 历史对话**与 **LocalAgent 对话**；文档走独立 RAG。对话提取 → Mem0 长期记忆 | ✅ `memory ingest chatgpt` / `memory ingest chat`；文档用 `rag add` |
| 5 | **能不能真正可用（本机 · 画像 · 联网）** | **联网查询**（Tavily / `/deepsearch`）+ **本地 Shell**（`run_shell`）+ 工作区感知，把电脑本机、用户画像、互联网三层打通 | ✅ workspace / `run_shell` / Tavily；✅ `LA audit` 可审计 |

**一句话**：LocalAgent = **完全本地** + **长期多层次记忆（Mem0）** + **对话记忆 + 文档 RAG** + **本机 · 画像 · 联网三层打通**。

---

## 1. 产品目标

在上述核心定位下，具体目标包括：

1. **完全本地化**：默认本地 Ollama 跑通核心链路；数据与身份不出本机；可选云端模型不改变 owner 边界
2. **可靠执行**：用户输入直接进入 Agent；副作用工具执行前确认；写文件幻觉检测
3. **长期多层次记忆**：Hot / Warm / Cold + Mem0；助手记住「我是谁、我说过什么」，跨模型不丢身份，但不喧宾夺主
4. **对话记忆冷启动**：ChatGPT 历史导出与 LA 日常对话作为 Warm 记忆主输入；个人文档仅进 Cold RAG
5. **本机 · 画像 · 联网三层打通**：工作区感知与本地 Shell、记忆召回、联网搜索协同，形成真正可用的个人 Agent
6. **多模型对话**：本地 Ollama 与线上模型服务统一接入，切换模型不丢失「我是谁」
7. **可审计**：服务花费、token 消耗、文件安全性可追踪、可报告
8. **用户掌控写入**：记忆与知识的关键变更须经用户确认（pending 确认门）

### 1.1 能力详述（对应核心定位）

#### 1.1.1 多模型对话

- 支持 **Ollama**（本地）、**OpenRouter**、**Cursor** 等；通过 `.env` 与 `LA_MODEL_PROVIDER_PRIORITY` 配置优先级
- `LA chat` / `/provider` 在 `auto | ollama | openrouter | cursor` 间切换
- `/model` 为当前路径选择模型并写入 `config/model_servers.yaml`，下次默认使用
- 模型不可用时按优先级自动降级，并在 REPL 中提示当前实际路径
- **原则**：模型是「算力供应商」，LocalAgent 是「会话与记忆 owner」

#### 1.1.2 记忆模块（长期、多层次、懂你）

- **Hot**：`core_profile.json` — pinned 核心事实（姓名、偏好、长期目标等）/ 用户画像
- **Warm**：结构化长期记忆，优先接入强大的 **Mem0** 引擎（Retain → 多路 Recall → Reflect → Consolidation）；亦可回退 JSON memory
- **Cold**：Chroma + BM25 — 个人文档原文（`data/kb/`）
- **Warm 输入**：ChatGPT 历史对话导出、LocalAgent 日常对话 → 记忆提取入库
- **Cold 输入**：个人文档 → `LA rag` 知识库（不提取记忆）
- 对话退出时自动提取候选 → `pending` → `approve/reject`；ChatGPT 批量导入走同一确认门
- **原则**：换模型不换身份；全方位记住用户；记忆写入可审计、可撤销（reset / rebuild）

#### 1.1.3 联网

- Tavily（或同类）作为默认搜索后端；Agent 在需要实时信息时自动调用
- `/deepsearch <主题>` 多步检索与归纳
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
- 与现有 `rag add` / `rag ingest` 知识库索引协同，避免重复造轮子

#### 1.1.5 审计与报告（监察官）

Audit 是本地**监察官**：执行前护栏拦截危害动作，append-only 事件流留证，`LA audit` 出具报告。三层分离——**护栏（拦）≠ 轨迹（记）≠ 报告（算）**。

| 审计维度 | 采集内容 | 报告呈现 |
|----------|----------|----------|
| **服务花费** | 各 provider 调用次数、估算费用（`usage.jsonl`） | 按 provider / 命令 / 模型表格 |
| **Token 消耗** | 输入/输出 token（含 Ollama 估算、线上 API 回传） | 汇总 + breakdown |
| **Agent 行为** | `run_shell` / `write_file` / `web_search` 次数（`events.jsonl`） | 行为节 + 决策结果 |
| **护栏拦截** | blocked / denied / 敏感路径拒绝 ingest | 本周期拦截清单 |
| **文件安全** | kb 敏感文件名、密钥内容、权限；ingest 事前拒绝 `.env`/密钥 | 风险项 + remediation |
| **记忆健康** | 记忆条数、kb/索引一致性、失败 ingest 任务 | 运维向摘要 |

**已实现命令**：

```bash
LA audit              # 交互式摘要（用量 + 行为 + 安全 + 健康）
LA audit --report out.md   # 导出 Markdown 报告
LA audit --since 7d        # 时间范围
```

**原则**：审计数据存本地（`data/audit/`），不上传；报告默认只含聚合统计，不含完整对话正文。破坏性 shell 硬拦截；敏感文件禁止入库。

#### 1.1.6 可靠执行（工具确认 + 幻觉检测）

用户输入直接进入 Agent 主流程，**不做意图预检 / 澄清追问**。

**期望行为**：

1. **直接执行**：每轮用户输入进入 Agent 工具循环
2. **执行前确认**：`run_shell` / `write_file` 按 `LA_TOOL_APPROVAL` 门控
3. **幻觉检测**：模型声称已写入却未调用 `write_file` 时，重试或明确报错
4. **失败重试**：联网天气结果核对失败或命中歌词/教案等垃圾页时，自动换查询再搜

**原则**：

- 不打断用户：不做对话前意图追问
- 副作用可控：写文件与 Shell 需确认；极端危险命令硬拦截
- 失败重试优先于交卷：工具结果不可用时先换查询再试

## 2. 极简 CLI

| 命令 | 作用 |
|------|------|
| `LA chat` | 对话 REPL；记忆/知识 JIT；联网自动触发 |
| `LA memory add "..."` | 直接加记忆（即时生效） |
| `LA rag add <path>` | 软链 + 立即索引单文件到知识库（不提取记忆） |
| `LA rag add -b <path>` | 软链后后台索引 |
| `LA tasks [id]` | 查看索引任务状态 |
| `LA rag ingest` | 索引 `data/kb/` 全部文档（增量） |
| `LA rag ingest --force` | 强制全量重索引 |
| `LA memory ingest chat [--force]` | 从 LocalAgent 对话 jsonl 提取记忆（增量；`--force` 重提） |
| `LA memory ingest chatgpt <path>` | 导入 ChatGPT 导出 JSON |
| `LA memory ingest chatgpt --dir data/chatGPTdata/` | 批量导入目录下全部导出文件 |
| `LA memory ingest all [--force]` | 依次消费 chat / file / chatgpt |
| `LA memory search <query>` | 调试记忆/知识检索 |
| `LA memory query …` | 条件浏览记忆（标签/时间/排序） |
| `LA memory reflect <query>` | 跨记忆推理 |
| `LA memory forget <id>` | 删除一条记忆 |
| `LA memory reset [chat\|file\|chatgpt\|all]` | 按来源清空记忆 |
| `LA rag rebuild` | 清空知识库索引后强制重扫 kb/ |
| `LA memory reindex` | 重建 Mem0 向量索引（不删事实） |
| `LA memory status` | 诊断 Warm 层记忆后端 |
| `LA workspace` | 工作区快照：最近文件、Git、待办 |
| `LA audit` | Token/费用/安全/记忆健康审计；`--report out.md` |

## 3. 记忆与知识库输入

| 来源 | 入口 | 写入路径 | 记忆流程 |
|------|------|----------|----------|
| 个人文件 | `rag add` / `rag ingest` | `data/kb/` | 仅 Cold 知识库，不写 Warm |
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

- `rag add` 软链存在 + RAG 已写入 + sync_index 有记录（无新 Warm 记忆）
- `sync-file` 第二次执行跳过未变更文件
- `chat` 对话持久化到 `data/conversations/*.jsonl`
- LocalAgent 对话与 ChatGPT 导入的提取均走 approve 确认门
- `import-chatgpt data/chatGPTdata/conversations-002.json` 能解析 100 条对话并生成 pending 候选
- 跳过 `is_do_not_remember: true` 的对话；同一 `conversation_id` 重复导入不重复入队（除非 `--force`）
- `LA chat` 可在 Ollama / OpenRouter / Cursor 间切换或 auto 降级
- 联网搜索与 `/deepsearch` 可用（配置 `TAVILY_API_KEY` 后）

**可靠执行**

- 用户输入直接进入 Agent，不做意图预检追问
- `run_shell` / `write_file` 按审批策略确认后执行
- 模型声称已写入却未调用 `write_file` 时，重试或明确报错

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
