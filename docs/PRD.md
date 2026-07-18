# LocalAgent 需求文档（PRD v1）

**产品名**：LocalAgent（CLI 入口：`LA` / `la`）  
**定位三板斧**：**Local First. Memory Forever. Actions Automated.**  
**一句话**：Local AI that remembers and gets things done.  
**中文一句话**：本地 AI：记得住你，也能把事办完。

**定位**：本地个人 AI——默认本机可完整跑通；跨会话持久记住你；能动手把事办完（工具循环 · 日常旁路 · 定时），副作用可控。

对外主叙事见 [README.md](../README.md)（英文默认 · [中文](../README.zh-CN.md)）；可跑通故事见 [examples/product-tour.zh-CN.md](../examples/product-tour.zh-CN.md)。

---

## 0. 核心定位

LocalAgent 不是「又一个 Chat 客户端」，而是跑在本机上的**个人 AI**：模型是「算力供应商」，LocalAgent 是「会话与记忆 owner」。身份、记忆与审计数据始终留本机。

**三词精确定义**

| 词 | 含义 | 不是 |
|----|------|------|
| **Local First** | 默认本机可完整跑通；云/网可选增强；身份、记忆、审计永不离开本机 | 拒绝一切联网 |
| **Memory Forever** | 跨会话 / 换模型身份仍在；Hot·Warm·Cold 持久栈；取舍与 forget 保证质量 | 死记一切、永不删除 |
| **Actions Automated** | 代劳执行到结果（工具循环、日常旁路、定时）；确认门 + 危险硬拦 | 无人值守乱改本机 |

**本周期明确不做**：工作区 watcher 增量索引、外部任务源、完全无人值守的定时 Shell。

---

## 1. 产品设计（三支柱）

| # | 支柱 | 产品承诺 | 原则 | 现状 |
|---|------|----------|------|------|
| 1 | **Local First** | 默认 Ollama 零账单路径；对话、记忆、检索、工作区、Shell 均可离线跑通；一键安装、三命令主路径；可选云端 / 联网，但**身份、记忆、审计始终留本机** | 始终保留纯本地选项；联网是增强不是前提；少即是多 | ✅ 纯本地路径 + Ollama / OpenRouter / Cursor；`la` / `la setup` / `la chat` |
| 2 | **Memory Forever** | Hot / Warm / Cold + Mem0；跨会话 JIT 召回；本地文档进 Cold；ChatGPT 可导入 | 懂你 = 记住 + 取舍；换模型不换身份；Cold 先于 Warm；写入可审计可撤销 | ✅ 分层栈 + Mem0 + `LA rag` + pending 确认门 |
| 3 | **Actions Automated** | 本机 Shell / 写文件 / 工作区；日常旁路（summarize · news · polish）；新闻定时；办完回执；会话内同模式少打断；审计护栏 | 不做意图预检追问；副作用可控；失败重试优先于交卷；危险硬拦不可记忆化放行 | ✅ 工具确认门 + 硬拦截 + 幻觉检测 + 日常三剑客 + schedule + Action receipt + approve-once + `la status` |

**支撑能力**（不与三核并列占对外主位）：易用三命令、日常旁路、RAG、审计——分别挂在对应支柱下证明承诺。

---

## 2. 用户故事

### Local First

| # | 作为… | 我想… | 以便… | 主入口 | 验收锚点 |
|---|--------|--------|--------|--------|----------|
| 1 | 普通用户 | 一键装好并马上聊天 | 零门槛上手 | `pipx install …@vX.Y.Z` → `la` / `la setup` | §6.1 |
| 2 | 开发者 | 从源码安装并跑测试 | 改 LA、实验 AI | `pip install -e ".[dev]"` / `uv sync` | §6.1 |
| 3 | 用户 | 用自己注册的 API Key 也能跑 | 不绑死某一厂商 | `la config` / `.env` | §6.1 |

### Memory Forever

| # | 作为… | 我想… | 以便… | 主入口 | 验收锚点 |
|---|--------|--------|--------|--------|----------|
| 4 | 用户 | 被 profile、跨会话记住偏好与事实 | 真正懂我 | Hot pin · Warm Mem0 · `LA chat` | §6.2 |
| 5 | 用户 | 导入 ChatGPT 历史 | 更快认识我 | `LA memory ingest chatgpt` | §6.2 |
| 6 | 用户 | 把本地文档放进知识库并深度召回 | 对话时用上我的材料 | `LA rag add` / `rag search` | §6.2 |

### Actions Automated

| # | 作为… | 我想… | 以便… | 主入口 | 验收锚点 |
|---|--------|--------|--------|--------|----------|
| 7 | 用户 | 联网搜索实时信息 | 小模型也能用好网络 | `web_search` / `/deepsearch`（默认 ddgs） | §6.3 |
| 8 | 用户 | 用本地工具改文件、跑命令 | Agent 真正动手 | `run_shell` / `write_file` / `LA workspace` | §6.3 |
| 9 | 用户 | 危险命令被拦截 | 避免误伤本机 | 护栏 + 确认门 | §6.3 |
| 10 | 用户 | 看清花了多少 token / 费用 | 可控成本 | `LA audit` / `--report` | §6.3 |
| 11 | 用户 | 一键总结本地文档 | 3 分钟读懂；默认文档对话；默认不入库 | `la summarize` / `sum>` | §6.3 |
| 12 | 用户 | 嗅探今日资讯并浏览简报 | 替代每天手动刷 | `la news sync/brief`；`schedule on` | §6.3 |
| 13 | 用户 | 一键润色文案 | 识别场合后改写；主推进剪贴板 | `la polish` / `/polish` | §6.3 |
| 14 | 用户 | 工具办完后看到回执 | 确认「办完了什么」 | Agent 回合末 Action receipt | §6.3 |
| 15 | 用户 | 同会话对同类安全操作少确认 | 连续改文件不打断 | Session approve-once | §6.3 |
| 16 | 用户 | 打开 LA 看到今日待办信号 | 知道有什么可办 / 已准备好 | Daily Actions 表面（横幅 / `la status`） | §6.3 |

---

## 3. 章程（Constitution）

1. **拥抱 AI**：AI 是革命性技术，我们一定要拥抱它。  
2. **实践胜于旁观**：「书读百遍其义自见」不会自动发生；听过一万遍别人谈论 AI，不如一键下载 LA，亲自调试——本机就能开发、使用的个人 AI。  
3. **本地实验台**：看到新方案或新技术时，不妨先在本机助手上试一遍，亲自看能做什么、局限在哪。  
4. **只摘低垂成熟的果实**：不引入很重的、无法控制的、成本高昂的技术栈；保证易用，不设置障碍阻止用户使用 AI，相反要不遗余力消除障碍。  
5. **只做一件事——本地 AI：记得住、办得完**：一切围绕本机可跑通、持久记忆、可靠行动展开。LA **不拒绝联网**，也不拒绝最新技术，但把**数据留在本地**，且**本地也能完整跑通**。

---

## 4. 能力详述

### 4.1 多模型对话（Local First）

- 支持 **Ollama**（本地）、**OpenRouter**、**Cursor** 等；通过 `.env` 与 `LA_MODEL_PROVIDER_PRIORITY` 配置优先级
- `LA chat` / `/provider` 在 `auto | ollama | openrouter | cursor` 间切换
- `/model` 为当前路径选择模型并写入 `config/model_servers.yaml`，下次默认使用
- 模型不可用时按优先级自动降级，并在 REPL 中提示当前实际路径
- **原则**：模型是「算力供应商」，LocalAgent 是「会话与记忆 owner」

### 4.2 记忆模块（Memory Forever）

- **Hot**：`core_profile.json` — pinned 核心事实（姓名、偏好、长期目标等）/ 用户画像
- **Warm**：结构化长期记忆，优先 **Mem0**（Retain → 多路 Recall → Reflect → Consolidation）；可回退 JSON memory
- **Cold**：Chroma + BM25 — 个人文档原文（`data/kb/`），以及 ChatGPT / LA **对话归档**（摘要 + 轮次块）
- **Warm 输入**：ChatGPT 历史导出、LocalAgent 日常对话 → 事实提取（**Cold 先于 Warm**）
- **Cold 文档输入**：个人文档 → `LA rag`（不提取 Warm 记忆）
- 对话退出 / ChatGPT 导入：候选经 `value_filter` 后 → `pending_queue.json` → `LA memory pending` / `approve` / `reject`；`LA_MEMORY_APPROVAL_AUTO=1` 跳过确认门（CI/基准）；`LA memory add` 仍直接写入
- **精确问双路径**（**默认关图 / 关 Neo4j**，章程：不引入重栈）：计数/聚合/可形式化多跳 → 可选 `LA_NEO4J=1` + Cypher；日常开放语义问 → Warm hybrid / Cold RAG。安装：`pip install 'la-localagent[neo4j]'` 仅在需要时。
- **原则**：换模型不换身份；该记则记、不该记则跳过（如 `is_do_not_remember`）；写入可审计、可撤销

### 4.3 联网（Actions · 可选增强）

- **默认 ddgs**（无需 API Key）；可选 Tavily / SearXNG 提升质量
- `/deepsearch <主题>` 多步检索与归纳
- 联网结果默认**不**自动入库；若含可沉淀事实，仍走 pending 确认

### 4.4 本地文件、工作区与可靠执行（Actions）

用户期望 Agent 能回答并协助：

| 场景 | 期望行为 |
|------|----------|
| 我最近干了啥 | 汇总近期改动的文件、Git commit、对话中提取的任务 |
| 文件出现了怎样的变化 | 工作目录 diff / 最近修改列表 |
| Git 记录是怎样的 | `git log`、`git status`、分支与未提交变更的自然语言摘要 |
| 有什么待办 | 聚合 TODO 注释、markdown checkbox、对话 pending |

**已实现**：工作区根目录（`LA_WORKSPACE` / `LA chat --cwd`）、最近文件、Git 摘要（只读）、Todo 扫描、`LA workspace`；`run_shell` / `write_file` 确认门；写文件幻觉检测；危险命令硬拦截。

**本周期补强**：

1. **Action receipt**：本轮若调用了副作用工具（`run_shell` / `write_file` 等），回合末给出结构化回执（做了什么、改了哪些路径、是否已确认）。复用 audit 事件轨迹。  
2. **Session approve-once**：用户对某次确认可选择「本会话相同模式不再问」；危险命令分类仍硬拦，不可放行记忆化。  
3. **Daily Actions 表面**：打开 `la` / 欢迎横幅或 `la status` 聚合：今日新闻是否已 sync、memory pending 条数、workspace 待办摘要。

**下一周期**：工作区 watcher 增量索引、与 `rag` 索引更紧协同、外部任务源。

用户输入直接进入 Agent，**不做意图预检 / 澄清追问**。

1. **直接执行**：每轮用户输入进入 Agent 工具循环  
2. **执行前确认**：`run_shell` / `write_file` 按 `LA_TOOL_APPROVAL` 门控；支持会话级 approve-once  
3. **幻觉检测**：模型声称已写入却未调用 `write_file` 时，重试或明确报错  
4. **失败重试**：联网结果不可用时先换查询再试  
5. **办完回执**：有副作用工具时输出 Action receipt

### 4.5 审计与报告（Actions · 信任刹车）

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

### 4.6 文档 RAG（Memory Forever · Cold）

- `LA rag add` / `rag ingest`：软链 + 索引个人文档（`.txt` / `.md` / `.pdf` / `.xlsx` 等）
- 对话时 `search_knowledge` / `rag search` 深度召回 Cold（文档 + 对话归档）
- 与 Warm 分离：文档不进事实提取主路径

### 4.7 一键总结 / 文档对话（Actions · 旁路快捷）

- `la summarize <path>`：短文档优先；输出「最多三句话」+ 结构化要点（〔§章节 | p.页〕）；**TTY 下默认进入 `sum>` 文档对话**
- `--no-chat`：仅速读（可多文件 / `--out`）；不进入对话
- **默认不入库**；会话内 `/keep` 或 `--keep` 收藏到 Cold 知识库；**禁止**每次总结后追问是否入库
- `--list` / `--resume` / `--id`：文档对话可离开再续
- 与 `la chat` 区分：chat = 和助手聊；summarize = 针对已打开文件的速读/深聊
- 对话内工具：`summarize_document`（原子速读）

### 4.8 一键润色（Actions · 旁路快捷）

- `la polish` / `/polish`：旁路 Agent 循环；识别邮件 / 朋友圈 / 简历 / 商务对话场景与态度后改写
- 输出 Taste Brief + 主推 + 两个备选 + 改动说明；**默认将主推写入系统剪贴板**（`--no-copy` 可关）
- 可选 `--scene` / `--tone`；注入 Hot 画像偏好（若有）；硬约束禁止编造数字/承诺（尤其简历）
- 与「一键总结」同属旁路快捷能力；不进入 `run_shell` / 写文件工具循环

### 4.9 新闻嗅探（Actions · 旁路 + 定时）

- 默认信源：BestBlogs RSS（AI 精选池；可改 `LA_NEWS_RSS_URL`）
- `la news sync` → `la news brief`：TTY 下进入交互浏览器（↑↓/`jk` 切换；`o`/Enter 打开系统浏览器；OSC 8 可点标题；`r` 精读后进入与 summarize 同款深聊）；`--no-ui` 一次性 dump
- `la news read <id|url>`：抓正文 → 总结卡片；默认不入库，`--keep` 可选
- `la news schedule on|off`：本机定时（默认每天 08:00）；可关
- 进入 `la`/`la chat` 且当日已 sync、已过同步时刻：提示「今日更新已准备好」
- 简报默认不进 Warm；与 `value_filter` 新闻 ephemeral 策略一致
- Agent 工具：`news_brief` / `news_read` / `news_mark`；OpenAPI 为后续可选（Free 额度珍惜）

### 4.10 Actions 三档

| 档 | 能力 | 说明 |
|----|------|------|
| 旁路快捷 | summarize · news · polish | 不走漫长 Agent 工具循环，直接出结果 |
| Agent 工具循环 | `run_shell` / `write_file` / workspace / web_search | 执行前确认；approve-once；办完回执 |
| 定时 | `la news schedule` | 本机定时准备，打开 LA 可见就绪信号 |

---

## 5. 极简 CLI（按真实 client 分层）

普通用户几乎只在 **对话**里完成工作；下列命令按任务分层。会话内 `/memory add` 等与外层同名路径等价；`/add`、`/search` 仅为会话快捷方式（外层请写完整 `LA memory …`）。

### 5.1 主路径（少即是多）

| 命令 | 作用 |
|------|------|
| `la` / `LA chat` | 对话 REPL；记忆/知识 JIT；联网按需；Daily Actions 信号 |
| `la setup` | 引导安装 Ollama / 拉取默认模型（`-y` 免确认） |
| `la config` / `la config-example` | 纯本地或自有 API 配置 |
| `la status` | Daily Actions 摘要：新闻就绪 / pending / workspace 待办 |

### 5.2 日常能力（用户故事对应）

| 我想… | 命令 |
|------|------|
| 记住一句话 | `LA memory add "..."` |
| 搜我记得的事 | `LA memory search <query>` |
| 审阅待写入记忆 | `LA memory pending` → `approve` / `reject` |
| 导入 ChatGPT | `LA memory ingest chatgpt <path>` |
| 把文档放进知识库 | `LA rag add <path>` → `LA rag search <query>` |
| 一键总结文档（默认文档对话，不入库） | `la summarize <path>` → `sum>`；长期召回：`--keep` / `/keep`；仅速读：`--no-chat` |
| 新闻嗅探 / 今日简报 | `la news sync` → `la news brief`（TTY 交互）；`r` 精读深聊；`la news schedule on` |
| 一键润色文案（默认复制主推） | `la polish "草稿"` / `/polish`；`--scene` · `--tone` · `--no-copy` |
| 看今日待办信号 | `la status` |
| 看花费与安全 | `LA audit` / `--report out.md` |
| 删一条记忆 | `LA memory forget <id>` |

会话内还可：`/provider` · `/model` · `/deepsearch <主题>` · `/polish <草稿>`（联网默认 ddgs，见 §4.3）。

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
| `LA news skim` / `read` / `mark` … | 新闻速读/精读/标记等（日常主路径见 `brief`） |

### 5.4 记忆与知识库输入

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

### 6.1 Local First（故事 1–3）

- pin 版本 `pipx install …@vX.Y.Z` 后 `la --version` 正确；`la` / `la setup` 可引导 Ollama
- 源码 `pip install -e ".[dev]"` 可开发与测试
- `la config` 可配置纯本地 Ollama 或自有 OpenRouter / Cursor Key
- `LA chat` 可在 Ollama / OpenRouter / Cursor 间切换或 auto 降级
- CLI / 官网 / README 主标为三板斧与一句话；旧主权 slogan 不再作主标

### 6.2 Memory Forever（故事 4–6）

- Hot 画像 / Warm 事实跨会话可召回；价值过滤与 pending 确认门可用
- `memory ingest chatgpt` / `chat`：**Cold 先于 Warm**；`no_facts` 时仍有 `cold_chunks>0` 且 `rag search` 可命中
- 跳过 `is_do_not_remember: true`；同一 `conversation_id` 默认不重复（除非 `--force`）
- `rag add` 软链存在 + RAG 已写入 + sync_index 有记录（无新 Warm 记忆）
- `chat` 对话持久化到 `data/conversations/`

### 6.3 Actions Automated（故事 7–16）

- 联网搜索与 `/deepsearch` **默认 ddgs 可用**（无需 Tavily）；Tavily / SearXNG 为可选增强
- 用户输入直接进入 Agent，不做意图预检追问
- `run_shell` / `write_file` 按审批策略确认后执行；危险命令硬拦截
- 模型声称已写入却未调用 `write_file` 时，重试或明确报错
- `LA workspace`：最近文件、Git 摘要、TODO 扫描可用
- **一键总结**：`la summarize <path>` 输出 1～3 句 + 〔§/p.〕要点；TTY 默认进 `sum>`；默认不写 kb；`--keep` / `/keep` 后可检索；不追问入库
- **新闻嗅探**：`la news sync` 拉取 BestBlogs RSS；TTY 下 `la news brief` 可 ↑↓ 浏览、`o` 打开浏览器、`r` 精读深聊；`schedule on/off` 控制早 8 点自动 sync；入 chat 可提示就绪
- **一键润色**：`la polish` / `/polish` 输出识别 Brief + 主推/备选；默认主推进剪贴板；`--no-copy` 可关；简历场景不编造原文没有的数字
- **Action receipt**：本轮有副作用工具调用时，输出含工具名/路径或命令摘要的回执
- **Session approve-once**：用户选择后，同会话同类安全操作不再交互确认；危险命令仍硬拦
- **Daily Actions**：`la status` 或欢迎横幅可见新闻就绪 / pending 条数 / workspace 待办信号
- 模型调用记录 provider、模型、估算 token 与费用到本地 audit 日志
- `LA audit --report` 生成含花费、token、安全扫描结果的 Markdown 报告

**下一周期**：工作区 watcher 增量索引、外部任务源；新闻 OpenAPI / 个人 OPML（MVP 仅 BestBlogs RSS）；完全无人值守定时 Shell。`LA audit --report *.html` 已支持。
