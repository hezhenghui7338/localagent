# LocalAgent 需求文档（PRD v1）

**产品名**：LocalAgent（CLI 入口：`LA`）  
**定位**：完全本地的主动式 AI 个人助手——会追问模糊意图，用长期多层次记忆懂你，并能打通本机、用户画像与互联网。

## 0. 核心定位（用户真正关心的事）

LocalAgent 不是「又一个 Chat 客户端」，而是跑在本机上的**主动式个人 AI 中枢**。叙事主线按五件事展开：

| # | 用户关切 | 产品承诺 | 现状 / 方向 |
|---|----------|----------|-------------|
| 1 | **是不是完全本地** | 默认本地 Ollama；对话、记忆写入/召回、文档检索、工作区感知均可离线跑通；可选接入线上模型，但**身份、记忆、审计数据始终留在本机** | ✅ 纯本地路径 + Ollama / OpenRouter / Cursor 统一入口 |
| 2 | **会不会主动搞清楚我想干什么** | 意图模糊且选错代价高时**主动追问**；轻微模糊则假设推进并说明；该做时不打断 | ✅ `LA_INTENT_CLARIFY` 三档预检 + 幻觉检测兜底 |
| 3 | **能不能长期、多层次地记住我** | Hot（核心画像）/ Warm（长期记忆）/ Cold（文档原文）分层；配合强大的 **Mem0** 记忆引擎，跨会话 JIT 召回「懂你」的上下文 | ✅ 分层记忆栈 + Mem0；持续优化召回 |
| 4 | **记忆从哪来、能不能全方位认识我** | 记忆引擎输入支持 **ChatGPT 历史对话**、个人文档、LocalAgent 对话；多源冷启动 → pending 确认 → Mem0 长期记忆，全方位记住用户 | ✅ `import-chatgpt` / `add-file` / chat 提取同一管线 |
| 5 | **能不能真正可用（本机 · 画像 · 联网）** | **联网查询**（Tavily / `/deepsearch`）+ **本地 Shell**（`run_shell`）+ 工作区感知，把电脑本机、用户画像、互联网三层打通 | ✅ workspace / `run_shell` / Tavily；✅ `LA audit` 可审计 |

**一句话**：LocalAgent = **完全本地** + **主动意图澄清** + **长期多层次记忆（Mem0）** + **多源记忆输入** + **本机 · 画像 · 联网三层打通**。

---

## 1. 产品目标

在上述核心定位下，具体目标包括：

1. **完全本地化**：默认本地 Ollama 跑通核心链路；数据与身份不出本机；可选云端模型不改变 owner 边界
2. **主动意图澄清**：收到用户问题时先分析意图；意图不清晰时主动追问，澄清后再执行原任务
3. **长期多层次记忆**：Hot / Warm / Cold + Mem0；助手记住「我是谁、我说过什么」，跨模型不丢身份，但不喧宾夺主
4. **多源记忆冷启动**：ChatGPT 历史导出、个人文档、日常对话作为记忆主输入，全方位沉淀用户画像
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
- **多源输入**：ChatGPT 历史对话导出、个人文档、LocalAgent 日常对话 → 同一管线入库
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

用户抛出问题时，Agent **不应盲目开工**，但更不应过度打断。第一原则是**少打扰**：该做时直接做；不得不问时再问。

**三档决策**：

| mode | 条件 | 行为 |
|------|------|------|
| `act` | 意图已足够执行 | 直接进入工具/回答流程 |
| `assume` | 轻微模糊、做错可逆 | 注入 1–2 条假设后推进，并在回复中说明 |
| `clarify` | 缺失信息会实质改变高代价动作 | 追问 **1** 个关键问题，等待补充 |

**必须放行（act）的典型**：

- 「当前项目 / 本仓库」范围、统计行数、列目录、搜索、跑测试
- 含具体路径/命令；寒暄确认；会话回顾
- 询问已记住的个人事实/偏好（如「我喜欢喝什么」）——直接查记忆，禁止当成推荐场景追问

**才追问（clarify）的典型**：

| 信号 | 示例 |
|------|------|
| 指代不明且上下文无法推断 | 「帮我改一下」「把它优化掉」 |
| 高代价副作用缺关键参数 | 写文件但无路径与改动内容 |
| 多种互斥解读且选错代价高 | 不知是重构、修 bug 还是只读分析 |

**期望行为**：

1. **分析**：每轮用户输入进入 Agent 主流程前，轻量评估（结合近期对话上下文）
2. **假设推进**：轻微模糊时不打断，带假设执行
3. **追问**：仅 clarify 时问 1 个具体问题（不调用工具、不执行副作用）
4. **等待 / 合并**：澄清后将原始问题与补充合并再执行
5. **放行**：明确请求与个人记忆回忆直接处理

**配置**：

- `LA_INTENT_CLARIFY=1`（默认开启）；设为 `0` 可关闭预检，仅依赖 system prompt 兜底

**原则**：

- 少打扰优先：宁可假设推进并说明，也不为琐碎歧义打断用户
- 高代价才澄清：改文件、危险命令等选错代价高时才追问
- 追问要短、要具体：一次最多 1 个问题
- 澄清轮次计入对话历史，便于后续轮次继承上下文

## 2. 极简 CLI

| 命令 | 作用 |
|------|------|
| `LA chat` | 对话 REPL；记忆/知识 JIT；联网自动触发 |
| `LA memory add "..."` | 直接加记忆（即时生效） |
| `LA memory add-file <path>` | 软链 + 立即索引单文件（显示进度） |
| `LA memory add-file -b <path>` | 软链后后台索引 |
| `LA tasks [id]` | 查看索引任务状态 |
| `LA memory ingest file` | 索引 `data/kb/` 全部文档（增量） |
| `LA memory ingest file --force` | 强制全量重索引 |
| `LA memory ingest chat [--force]` | 从 LocalAgent 对话 jsonl 提取记忆（增量；`--force` 重提） |
| `LA memory ingest chatgpt <path>` | 导入 ChatGPT 导出 JSON |
| `LA memory ingest chatgpt --dir data/chatGPTdata/` | 批量导入目录下全部导出文件 |
| `LA memory ingest all [--force]` | 依次消费 chat / file / chatgpt |
| `LA memory search <query>` | 调试记忆/知识检索 |
| `LA memory query …` | 条件浏览记忆（标签/时间/排序） |
| `LA memory reflect <query>` | 跨记忆推理 |
| `LA memory forget <id>` | 删除一条记忆 |
| `LA memory reset [chat\|file\|chatgpt\|all]` | 按来源清空记忆 |
| `LA memory rebuild` | reset all + ingest file --force |
| `LA memory reindex` | 重建 Mem0 向量索引（不删事实） |
| `LA memory status` | 诊断 Warm 层记忆后端 |
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
- 联网搜索与 `/deepsearch` 可用（配置 `TAVILY_API_KEY` 后）

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
