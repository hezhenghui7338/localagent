# LocalAgent 需求文档（PRD v1）

**产品名**：LocalAgent（CLI 入口：`LA` / `la`）  
**一句话**：The AI that lives on your computer.  
**中文一句话**：栖居在你电脑里的 AI。  
**定位三板斧**：**本地优先，真记得你，把事办完。**（Local First. Memory Forever. Actions Automated.；特性专业化拆分，次于一句话）

**定位**：本地个人 AI——默认本机可完整跑通；跨会话持久记住你；能动手把事办完（工具循环 · 日常快捷功能 · 定时），副作用可控。

对外设计主线见 [README.md](../README.md)（英文默认 · [中文](../README.zh-CN.md)）；可跑通故事见 [examples/product-tour.zh-CN.md](../examples/product-tour.zh-CN.md)。

---

## 0. 核心定位

LocalAgent 不是「又一个 Chat 客户端」，而是跑在本机上的**个人 AI**：算力默认本机，也可选用外部模型服务；模型与 LocalAgent 相互独立——越好的模型效果越好，小模型也能跑通基本任务。身份、记忆与审计**本地数据**存本机、不上传；选用云端推理或联网搜索时，当轮内容会上传到对应服务。

**三词精确定义**

| 词 | 含义 | 不是 |
|----|------|------|
| **Local First** | 默认本机可完整跑通；云/网可选增强；身份、记忆、审计**本地数据**存本机（存储不上传；推理/搜索内容会上传到对应服务） | 拒绝一切联网；声称零外传 |
| **Memory Forever** | 跨会话 / 换模型身份仍在；Hot·Warm·Cold 持久栈；取舍与 forget 保证质量 | 死记一切、永不删除 |
| **Actions Automated** | 代劳执行到结果（工具循环、日常快捷功能、定时）；确认门 + 危险命令直接拦截 | 无人值守乱改本机 |

**本周期明确不做**：外部任务源、完全无人值守的定时 Shell、屏幕/音频录制式全量感知。

**Aware（本机感知，MVP 已落地）**：`la aware`（默认概览：当前电脑状态优先 + 最近 3 小时动态，随后进入 `aware>`）/ `--no-chat` / `--detail` / `--since` / `tick`；Episode 会话化；`apps` 前台焦点 + Now Playing + HID 空闲估算的「今日输入活跃」时长（按前台应用分桶，不记按键内容）；场景分类（music/video/coding/call…）；Hypothesis → insight suggestion；`la chat` 相关问题时注入感知上下文（默认近 3 小时）。按源 opt-in（`fs` / `browser` / `git` / `terminal` / `apps`）；可索引文件仅进 `suggestion`（须用户确认后 `LA ingest doc`），绝不自动写入 Cold/`kb/`；另有 wellness/insight suggestion。后续：`wechat`；TODO：`calendar` / `email`。不做录屏、不做键内容捕、不自动任意 Shell。

---

## 1. 产品设计（三大核心理念）

| # | 核心理念 | 产品承诺 | 原则 | 现状 |
|---|------|----------|------|------|
| 1 | **Local First** | 默认 Ollama 零成本使用；对话、记忆、检索、工作区、Shell 均可离线跑通；一键安装、三命令常用路径；可选云端 / 联网，**本地数据存本机**；云端/搜索会上传当轮内容 | 始终保留纯本地选项；联网是增强不是前提；少即是多；文案区分「存储」与「推理」 | ✅ 纯本地路径 + Ollama / OpenRouter / Cursor；`la` / `la setup` / `la chat` |
| 2 | **Memory Forever** | Hot / Warm / Cold + Mem0；跨会话 JIT 召回；本地文档进 Cold；ChatGPT 可导入；可选 cross-encoder rerank 提升召回排序 | 懂你 = 记住 + 取舍；换模型不换身份；Cold 先于 Warm；写入可审计可撤销 | ✅ 分层栈 + Mem0 + `LA rag` + pending 确认门 + Rerank（`[rerank]` extra） |
| 3 | **Actions Automated** | 本机 Shell / 写文件 / 工作区；日常快捷功能；新闻定时；多步里程碑规划 + 跨 turn 续跑；工具结果校验；可选 MCP 扩展；办完回执；审计护栏 | 不向用户做意图预检追问；内部自动路由执行路径；副作用可控；失败重试优先于交卷；危险命令直接拦截不可记忆化放行 | ✅ Context Engine JIT + milestone planner + validation + session work + 工具确认门 + 直接拦截 + 幻觉检测 + 日常快捷功能（含 Aware）+ 操作回执 + 会话内免重复确认 + 可选 MCP + `la status` |

**支撑能力**（不与三核并列占对外主位）：易用三命令、日常快捷功能、RAG、审计——分别挂在对应核心理念下证明承诺。

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
| 5 | 用户 | 导入 ChatGPT 历史 | 更快认识我 | `LA ingest chatgpt` | §6.2 |
| 6 | 用户 | 把本地文档放进知识库并检索原文 | 对话时用上我的材料 | `LA ingest doc` / `rag search` | §6.2 |

### Actions Automated

| # | 作为… | 我想… | 以便… | 主入口 | 验收锚点 |
|---|--------|--------|--------|--------|----------|
| 7 | 用户 | 联网搜索实时信息 | 本地小模型也能联网查资料 | `web_search` / `/deepsearch`（默认 ddgs） | §6.3 |
| 8 | 用户 | 用本地工具改文件、跑命令 | Agent 真正动手 | `run_shell` / `write_file` / `LA workspace` | §6.3 |
| 9 | 用户 | 危险命令被拦截 | 避免误伤本机 | 护栏 + 确认门 | §6.3 |
| 10 | 用户 | 看清花了多少 token / 费用 | 可控成本 | `LA audit` / `--report` | §6.3 |
| 10b | 用户 | 从截图/扫描件拿到可复制原文 | 不要 LLM 瞎编菜单/表格内容 | `la ocr <path>` | §6.3 |
| 11 | 用户 | 一键总结本地文档 | 3 分钟读懂；默认文档对话；默认不入库 | `la summarize` / `sum>` | §6.3 |
| 12 | 用户 | 嗅探今日资讯并浏览简报 | 替代每天手动刷 | `la news sync/brief`；`schedule on` | §6.3 |
| 13 | 用户 | 一键润色文案 | 识别场合后改写；主推进剪贴板 | `la polish` / `/polish` | §6.3 |
| 13b | 用户 | 授权后感知本机工作上下文 | opt-in 采集；不自动入库；相关时注入 chat | `la aware` / `grant` / `tick` / `suggestion` | §6.3 |
| 14 | 用户 | 工具办完后看到回执 | 确认「办完了什么」 | Agent 回合末操作回执（Action receipt） | §6.3 |
| 15 | 用户 | 同会话对同类安全操作少确认 | 连续改文件不打断 | 会话内免重复确认（approve-once） | §6.3 |
| 16 | 用户 | 打开 LA 看到今日待办信号与数据层摘要 | 知道有什么可办 / 库里有什么 | Daily Actions + 数据层（横幅高层次 / `la status`·`/status` 明细） | §6.3 |
| 17 | 用户 | 聊天时看到 LA 在做什么（预加载、调工具、等确认） | 知道「搜了什么、调了什么、为什么停」而不被技术细节刷屏 | Turn 内 `[chat] …` status 行 + 操作回执 | §6.3 · TDD §8 |
| 18 | 用户 | 需要时可展开本轮执行细节 | 排查 prefetch 命中、里程碑进度、校验失败原因 | `LA_TRACE=1` / `/trace on`（设计目标）· `/last-turn` · `la audit` | §6.3 · TDD §8 |
| 19 | 用户 | 复杂多步任务被自动拆步执行 | 不用自己拆 todo；回合末回执看 ✓/○ 进度 | `LA chat`（复杂度判断 → milestone planner） | §4.11 · §6.3 |
| 20 | 用户 | 说「继续/下一步」接着上次未完成任务 | 多 turn 行动不必重述上下文 | `LA chat`（session work 续跑） | §4.11 · §6.3 |
| 21 | 用户 | 连接 MCP server 扩展 Agent 工具 | 用 GitHub/DB 等外部能力而不改 LA 源码 | `la mcp list` · `config/mcp.yaml` | §4.12 · §6.3 |
| 22 | 用户 | 在 chat 里说「记住 xxx」快速写入 | 不必切到 `LA ingest text` | `LA chat`（显式 remember 短路） | §4.11 · §6.3 |

**可观测性分层（故事 17–18）**：L0 默认只看阶段与关键动作（prefetch 命中、工具调用、审批、生成）；L1 verbose 展开路由模块、里程碑 i/N、validation 摘要；L2 用 `la audit` / `la logs` 复盘全链。`/status` 仍是数据层库存，**不是** turn trace；执行 trace 用 `/trace`（与 `/status` 相互独立，见 TDD §8.1）。

## 3. 章程（Constitution）

1. **实践反馈**：LA 致力于提供高质量的 AI 实践反馈。  
2. **实践胜于旁观**：「书读百遍其义自见」不会自己发生；真正懂，靠的是一遍遍实践——本机就能开发、使用的个人 AI。  
3. **本地实验台**：看到新方案或新技术时，不妨先在本机助手上试一遍，亲自看能做什么、局限在哪。  
4. **只摘低垂成熟的果实**：不引入失控、昂贵、难维护的重栈；尽量消除使用 AI 的门槛，而不是再添一道。  
5. **只做一件事——本地 AI：记得住、办得完**：一切围绕本机可跑通、持久记忆、可靠行动展开。欢迎联网与新技术，但把**数据留在本地**，且**本地也能完整跑通**。

---

## 4. 能力详述

### 4.1 多模型对话（Local First）

- 支持 **Ollama**（本地）、**OpenRouter**、**Cursor** 等；通过 `.env` 与 `LA_MODEL_PROVIDER_PRIORITY` 配置优先级
- `LA chat` / `/provider` 在 `auto | ollama | openrouter | cursor` 间切换
- `/model` 为当前路径选择模型并写入 `config/model_servers.yaml`，下次默认使用
- 模型不可用时按优先级自动降级，并在 REPL 中提示当前实际路径
- **原则**：算力默认本机，可扩展外部模型服务；模型与 LocalAgent 相互独立——小模型可跑通基本任务，更好的模型效果更好；会话、记忆与审计由 LocalAgent 本机持有

### 4.2 记忆模块（Memory Forever）

- **Hot**：`core_profile.json` — pinned 核心事实（姓名、偏好、长期目标等）/ 用户画像
- **Warm**：结构化长期记忆，优先 **Mem0**（Retain → 多路 Recall → Reflect → Consolidation）；可回退 JSON memory
- **Cold**：Chroma + BM25 — 个人文档原文（`data/kb/`），以及 ChatGPT / LA **对话归档**（摘要 + 轮次块）
- **Warm 输入**：ChatGPT 历史导出、LocalAgent 日常对话 → 事实提取（**Cold 先于 Warm**）
- **Cold 文档输入**：个人文档 → `LA rag`（不提取 Warm 记忆）
- 对话退出 / ChatGPT 导入：候选经 `value_filter` 后 → `pending_queue.json` → `LA memory pending` / `approve` / `reject`；`LA_MEMORY_APPROVAL_AUTO=1` 跳过确认门（CI/基准）；`LA ingest text` 仍直接写入
- **精确问双路径**（**默认关图 / 关 Neo4j**，章程：不引入重栈）：计数/聚合/可形式化多跳 → 可选 `LA_NEO4J=1` + Cypher；日常开放语义问 → Warm hybrid / Cold RAG。安装：`pip install 'la-localagent[neo4j]'` 仅在需要时。
- **Rerank（可选增强）**：Warm/Cold 混合召回后可经 cross-encoder 重排（`LA_MEMORY_RERANK=1`；`LA_MEMORY_RERANK_BACKEND=cross_encoder` 需 `pip install 'la-localagent[rerank]'`）；提升「personal / archive」类问题的 top-k 质量；默认 `auto` 有 extra 则启用
- **检索统一路径**：Agent 工具（`search_memory` / `search_knowledge`）与 JIT 预取共用 `RetrievalGateway`，避免双 pass 不一致（见 TDD §6-§7）
- **Profile Compile（下一周期）**：引擎可从 KB 简历等批量编译 Hot 画像（`memory/compile/`）；**本周期未暴露 CLI / ingest 自动触发**，待 `LA ingest compile` 或 ingest 联动产品化后再验收
- **原则**：换模型不换身份；该记的会记，不该记的不记（如 `is_do_not_remember`）；写入可审计、可撤销

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
| 有什么待办 | 托管待办队列（用户指定 / Agent 重大问题，须 rationale）；代码 TODO/checkbox 仅诊断不入队；并列 memory pending |

**已实现**：工作区根目录（`LA_WORKSPACE` / `LA chat --cwd`）、最近文件、Git 摘要（只读）、托管待办（`la workspace tasks/add/done/dismiss/snooze`，TTL/清理）、诊断扫描（`--todos-only` / `scan`，未入队）、`LA workspace`；`run_shell` / `write_file` 确认门；写文件幻觉检测；危险命令直接拦截。

**本周期补强**：

1. **操作回执（Action receipt）**：本轮若调用了副作用工具（`run_shell` / `write_file` 等），回合末给出结构化回执（做了什么、改了哪些路径、是否已确认）。复用 audit 事件轨迹。  
2. **会话内免重复确认（approve-once）**：用户对某次确认可选择「本会话相同模式不再问」；危险命令分类仍直接拦截，不可放行记忆化。  
3. **Daily Actions + 数据层表面**：打开 `la` 欢迎横幅展示今日信号与 **数据层高层次摘要**（Hot / Warm / Cold / Aware）；`la status` / 会话 `/status` 给出完整盘点（含新闻·总结收藏计数）并说明综合召回优先级（personal → archive → …；时间邻近加权）。

**下一周期**：Aware 扩展占位源（wechat / calendar / email）、与 `rag` 更紧协同、外部任务源、Hot Profile Compile CLI。（`apps` 已在 MVP 落地，见 §4.10a。）

用户输入**直接进入 Agent，不向用户做意图预检 / 澄清追问**（不先问「你是想 A 还是 B？」）。LA 内部仍有**执行路由**（显式 remember 短路、continue 续跑、复杂度判断 → milestone 或 ReAct），见 §4.11；这与「用户向不做预检」不矛盾。

1. **直接执行**：每轮用户输入经 Context Engine 预取后进入执行路径（§4.11）  
2. **执行前确认**：`run_shell` / `write_file` 按 `LA_TOOL_APPROVAL` 需用户确认；支持会话内免重复确认  
3. **幻觉检测**：模型声称已写入却未调用 `write_file` 时，重试或明确报错  
4. **工具结果校验**：副作用工具执行后程序化核对（及可选 LLM semantic）；失败驱动 ReAct 重试（§4.11）  
5. **失败重试**：联网结果不可用时先换查询再试  
6. **办完回执**：有副作用工具或多步里程碑时输出操作回执（含 ✓/○）

**可观测性（故事 17–18）**：用户输入后，L0 通过 `[chat] …` status 行感知关键节点——prefetch 命中、连接模型、工具调用（截断 preview）、等待确认、生成/综合、记忆写入；Turn 末操作回执确认副作用与里程碑 ✓/○。L1 verbose（`LA_TRACE=1` 或 `/trace on`，设计目标）展开 prefetch 路由、里程碑 i/N、validation warn/fail 摘要。`/status` 只展示 Daily Actions 与 Hot/Warm/Cold/Aware **库存**；查「刚才 Agent 做了什么」用 status 行 + 回执，进阶用 `/last-turn` 或 `la audit`（TDD §8）。

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

- `LA ingest doc` / `LA ingest kb`：软链 + 索引个人文档（`.txt` / `.md` / `.pdf` / `.xlsx` 等）
- 对话时 `search_knowledge` / `rag search` 检索知识库 Cold 层（文档 + 对话归档）
- 与 Warm 分离：文档不进事实提取常用路径

### 4.7 一键总结 / 文档对话（Actions · 快捷能力）

- `la summarize <path>`：支持 `.txt` / `.md` / `.pdf` / `.xlsx`（**不含图片**——图片请用 `la ocr`）；短文档优先；输出「最多三句话」+ 结构化要点（〔§章节 | p.页〕）；**TTY 下默认进入 `sum>` 文档对话**
- **扫描 PDF**：loader 检测文本层覆盖率不足 → 调用 `ingest/ocr.py`（RapidOCR）→ 再走 summarize
- `--no-chat`：仅速读（可多文件 / `--out`）；不进入对话
- **默认不入库**；会话内 `/keep` 或 `--keep` 收藏到 Cold 知识库；**禁止**每次总结后追问是否入库
- `--list` / `--resume` / `--id`：文档对话可离开再续
- 与 `la chat` 区分：chat = 和助手聊；summarize = 针对已打开文件的速读/深聊
- 与 `la ocr` / VL 区分：summarize = LLM 速读+深聊；OCR = 精确取字；VL = 图片语义描述（独立开关）
- 对话内工具：`summarize_document`（原子速读）

### 4.7a 本地 OCR（Actions · 快捷能力）

- `la ocr <path>`：图片（`.png` / `.jpg` / `.jpeg` / `.webp` / `.bmp` / `.tiff`）与 PDF 逐页 OCR → 纯文本（stdout 或 `--out`）
- 依赖：`pip install 'la-localagent[ocr]'`；`LA_OCR_ENABLED=1`（见 `env.example` 中 `LA_OCR_*`）
- 未安装 extra 或 OCR 关闭时：清晰报错，不静默失败
- **边界**：`la summarize` 拒绝图片；`la ingest doc` 仍可对图片/扫描 PDF OCR 入库；与 VL（`LA_VL_ENABLED`）独立——OCR 取字，VL 描述场景

### 4.8 一键润色（Actions · 快捷能力）

- `la polish` / `/polish`：独立 Agent 循环；识别邮件 / 朋友圈 / 简历 / 商务对话场景与态度后改写
- 输出 Taste Brief + 主推 + 两个备选 + 改动说明；**默认将主推写入系统剪贴板**（`--no-copy` 可关）
- 可选 `--scene` / `--tone`；注入 Hot 画像偏好（若有）；硬约束禁止编造数字/承诺（尤其简历）
- 与「一键总结」同属快捷能力；不进入 `run_shell` / 写文件工具循环

### 4.9 新闻嗅探（Actions · 快捷 + 定时）

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
| 快捷能力 | summarize · **ocr** · news · polish · aware | 不走漫长 Agent 工具循环，直接出结果；**OCR ≠ summarize ≠ VL** |
| Agent 工具循环 | `run_shell` / `write_file` / workspace / web_search + 可选 MCP | Context Engine JIT 预取；复杂度判断 milestone；ReAct + validation；执行前确认；会话内免重复确认；办完回执 |
| 定时 | `la news schedule` · `la aware schedule` | 本机定时准备，打开 LA 可见就绪信号 |

### 4.10a Aware——本机感知（Actions · 快捷 · opt-in）

按源授权后感知本机工作上下文；默认关闭。与 summarize/news/polish 同属快捷能力，但**采集面更大，隐私边界更硬**。

| 项 | 约定 |
|----|------|
| CLI | `la aware`（默认智能总结：当前状态 + 近 3h → `aware>`）；`--no-chat` / `--detail` / `--since`；子命令 `status` · `grant` · `ungrant` · `tick` · `schedule` · `suggestion` · `paths` · `events` |
| 已实现源 | `fs` · `git` · `terminal` · `browser` · `apps`（前台 / Now Playing / 按应用估算输入活跃；不记按键内容） |
| 占位源 | `wechat` · `calendar` · `email`（未实现） |
| Episode | tick 后会话化；相关问题可注入 `la chat`（默认近时窗） |
| Suggestion | 可索引文件 / 洞察进队列；**绝不自动写 Cold/`kb/`**；`approve` 仅白名单（`la ingest doc\|text` · `la summarize`）；insight/wellness 为 ack-only |
| 浏览器语义 | **selected ≠ viewing**：仅 OS 前台浏览器累计前台停留时长；后台选中不算「在看」 |
| 非目标 | 录屏、键内容捕获、自动任意 Shell、未授权采集 |

数据落 `data/aware/`。§0 有实现面摘要；验收见 §6.3。

### 4.11 Agent 执行架构（Actions · 用户向摘要）

Turn 级编排：Context Engine 组装上下文 → 内部执行路由 → ReAct 或 Milestone Planner → 校验与回执。技术细节见 [TDD.md](TDD.md) §6-§8。

**JIT 上下文预取（Context Engine）**

- 每轮 `LA chat` 经 `ContextEngine.build_turn_context`：regex（或可选 hybrid BM25）路由 → 按需预取模块 → 字符预算裁剪 → 组装 system prompt 与工具定义
- **预取模块**：`session`（近时/本场对话）· `archive`（历史归档硬窗）· `personal`（Warm+Cold 个人记忆）· `web`（联网摘要）· `workspace`（Git/最近文件/待办）· `aware`（近时 Episode）· `work`（进行中任务摘要）
- 预算：`LA_PREFETCH_BUDGET_CHARS`（默认 1500）；路由模式 `LA_PREFETCH_ROUTER=regex|hybrid`
- 用户 L0：命中模块时见 `[chat] …` prefetch status 行（故事 17）

**内部执行路由（不向用户追问）**

| 路径 | 触发 | 行为 |
|------|------|------|
| **remember 短路** | 「记住/record …」 | 直写 Warm（不经完整 tool loop） |
| **continue 续跑** | 「继续/下一步/continue」+ 未完成 plan | 恢复 `sessions/*.work.json` 中的 milestone plan |
| **action_milestone** | 复杂多步行动（复杂度 ≥ 阈值） | LLM 规划 2–4 个 milestone，逐步 ReAct 执行 |
| **action_simple / qa** | 简单行动或问答 | 单轮 ReAct 工具循环 |

配置：`LA_PLANNER_ENABLED=1`（默认开）；`LA_PLANNER_MODE=lazy|always|off`；`LA_PLANNER_COMPLEXITY_THRESHOLD` 等见 `env.example`。

**Milestone Planner（多步行动）**

- 复杂任务自动拆 2–4 有序 milestone；每步内嵌 ReAct；步末校验 `done_when`
- 失败可 replan（`LA_PLANNER_MAX_REPLAN`）；partial 时 receipt 显示 ✓/○；audit 记 `planner.*` 事件
- 可选 BM25 工具子集路由（`LA_PLANNER_TOOL_SUBSET`）缩小 milestone 模式 tool schema

**Session Work（跨 turn 续跑）**

- Turn 结束同步 `{session_id}.work.json`：活跃 milestone plan、最近触及文件路径
- 72h 内有效；下轮 prefetch 注入 ~200 字任务摘要（`work` 模块）
- 与故事 20、「继续」自然语言续跑对应

**ReAct 工具循环与工作记忆**

- 共享 `run_react_loop`：解析 tool 调用、空回复/格式错误/不完整回答/虚假写文件重试、重复调用熔断
- `ReactWorkingMemory` 累积 turn evidence；观测经 Observe 启发式压缩（`LA_OBSERVE_BUDGET_CHARS`）后回填 system prompt，避免多轮 tool 爆 context
- milestone 与简单路径共用同一 ReAct 内核

**工具结果校验（Validation）**

- 执行后程序化校验：`run_shell` · `write_file` · `edit_file` · `web_search` · `read_file` · `grep` · `glob`
- 可选 LLM semantic 二次判断；失败生成 follow-up 驱动重试；L1 verbose 见 validation 摘要（故事 18）
- 与 §4.4 幻觉检测并列：前者查「声称写入未调工具」，后者查「工具已执行但结果不对」

### 4.12 MCP 工具扩展（Local First · 可选增强）

LA 作为 **MCP client** 连接外部 tool server，已发现工具自动合并进 Agent 工具列表（与 builtin 并列）。

| 项 | 约定 |
|----|------|
| 依赖 | `pip install 'la-localagent[mcp]'` |
| 配置 | `config/mcp.yaml`（见 `mcp.yaml.example`）；`LA_MCP_CONFIG` 可覆盖路径；`LA_MCP_IMPORT_CURSOR=1` 可合并 Cursor `mcp.json` |
| CLI | `la mcp list` · `la mcp test <server>` · `la mcp tools [--server X]` · `la mcp serve`（LA 反向暴露为 MCP server） |
| 开关 | `LA_MCP_ENABLED=1`（默认开，有配置才连接）；`LA_MCP_MAX_TOOLS` 上限 |
| 原则 | **builtin 工具可完整跑通**；MCP 为增强，非前提；外部工具仍走确认门与 audit |
| 安全 | HTTP serve 需 `LA_MCP_SERVE_TOKEN`；副作用工具 preview 截断；见 TDD §4.2 MCP |

未安装 `[mcp]` extra 或未配置 server 时：纯本地路径不受影响；`la mcp list` 提示安装/配置。

---

## 5. 极简 CLI（按真实 client 分层）

普通用户几乎只在 **对话**里完成工作；下列命令按任务分层。会话内 `/memory add` 等与外层同名路径等价；`/add`、`/search` 仅为会话快捷方式（外层请写完整 `LA memory …`）。

### 5.1 常用路径（少即是多）

| 命令 | 作用 |
|------|------|
| `la` / `LA chat` | 对话 REPL；记忆/知识 JIT；联网按需；Daily Actions + 数据层摘要 |
| `la setup` | 引导安装 Ollama / 拉取默认模型（`-y` 免确认） |
| `la config` / `la config-example` | 纯本地或自有 API 配置 |
| `la status` / `/status` | Daily Actions + 数据层（Hot/Warm/Cold/Aware）+ 综合召回说明 |

### 5.2 日常能力（用户故事对应）

| 我想… | 命令 |
|------|------|
| 记住一句话 | `LA ingest text "..."`；或 chat 内「记住 xxx」（§4.11 短路） |
| 接着上次未完成任务 | chat 内「继续/下一步/continue」（§4.11 session work） |
| 搜我记得的事 | `LA memory search <query>` |
| 审阅待写入记忆 | `LA memory pending` → `approve` / `reject` |
| 导入 ChatGPT | `LA ingest chatgpt <path>` |
| 把文档放进知识库 | `LA ingest doc <path>` → `LA rag search <query>` |
| OCR 取字（截图/扫描件原文） | `la ocr <path>`；`--out` / `--json`；需 `[ocr]` extra |
| 一键总结文档（默认文档对话，不入库） | `la summarize <path>` → `sum>`（`.txt/.md/.pdf/.xlsx`，不含图片）；长期召回：`--keep` / `/keep`；仅速读：`--no-chat` |
| 新闻嗅探 / 今日简报 | `la news sync` → `la news brief`（TTY 交互）；`r` 精读深聊；`la news schedule on` |
| 一键润色文案（默认复制主推） | `la polish "草稿"` / `/polish`；`--scene` · `--tone` · `--no-copy` |
| 授权后感知本机 | `la aware` · `grant` · `tick` · `suggestion`（不自动写 Cold/`kb/`） |
| 看今日信号与数据层 | `la status` / `/status` |
| 看花费与安全 | `LA audit` / `--report out.md` |
| 删一条记忆 | `LA memory forget <id>` |

会话内还可：`/provider` · `/model` · `/deepsearch <主题>` · `/polish <草稿>`（联网默认 ddgs，见 §4.3）。

### 5.3 运维与实验（默认不教日常用户）

| 命令 | 作用 |
|------|------|
| `LA ingest chat [--force]` | 从 LA 对话补提取（Cold 先于 Warm） |
| `LA ingest all [--force]` | 依次消费 chat / chatgpt 等 |
| `LA memory query …` | 按标签/时间浏览（高级；日常用 search） |
| `LA memory reflect <query>` | 跨记忆+知识库归纳 |
| `LA memory status` / `reindex` / `reset` | 诊断 / 重建索引 / 按来源清空 |
| `LA memory graph …` | 关系图 / Neo4j（默认关闭） |
| `LA ingest kb` / `rebuild` / `reset` | 扫描 kb、重建 Cold；或按源清空 |
| `LA rag reset` / `search` | Cold 运维与检索（写入请用 ingest） |
| `LA tasks` | 后台索引任务 |
| `LA workspace` / `LA logs` / `LA websearch` | 工作区快照、诊断日志、直连联网 |
| `LA mcp list` / `test` / `tools` / `serve` | MCP server 管理与 LA 反向 serve（§4.12；需 `[mcp]` extra） |
| `LA news skim` / `read` / `mark` … | 新闻速读/精读/标记等（日常常用路径见 `brief`） |

**相关环境变量（运维）**：`LA_PREFETCH_*` · `LA_PLANNER_*` · `LA_MCP_*` · `LA_MEMORY_RERANK_*` · `LA_OBSERVE_BUDGET_CHARS` — 见 `env.example` / `src/localagent/resources/env.example`。

### 5.4 记忆与知识库输入

| 来源 | 入口 | 写入路径 | 流程 |
|------|------|----------|------|
| 个人文件 | `LA ingest doc` / `LA ingest kb` | `data/kb/` → Cold（长文可 Warm 摘要） | 原文分块索引；可提取则记忆化 |
| LocalAgent 对话 | `LA chat` 退出 / `LA ingest chat` | `data/conversations/` | **先 Cold** → 再 Warm 事实提取 |
| **ChatGPT 导出** | `LA ingest chatgpt` | `data/chatGPTdata/`（归档） | **先 Cold** → 再 Warm 事实提取 |
| 单条文本 | `LA ingest text` | `data/ingest_notes/` | Cold 单块 + Warm 直写 + Hot pin |

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
- CLI help / 官网 / README 主标为一句话，三板斧为次标拆分；旧主权 slogan 不再作主标

### 6.2 Memory Forever（故事 4–6）

- Hot 画像 / Warm 事实跨会话可召回；价值过滤与 pending 确认门可用
- `ingest chatgpt` / `chat`：**Cold 先于 Warm**；`no_facts` 时仍有 `cold_chunks>0` 且 `rag search` 可命中
- 跳过 `is_do_not_remember: true`；同一 `conversation_id` 默认不重复（除非 `--force`）
- `ingest doc` 软链存在 + RAG 已写入 + sync_index 有记录（短文档可不写 Warm）
- `chat` 对话持久化到 `data/conversations/`
- **Rerank（可选）**：安装 `[rerank]` 且 `LA_MEMORY_RERANK_BACKEND=cross_encoder` 时，Warm/Cold 召回候选经 cross-encoder 重排；未安装 extra 时 graceful 回退 hybrid 排序

### 6.3 Actions Automated（故事 7–22 · 含 13b Aware · §4.11-§4.12）

- 联网搜索与 `/deepsearch` **默认 ddgs 可用**（无需 Tavily）；Tavily / SearXNG 为可选增强
- 用户输入直接进入 Agent，**不向用户做意图预检追问**；内部执行路由见 §4.11
- `run_shell` / `write_file` 按审批策略确认后执行；危险命令直接拦截
- 模型声称已写入却未调用 `write_file` 时，重试或明确报错
- `LA workspace`：最近文件、Git 摘要、托管待办生命周期可用；代码 TODO 扫描为诊断（未入队）
- **本地 OCR（故事 10b）**：`la ocr <path>` 输出可复制原文；未装 `[ocr]` 或 `LA_OCR_ENABLED=0` 时有清晰错误；图片不走 summarize
- **一键总结**：`la summarize <path>` 支持 `.txt/.md/.pdf/.xlsx`（不含图片）；扫描 PDF 内嵌 OCR；输出 1～3 句 + 〔§/p.〕要点；TTY 默认进 `sum>`；默认不写 kb；`--keep` / `/keep` 后可检索；不追问入库
- **新闻嗅探**：`la news sync` 拉取 BestBlogs RSS；TTY 下 `la news brief` 可 ↑↓ 浏览、`o` 打开浏览器、`r` 精读深聊；`schedule on/off` 控制早 8 点自动 sync；入 chat 可提示就绪
- **一键润色**：`la polish` / `/polish` 输出识别 Brief + 主推/备选；默认主推进剪贴板；`--no-copy` 可关；简历场景不编造原文没有的数字
- **Aware（故事 13b）**：未 `grant` 前不采集；`grant` → `tick` 产生 Episode / suggestion；可索引文件**不**自动写 Cold/`kb/`；`approve` 仅白名单（`ingest doc|text` / `summarize`）；`la aware` 可出智能总结；相关 `la chat` 可注入近时 Episode；浏览器 selected ≠ viewing
- **操作回执**：本轮有副作用工具调用时，输出含工具名/路径或命令摘要的回执
- **会话内免重复确认**：用户选择后，同会话同类安全操作不再交互确认；危险命令仍直接拦截
- **Daily Actions + 数据层**：欢迎横幅可见今日信号与 Hot/Warm/Cold/Aware 高净值；`la status` / `/status` 含完整数据层盘点与召回优先级说明；托管待办可 `done`/`dismiss`/`snooze`
- **可观测性（故事 17–18）**：L0 默认 Turn 内有 status 行（prefetch / 工具 / 审批 / 生成等）；有副作用时操作回执含工具与路径摘要；L1 verbose 可展开 prefetch 命中与 validation 摘要（`LA_TRACE=1` / `/trace`，设计目标）；`/status` 不混入 turn trace
- **Milestone Planner（故事 19）**：复杂多步行动回执含 milestone ✓/○；partial 未完成时 plan 写入 session work；audit 有 `planner.*` 事件
- **Session Work 续跑（故事 20）**：同 session 说「继续/下一步」可恢复 72h 内未完成 milestone plan；prefetch 注入 work 摘要
- **MCP（故事 21）**：配置 `mcp.yaml` 后 `la mcp list` 可见 server；chat 可调用外部 MCP 工具；builtin 未配置 MCP 时仍可完整跑通；audit 记录 tool 决策
- **Remember 快捷（故事 22）**：chat 内「记住 xxx」直写记忆，不进入完整 ReAct tool loop
- 模型调用记录 provider、模型、估算 token 与费用到本地 audit 日志
- `LA audit --report` 生成含花费、token、安全扫描结果的 Markdown 报告

**下一周期**：工作区 watcher 增量索引、外部任务源；Aware 占位源（wechat / calendar / email）；新闻 OpenAPI / 个人 OPML（MVP 仅 BestBlogs RSS）；完全无人值守定时 Shell；Hot Profile Compile CLI（`LA ingest compile`）。`LA audit --report *.html` 已支持。
