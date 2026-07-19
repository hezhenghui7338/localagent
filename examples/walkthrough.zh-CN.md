# LocalAgent 功能示例

> **栖居在你电脑里的 AI。** — **本地优先，真记得你，把事办完。**

本文档用短路径场景做上手（按 Local → Memory → Actions）。完整用户故事见 [product-tour.zh-CN.md](product-tour.zh-CN.md)（英文：[product-tour.md](product-tour.md)）。英文短路径：[walkthrough.md](walkthrough.md)。示例数据均为虚构内容，可安全复现。

**前置条件：**

```bash
# 1. 一键安装 LocalAgent（全局 la 命令）
pipx install "git+https://github.com/hezhenghui7338/localagent.git"
# 或源码开发：pip install -e ".[dev]"

# 2. 首次 la / la setup 会询问是否安装 Ollama，并按内存拉取合适模型（可答 n 跳过）
la setup
# 或无需确认：la setup -y

# 3. 使用纯本地配置（可选）
# 普通安装：编辑 ~/.localagent/.env 或：
#   la config --provider ollama --base_url "http://localhost:11434" --model qwen3.5:4b
# 源码开发：cp examples/env.local-only.example .env
```

---

## 亮点：Local First

LocalAgent 的核心链路——**对话、记忆写入、记忆召回、文档检索、工作区感知、审计统计**——均可只依赖本地 Ollama，无需任何付费 API。打开时可 `la status` / `/status` 查看今日信号与数据层（Hot/Warm/Cold/Aware）。

| 能力 | 是否需要联网 API | 说明 |
|------|------------------|------|
| 对话 `LA chat` | 否 | 默认 `qwen3.5:4b`，本机可跑 |
| 单条记忆 `LA ingest text` | 否 | 本地模型提取标题/标签 |
| 文件导入 `LA ingest doc` | 否 | 默认启发式提取，不调用 LLM |
| 记忆/知识检索 `LA memory search` | 否 | BM25 + Chroma 本地检索 |
| 工作区 `LA workspace` | 否 | 读本地 Git / 文件 / TODO |
| 本机感知 `la aware` | 否（本地模型可选） | 默认：当前状态 + 近 3 小时动态；`--detail` 分源明细 |
| 审计 `LA audit` | 否 | 读本地 usage.jsonl |
| 一键总结 `la summarize` | 否（本地模型） | 速读卡 + `sum>` 文档对话 |
| 新闻嗅探 `la news` | 仅 sync 时需联网 | RSS → 简报；精读可本地总结 |
| 一键润色 `la polish` | 否（本地模型） | 场景改写 + 剪贴板 |
| 联网搜索 | 否（默认 ddgs） | 开箱可用；可选 Tavily / 自托管 SearXNG |

**本周期尚未做**：工作区 watcher 增量索引、外部任务源。

```bash
# 强制纯本地对话，不会降级到 OpenRouter
LA chat --provider ollama
```

---

## 示例 1：按单条增加记忆，演示召回

适合记录一句话事实——决定、偏好、计划等。

```bash
# 写入一条记忆
LA ingest text "2026年7月决定为 LocalAgent 补充 examples 目录，方便新用户快速上手"

# 召回验证
LA memory search "examples 目录"
```

**预期输出（召回）：**

```text
[search] 检索记忆: examples 目录
找到 1 条相关记忆（查询: examples 目录）

### 1. 补充 examples 目录
相关度 0.82 · 2026-07-11 · 事实 · #文档/LocalAgent

2026年7月决定为 LocalAgent 补充 examples 目录，方便新用户快速上手

来源: LA ingest text · id: a1b2c3d4
→ LA memory forget <id>  删除某条记忆
```

在 `LA chat` 中也可以自然提问，Agent 会按需 JIT 召回这条记忆：

```text
你> 我之前关于 examples 做了什么决定？
助手> 你在 2026 年 7 月决定为 LocalAgent 补充 examples 目录，方便新用户快速上手。
```

---

## 示例 2：按 Markdown 文件导入知识库，演示召回

适合导入项目笔记、日记、技术方案等长文档。文件会软链到 `data/kb/`，**仅**写入知识库（Cold 层），不提取 Warm 记忆。

```bash
# 导入示例文档（仓库自带）
LA ingest doc examples/sample-project-notes.md

# 从知识库召回原文片段（Cold 层）
LA rag search "三层记忆架构"
```

**预期输出（ingest doc）：**

```text
[ingest doc] source=doc · cold=5 · warm=0 · files=1
[ingest doc] archived: data/kb/sample-project-notes.md
```

**预期输出（知识库检索）：**

```text
[rag search] 检索知识库: 三层记忆架构
--- 结果 1 (score=0.91) ---
来源: sample-project-notes.md · 架构决策
LocalAgent 采用 Hot / Warm / Cold 三层记忆架构：
- Hot：core_profile.json 存放核心画像
- Warm：JSON memory 存放长期事实
- Cold：Chroma + BM25 混合检索
```

---

## 示例 3：联网搜索，查询最近新闻

> **默认无需 API Key**：未配置时自动使用开源 `ddgs`。若已配置 `TAVILY_API_KEY`，`auto` 模式会优先走 Tavily（结果通常更稳）；也可自托管 SearXNG 并设置 `LA_SEARXNG_URL`。

可选增强（非必须）：

```bash
# 更高质量（可选）
TAVILY_API_KEY=tvly-xxx

# 或强制免费后端 / 自托管
# LA_WEB_SEARCH_PROVIDER=ddgs
# LA_SEARXNG_URL=http://localhost:8080
```

**方式 A：对话中自然提问**（Agent 自动调用 `web_search`）

```bash
LA chat --provider ollama
```

```text
你> 最近一周 AI 领域有什么重要新闻？简要列 3 条。
助手> [调用 web_search → 汇总结果]
      1. ...
      2. ...
      3. ...
```

**方式 B：深度研究**

```text
你> /deepsearch 2026年7月 大模型开源动态
助手> [多轮搜索 + 本地模型归纳，输出结构化报告]
```

联网结果进入当轮上下文回答，**不会自动写入长期记忆**。

---

## 示例 4：本地模型，本机就能跑

未配置模型时，`la setup` 会按系统内存推荐（可用 `OLLAMA_MODEL` 覆盖）。推荐配置（已包含在 `examples/env.local-only.example`）：

```bash
OLLAMA_MODEL=qwen3.5:4b           # 或 la setup 推荐的型号
OLLAMA_THINK=0                    # 关闭 thinking，避免等数分钟
LA_MODEL_PROVIDER_PRIORITY=ollama # 不降级到云端
```

**内存 → 推荐模型**（`la setup` 在无配置时使用）：

| 系统内存 | 模型 | 说明 |
|------|------|------|
| &lt; 6 GB | `qwen3.5:0.8b`（Mini） | 基础对话；多工具 Agent 较弱 |
| 6–10 GB | `qwen3.5:2b` | 轻量问答 |
| 10–18 GB | `qwen3.5:4b` | 主推质量档 |
| ≥ 18 GB | `qwen3.5:9b` | 高配质量档 |

```bash
# 确认本地模型可用
ollama run qwen3.5:4b "你好，一句话介绍你自己"

# 启动纯本地对话
LA chat --provider ollama
```

---

## 示例 5：回答本地工作内容

LocalAgent 感知当前工作区——最近修改的文件、Git 状态、TODO 注释——无需把代码上传到云端。

```bash
# 以 LocalAgent 仓库为工作区
LA workspace --cwd .

# 或在对话中指定工作区
LA chat --cwd . --provider ollama
```

本机感知（`la aware`）见 [§7](#7-日常旁路总结--新闻--润色--aware)。

**预期输出（workspace）：**

```text
工作区: /Users/you/code/localagent
最近 7 天修改的文件:
  - 2026-07-11 17:40  README.md
  - 2026-07-11 17:37  examples/walkthrough.md
  - 2026-07-11 16:20  src/localagent/cli.py

Git 分支: main
工作区: 干净（无未提交变更）

待办项 (2 条，显示前 10):
  - [checkbox] examples/sample-project-notes.md:28  补充 examples 目录
  - [todo] examples/sample-project-notes.md:29  支持更多文档格式导入
```

**在 chat 中提问：**

```text
你> 我最近在这个项目里改了什么？有什么待办？
助手> [调用 workspace_context 工具]
      最近 7 天你修改了 README.md、examples/walkthrough.md 等文件；
      Git 工作区干净，在 main 分支。
      待办有 2 条：补充 examples 目录、支持更多文档格式导入。
```

---

## 示例 6：汇总审计报告（Ollama 完全免费）

每次模型调用自动记入 `data/audit/usage.jsonl`。Ollama 本地调用的估算费用恒为 **$0**。

```bash
# 交互式摘要
LA audit --since 7d

# 导出完整 Markdown 报告
LA audit --since 7d --report examples/my-audit.md
```

**预期输出（交互式摘要）：**

```text
[audit] 摘要（7d）
  调用: 47  Token: 31,280  估算费用: $0.0200
    ollama: 42 次, 28,450 tokens, $0.0000
    tavily: 5 次, 0 tokens, $0.0500

文件安全: 未发现高风险项
记忆健康: facts=12

工作区（摘要）:
  工作区: /Users/you/code/localagent
  ...

→ LA audit --report report.md  导出完整报告
```

完整报告样例见 [audit-report-sample.md](audit-report-sample.md)。

**费用解读：**

- `ollama` 行：**$0.0000** — 42 次对话与记忆操作全部本地完成，零成本
- `tavily` / `ddgs` / `searxng` 行：联网搜索；ddgs/searxng 费用为 0，仅 Tavily 计费

---

## 7. 日常旁路：总结 · 新闻 · 润色 · Aware

### 一键总结

```bash
la summarize examples/sample-project-notes.md
# sum> 这份笔记的核心决策是什么？
# sum> /exit
```

### 新闻嗅探

```bash
la news sync
la news brief --no-ui --limit 5    # 脚本/管道用 --no-ui；TTY 下可去掉看交互浏览器
```

### 一键润色

```bash
la polish --no-copy --scene email "您好，上次说的方案这周能给一下吗？"
```

### Aware（本机感知，需授权）

按源 `grant` 后才采集。**绝不自动写入 Cold / `kb/`**——可索引文件只进 suggestion。

Aware 是可关闭的**本机事实层**（不是全知副脑）：`tick` 只做 Collect→Reduce（events / episodes / `context/hot.json`+`diff.json`），LLM 摘要与对话注入属于 Reason，仅在你主动问时跑。回答锚定事实卡；缺字段答「未观测到」，不瞎猜。

```bash
la aware status
la aware grant fs terminal browser apps -y
la aware tick --no-chat
la aware suggestion
la aware --no-chat                 # 智能总结；TTY 去掉 --no-chat → aware>
```

**预期：** 当前状态 + 近时动态摘要；suggestion 为空也正常。不想开感知可跳过 grant。
---

## 一键演示脚本（可选）

以下命令使用隔离数据目录，不污染你的 `data/`：

```bash
export LA_DATA_DIR=/tmp/la-demo
pip install -e ".[dev]" -q

LA ingest text "2026年7月决定为 LocalAgent 补充 examples 目录"
LA memory search "examples"
LA ingest doc examples/sample-project-notes.md
LA rag search "三层记忆"
LA workspace --cwd .
la aware --no-chat                 # 可选；未 grant+tick 前可能为空
LA audit --since 7d

echo "演示完成，数据在 $LA_DATA_DIR"
```

---

## 下一步

- 导入自己的 Markdown：`LA ingest doc ~/Documents/notes.md`
- 导入 ChatGPT 历史：`LA ingest chatgpt conversations.json`
- 阅读架构文档：[docs/PRD.md](../docs/PRD.md) · [docs/TDD.md](../docs/TDD.md)
