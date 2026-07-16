# LocalAgent 需求文档（PRD v1）

**产品名**：LocalAgent（CLI 入口：`LA` / `la`）  
**定位**：**本机个人 AI 中枢**——零成本默认可玩、真正易用、用智能多层次记忆懂你，并支持本机工具与 RAG。

**一句话**：LocalAgent = **本机个人 AI 中枢** = **完全本地（零成本可玩）** + **易用少命令** + **智能多层次记忆（Mem0）** + **外部工具** + **RAG**。

对外主叙事见 [README.md](../README.md)（中文）/ [README.en.md](../README.en.md)（English）；可跑通故事见 [examples/product-tour.zh-CN.md](../examples/product-tour.zh-CN.md)。

---

## 0. 核心定位

LocalAgent 不是「又一个 Chat 客户端」，而是跑在本机上的**个人 AI 中枢**。模型是「算力供应商」，LocalAgent 是「会话与记忆 owner」。身份、记忆与审计数据始终留本机。

**尚未做（本周期明确不做）**：工作区 watcher 增量索引、外部任务源。

---

## 1. 产品设计（五支柱）

| # | 支柱 | 产品承诺 | 原则 | 现状 |
|---|------|----------|------|------|
| 1 | **完全本地化** | 默认 Ollama 零账单路径；对话、记忆、检索、工作区、Shell 均可离线跑通；可选云端模型 / 联网增强，但**身份、记忆、审计数据始终留本机** | 始终保留纯本地选项；联网是增强不是前提 | ✅ 纯本地路径 + Ollama / OpenRouter / Cursor 统一入口 |
| 2 | **真正易用** | 一键安装（`pipx` pin 版本）、立即可用；日常主路径 `la` / `la setup` / `la chat` | 少即是多：日常能力用少量子命令；运维/实验不挡主路径 | ✅ 安装与三命令主路径；命令面按主路径 / 日常 / 运维分层 |
| 3 | **长期、多层次记忆** | Hot / Warm / Cold + Mem0；跨会话 JIT 召回 | 懂你 = 记住 + 取舍：该记什么、别记什么、何时介入；换模型不换身份；写入可审计可撤销 | ✅ 分层栈 + Mem0；持续优化召回与价值过滤 |
| 4 | **支持外部工具** | 本地 Shell、写文件、工作区；执行前确认；危险命令拦截；可审计花费与行为 | 不做意图预检追问；副作用可控；失败重试优先于交卷 | ✅ 确认门 + 硬拦截 + 幻觉检测 + `LA audit` |
| 5 | **支持 RAG** | 本地文档进 Cold 知识库；对话时可深度召回原文 | 文档不提取为 Warm 事实；对话归档 Cold 先于 Warm 提取 | ✅ `LA rag` + 对话/ChatGPT Cold 归档 |

---

## 2. 用户故事

| # | 作为… | 我想… | 以便… | 主入口 | 验收锚点 |
|---|--------|--------|--------|--------|----------|
| 1 | 普通用户 | 一键装好并马上聊天 | 零门槛上手 | `pipx install …@vX.Y.Z` → `la` / `la setup` | §6.1 |
| 2 | 开发者 | 从源码安装并跑测试 | 改 LA、实验 AI | `pip install -e ".[dev]"` / `uv sync` | §6.1 |
| 3 | 用户 | 用自己注册的 API Key 也能跑 | 不绑死某一厂商 | `la config` / `.env` | §6.1 |
| 4 | 用户 | 被 profile、跨会话记住偏好与事实 | 真正懂我 | Hot pin · Warm Mem0 · `LA chat` | §6.2 |
| 5 | 用户 | 导入 ChatGPT 历史 | 更快认识我 | `LA memory ingest chatgpt` | §6.2 |
| 6 | 用户 | 把本地文档放进知识库并深度召回 | 对话时用上我的材料 | `LA rag add` / `rag search` | §6.2 |
| 7 | 用户 | 联网搜索实时信息 | 小模型也能用好网络 | `web_search` / `/deepsearch`（默认 ddgs） | §6.3 |
| 8 | 用户 | 用本地工具改文件、跑命令 | Agent 真正动手 | `run_shell` / `write_file` / `LA workspace` | §6.3 |
| 9 | 用户 | 危险命令被拦截 | 避免误伤本机 | 护栏 + 确认门 | §6.3 |
| 10 | 用户 | 看清花了多少 token / 费用 | 可控成本 | `LA audit` / `--report` | §6.4 |

---

## 3. 章程（Constitution）

1. **拥抱 AI**：AI 是革命性技术，我们一定要拥抱它。  
2. **实践胜于旁观**：「书读百遍其义自见」不会自动发生；听过一万遍别人谈论 AI，不如一键下载 LA，亲自调试——本机就能开发、使用的个人 AI 中枢。  
3. **本地实验台**：看到新方案或新技术时，不妨先在本机中枢上试一遍，亲自看能做什么、局限在哪。  
4. **只摘低垂成熟的果实**：不引入很重的、无法控制的、成本高昂的技术栈；保证易用，不设置障碍阻止用户使用 AI，相反要不遗余力消除障碍。  
5. **只做一件事——本机个人 AI 中枢**：一切围绕本机可跑通展开。LA **不拒绝联网**，也不拒绝最新技术，但把**数据留在本地**，且**本地也能完整跑通**。  
6. **一起成长**：作者也在持续学习 AI；LA 就是学习 AI 的方式——让我们一起成长。

---

## 4. 能力详述

### 4.1 多模型对话（支撑支柱 1、2）

- 支持 **Ollama**（本地）、**OpenRouter**、**Cursor** 等；通过 `.env` 与 `LA_MODEL_PROVIDER_PRIORITY` 配置优先级
- `LA chat` / `/provider` 在 `auto | ollama | openrouter | cursor` 间切换
- `/model` 为当前路径选择模型并写入 `config/model_servers.yaml`，下次默认使用
- 模型不可用时按优先级自动降级，并在 REPL 中提示当前实际路径
- **原则**：模型是「算力供应商」，LocalAgent 是「会话与记忆 owner」

### 4.2 记忆模块（支柱 3）

- **Hot**：`core_profile.json` — pinned 核心事实（姓名、偏好、长期目标等）/ 用户画像
- **Warm**：结构化长期记忆，优先 **Mem0**（Retain → 多路 Recall → Reflect → Consolidation）；可回退 JSON memory
- **Cold**：Chroma + BM25 — 个人文档原文、图片 VL 描述（`data/kb/`），以及 ChatGPT / LA **对话归档**（摘要 + 轮次块）
- **Warm 输入**：ChatGPT 历史导出、LocalAgent 日常对话 → 事实提取（**Cold 先于 Warm**）
- **Cold 文档输入**：个人文档与图片 → `LA rag`（不提取 Warm 记忆）
- 对话退出 / ChatGPT 导入：候选经 `value_filter` 后 → `pending_queue.json` → `LA memory pending` / `approve` / `reject`；`LA_MEMORY_APPROVAL_AUTO=1` 跳过确认门（CI/基准）；`LA memory add` 仍直接写入
- **精确问双路径**（**默认关图 / 关 Neo4j**，章程：不引入重栈）：计数/聚合/可形式化多跳 → 可选 `LA_NEO4J=1` + Cypher；日常开放语义问 → Warm hybrid / Cold RAG。安装：`pip install 'la-localagent[neo4j]'` 仅在需要时。
- **原则**：换模型不换身份；该记则记、不该记则跳过（如 `is_do_not_remember`）；写入可审计、可撤销

### 4.3 联网（可选增强）

- **默认 ddgs**（无需 API Key）；可选 Tavily / SearXNG 提升质量
- `/deepsearch <主题>` 多步检索与归纳
- 联网结果默认**不**自动入库；若含可沉淀事实，仍走 pending 确认

### 4.4 本地文件、工作区与可靠执行（支柱 4）

用户期望 Agent 能回答并协助：

| 场景 | 期望行为 |
|------|----------|
| 我最近干了啥 | 汇总近期改动的文件、Git commit、对话中提取的任务 |
| 文件出现了怎样的变化 | 工作目录 diff / 最近修改列表 |
| Git 记录是怎样的 | `git log`、`git status`、分支与未提交变更的自然语言摘要 |
| 有什么待办 | 聚合 TODO 注释、markdown checkbox、对话 pending |

**已实现**：工作区根目录（`LA_WORKSPACE` / `LA chat --cwd`）、最近文件、Git 摘要（只读）、Todo 扫描、`LA workspace`；`run_shell` / `write_file` 确认门；写文件幻觉检测；危险命令硬拦截。

**尚未做**：工作区 watcher 增量索引、与 `rag` 索引更紧协同、外部任务源。

用户输入直接进入 Agent，**不做意图预检 / 澄清追问**。

1. **直接执行**：每轮用户输入进入 Agent 工具循环  
2. **执行前确认**：`run_shell` / `write_file` 按 `LA_TOOL_APPROVAL` 门控  
3. **幻觉检测**：模型声称已写入却未调用 `write_file` 时，重试或明确报错  
4. **失败重试**：联网结果不可用时先换查询再试  

### 4.5 审计与报告（支柱 4）

Audit 是本地**监察官**：执行前护栏拦截危害动作，append-only 事件流留证，`LA audit` 出具报告。三层分离——**护栏（拦）≠ 轨迹（记）≠ 报告（算）**。

| 审计维度 | 采集内容 | 报告呈现 |
|----------|----------|----------|
| **服务花费** | 各 provider 调用次数、估算费用（`usage.jsonl`） | 按 provider / 命令 / 模型表格 |
| **Token 消耗** | 输入/输出 token | 汇总 + breakdown |
| **Agent 行为** | `run_shell` / `write_file` / `web_search` 次数 | 行为节 + 决策结果 |
| **护栏拦截** | blocked / denied / 敏感路径拒绝 ingest | 本周期拦截清单 |
| **文件安全** | kb 敏感文件名、密钥内容 | 风险项 + remediation |
| **记忆健康** | 记忆条数、kb/索引一致性 | 运维向摘要 |

```bash
LA audit              # 交互式摘要
LA audit --report out.md
LA audit --since 7d
```

**原则**：审计数据存本地（`data/audit/`），不上传；报告默认只含聚合统计。

### 4.6 文档 RAG（支柱 5）

- `LA rag add` / `rag ingest`：软链 + 索引个人文档（含 VL 图片文本化）
- 对话时 `search_knowledge` / `rag search` 深度召回 Cold（文档 + 对话归档）
- 与 Warm 分离：文档不进事实提取主路径

---

## 5. 极简 CLI（按真实 client 分层）

普通用户几乎只在 **对话**里完成工作；下列命令按任务分层。会话内 `/memory add` 等与外层同名路径等价；`/add`、`/search` 仅为会话快捷方式（外层请写完整 `LA memory …`）。

### 5.1 主路径（少即是多）

| 命令 | 作用 |
|------|------|
| `la` / `LA chat` | 对话 REPL；记忆/知识 JIT；联网按需 |
| `la setup` | 引导安装 Ollama / 拉取默认模型（`-y` 免确认） |
| `la config` / `la config-example` | 纯本地或自有 API 配置 |

### 5.2 日常能力（用户故事对应）

| 我想… | 命令 |
|------|------|
| 记住一句话 | `LA memory add "..."` |
| 搜我记得的事 | `LA memory search <query>` |
| 审阅待写入记忆 | `LA memory pending` → `approve` / `reject` |
| 导入 ChatGPT | `LA memory ingest chatgpt <path>` |
| 把文档放进知识库 | `LA rag add <path>` → `LA rag search <query>` |
| 看花费与安全 | `LA audit` / `--report out.md` |
| 删一条记忆 | `LA memory forget <id>` |

会话内还可：`/provider` · `/model` · `/deepsearch <主题>`（联网默认 ddgs，见 §4.3）。

### 5.3 运维与实验（默认不教日常用户）

| 命令 | 作用 |
|------|------|
| `LA memory ingest chat [--force]` | 从 LA 对话补提取（Cold 先于 Warm） |
| `LA memory ingest all [--force]` | 依次消费 chat / chatgpt 等 |
| `LA memory query …` | 按标签/时间浏览（高级；日常用 search） |
| `LA memory reflect <query>` | 跨记忆+知识库归纳 |
| `LA memory status` / `reindex` / `reset` | 诊断 / 重建索引 / 按来源清空 |
| `LA memory graph …` | 关系图 / Neo4j（默认关闭） |
| `LA rag ingest` / `rebuild` / `reset` | 扫描 kb、重建或清空 Cold 索引 |
| `LA tasks` | 后台索引任务 |
| `LA workspace` / `LA logs` / `LA websearch` | 工作区快照、诊断日志、直连联网 |

### 5.3 记忆与知识库输入

| 来源 | 入口 | 写入路径 | 流程 |
|------|------|----------|------|
| 个人文件 | `rag add` / `rag ingest` | `data/kb/` → Cold | 原文分块索引；不提取 Warm |
| LocalAgent 对话 | `LA chat` 退出 / `memory ingest chat` | `data/conversations/` | **先 Cold** → 再 Warm 事实提取 |
| **ChatGPT 导出** | `memory ingest chatgpt` | `data/chatGPTdata/`（只读归档） | **先 Cold** → 再 Warm 事实提取 |

#### ChatGPT 对话导入

用户从 ChatGPT **Settings → Data Controls → Export** 获得 `conversations.json`，放入 `data/chatGPTdata/`。

**格式要点**：顶层对话数组；消息在 `mapping` 树；跳过 `is_do_not_remember: true`；剥离联网引用标记。

**导入行为**：

1. 解析 JSON，重建 user/assistant 轮次  
2. **Cold（始终）**：摘要 chunk + 轮次原文 → 混合索引  
3. **Warm（尽力）**：提取个人事实；失败不影响 Cold  
4. 原始 JSON 只读归档；索引防重复；`--force` 时 Cold + Warm 重跑  

召回：事实用 `memory search`；对话原文/摘要用 `rag search` / `search_knowledge`。

---

## 6. 验收标准

### 6.1 安装 · 配置 · 多模型（故事 1–3）

- pin 版本 `pipx install …@vX.Y.Z` 后 `la --version` 正确；`la` / `la setup` 可引导 Ollama
- 源码 `pip install -e ".[dev]"` 可开发与测试
- `la config` 可配置纯本地 Ollama 或自有 OpenRouter / Cursor Key
- `LA chat` 可在 Ollama / OpenRouter / Cursor 间切换或 auto 降级

### 6.2 记忆 · ChatGPT · RAG（故事 4–6）

- Hot 画像 / Warm 事实跨会话可召回；价值过滤与 pending 确认门可用
- `memory ingest chatgpt` / `chat`：**Cold 先于 Warm**；`no_facts` 时仍有 `cold_chunks>0` 且 `rag search` 可命中
- 跳过 `is_do_not_remember: true`；同一 `conversation_id` 默认不重复（除非 `--force`）
- `rag add` 软链存在 + RAG 已写入 + sync_index 有记录（无新 Warm 记忆）
- `chat` 对话持久化到 `data/conversations/`

### 6.3 联网 · 本机工具 · 安全（故事 7–9）

- 联网搜索与 `/deepsearch` **默认 ddgs 可用**（无需 Tavily）；Tavily / SearXNG 为可选增强
- 用户输入直接进入 Agent，不做意图预检追问
- `run_shell` / `write_file` 按审批策略确认后执行；危险命令硬拦截
- 模型声称已写入却未调用 `write_file` 时，重试或明确报错
- `LA workspace`：最近文件、Git 摘要、TODO 扫描可用

### 6.4 审计（故事 10）

- 模型调用记录 provider、模型、估算 token 与费用到本地 audit 日志
- `LA audit --report` 生成含花费、token、安全扫描结果的 Markdown 报告
- 报告可指定时间范围；敏感文件误索引项可被列出并给出修复建议

**尚未做**：工作区 watcher 增量索引、外部任务源。`LA audit --report *.html` 已支持。
