# LocalAgent 产品体验教程

> **定位**：**Local First. Memory Forever. Actions Automated.**  
> **一句话**：本地 AI：记得住你，也能把事办完。  
> **目标**：用一条连贯的「虚构用户」故事，在约 **30 分钟**内亲手跑通三幕核心体验（对照 [PRD §2](../docs/PRD.md)）。  
> 每一步都给出**完整输入**与**预期输出**（示例数据均为虚构，可安全复现）。  
> 命令入口：`la` / `LA`（等价）。更短的上手见 [walkthrough.zh-CN.md](walkthrough.zh-CN.md)。  
> [English](product-tour.md)

---

## 你将体会到什么（三幕）

| 幕 | 支柱 | 你会体验到 | 本节 |
|----|------|------------|------|
| **I** | **Local First** | 一键装好、纯本地或自有 API | [§1](#1-一键安装与-hello用户--开发者) · [§2](#2-纯本地与自有-api-双路径) |
| **II** | **Memory Forever** | 跨会话记住、ChatGPT 导入、RAG 深召回 | [§3](#3-跨会话记忆--hot--warm--cold) · [§4](#4-chatgpt-导入加速认识你) · [§5](#5-本地文档-rag-深度召回) |
| **III** | **Actions Automated** | 联网、动手改文件、日常三剑客、审计与今日信号 | [§6](#6-联网搜索--小模型也能用好网络)–[§12](#12-一键润色故事-6d)；另试 `la status` |

**叙事设定（虚构）**：你是「林晓」，在本机上用 LocalAgent 做个人 AI；偏好美式咖啡；2026-05 在深圳开会定了产品路线；2026-07 决定用 Mem0 做记忆引擎。

**建议**：用隔离数据目录，不污染日常数据：

```bash
export LA_DATA_DIR=/tmp/la-product-tour
```

下文凡出现 `data/`，在隔离模式下即指 `$LA_DATA_DIR/`。

---

## 1. 一键安装与 Hello（用户 / 开发者）

### 1.1 用户安装（一键）

**输入：**

```bash
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.4.0"
la --version
```

**预期输出：**

```text
la-localagent 0.4.0
```

### 1.2 开发者安装

```bash
git clone git@github.com:hezhenghui7338/localagent.git
cd LocalAgent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
# 或：uv sync --extra dev
la --version
```

源码 checkout 时配置与数据在仓库内（`.env`、`data/`）；与用户安装的 `~/.localagent/` 互不干扰。配置与 Hello 见下一节。

---

## 2. 纯本地与自有 API 双路径

纯本地（零账单）只需 Ollama；要用自己注册的 OpenRouter / Cursor / Tavily Key，写入配置即可——**身份与记忆仍留本机**。

### 2.1 按 example 配置

**方式 A（推荐，JSON 模板）：**

```bash
la config-example > /tmp/la-hello.json
# 编辑后加载（最小可用：本地 Ollama）
cat > /tmp/la-hello.json <<'EOF'
{
  "provider": "ollama",
  "base_url": "http://localhost:11434",
  "model": "qwen3.5:4b",
  "api_key": "",
  "TAVILY_API_KEY": "",
  "LA_WEB_SEARCH_PROVIDER": "auto",
  "LA_SEARXNG_URL": "",
  "OPENROUTER_API_KEY": "",
  "CURSOR_API_KEY": "",
  "OPENAI_API_KEY": ""
}
EOF
la config /tmp/la-hello.json
la config list
```

**方式 B（一行参数）：**

```bash
la config --provider ollama \
  --base_url "http://localhost:11434" \
  --model qwen3.5:4b
```

**预期输出（节选）：**

```text
[config] 已加载 /tmp/la-hello.json
provider: ollama
base_url: http://localhost:11434
model: qwen3.5:4b
```

### 2.2 准备本地模型（首次）

```bash
la setup -y
# 或手动：ollama pull qwen3.5:4b
```

### 2.3 Hello World

**输入：**

```bash
la chat --provider ollama
```

进入对话后：

```text
你> 用一句话介绍你自己，并说明你的数据存在哪里。
```

**预期输出（示意）：**

```text
LocalAgent v0.4.0 …
│ qwen3.5:4b · ollama …
> 用一句话介绍你自己，并说明你的数据存在哪里。
[chat] 思考中…
[chat] 连接模型 (ollama)…
[chat] 生成回复…
我是跑在你本机上的 LocalAgent：对话、记忆与审计默认都落在本机数据目录
（如 ~/.localagent/ 或你设置的 LA_DATA_DIR），不会把身份数据上传到云端。
[via ollama/qwen3.5:4b]
```

输入 `/q` 退出。若能看到欢迎屏与回复，**安装链路已跑通**。

---

## 3. 跨会话记忆 → Hot / Warm / Cold

核心承诺：**换会话、换模型，不换「我是谁」**。三层分工：

| 层 | 存什么 | 典型位置 / 命令 |
|----|--------|-----------------|
| **Hot** | 核心画像与状态（姓名、偏好、长期目标） | `data/core_profile.json` |
| **Warm** | 结构化长期事实（Mem0 / JSON） | `LA memory add` / 对话提取 / `LA memory search` |
| **Cold** | 文档原文片段（语义 + BM25） | `LA rag add` → `LA rag search` |

### 3.1 写入 Warm：手动一条事实

**输入：**

```bash
LA memory add "我叫林晓，日常偏好喝美式咖啡，不喜欢拿铁"
LA memory add "2026年5月，我在深圳开会讨论产品路线，结论是优先做本地个人 AI 助手"
```

**预期输出（示意）：**

```text
[add] 已写入记忆: 我叫林晓，日常偏好喝美式咖啡，不喜欢拿铁
  id: a1b2c3d4 · 标题: 个人偏好 · 标签: #偏好/饮品
[add] 已写入记忆: 2026年5月，我在深圳开会讨论产品路线…
  id: e5f6g7h8 · 标题: 深圳产品路线会议 · 标签: #决策/产品
```

### 3.2 写入 Cold：导入文档

**输入：**

```bash
LA rag add examples/sample-project-notes.md
LA rag search "三层记忆架构"
```

**预期输出（rag add）：**

```text
[rag add] 源文件: …/examples/sample-project-notes.md (1.1 KB)
[rag add] 软链: data/kb/sample-project-notes.md
  ✓ sample-project-notes.md: chunks=5
[rag add] done
```

**预期输出（Cold 检索）：**

```text
[search] 检索知识库: 三层记忆架构
--- 结果 1 (score=0.91) ---
来源: sample-project-notes.md · 架构决策
LocalAgent 采用 Hot / Warm / Cold 三层记忆架构：
- Hot：core_profile.json 存放核心画像
- Warm：JSON memory 存放长期事实
- Cold：Chroma + BM25 混合检索
```

### 3.3 Warm 召回

**输入：**

```bash
LA memory search "我喜欢喝什么"
```

**预期输出（示意）：**

```text
[search] 检索记忆: 我喜欢喝什么
找到 1 条相关记忆（查询: 我喜欢喝什么）

### 1. 个人偏好
相关度 0.88 · 2026-07-14 · 偏好 · #偏好/饮品

我叫林晓，日常偏好喝美式咖啡，不喜欢拿铁

来源: LA memory add · id: a1b2c3d4
→ LA memory forget <id>  删除某条记忆
```

### 3.4 跨会话验证（关键）

**会话 A — 写入更多上下文后退出：**

```bash
la chat --provider ollama --session-id tour-a
```

```text
你> 记住：我下周要给团队演示 LocalAgent 的记忆分层。
助手> 好的，已记下你下周要演示记忆分层这件事。
你> /q
```

**会话 B — 全新 session，问同样的人：**

```bash
la chat --provider ollama --session-id tour-b
```

```text
你> 我叫什么？喜欢喝什么？5 月在深圳开过什么会？
```

**预期输出（示意）：**

```text
[chat] 思考中…
[chat] 调用 搜索记忆…
你叫林晓，喜欢美式咖啡（不喜欢拿铁）。
2026 年 5 月你在深圳开会讨论产品路线，结论是优先做本地个人 AI 助手。
[via ollama/qwen3.5:4b]
```

> **对比点**：普通 Chat 客户端换会话就「失忆」；LocalAgent 从 Warm/Hot 召回，**不依赖当前会话上下文**。

### 3.5 一眼看清三层

```bash
# Hot
cat "${LA_DATA_DIR:-data}/core_profile.json" 2>/dev/null || echo "(画像随对话/导入逐步 enrich)"

# Warm
LA memory search "林晓" --top-k 3

# Cold
LA rag search "qwen3.5:4b" --top-k 2
```

---

## 4. ChatGPT 导入加速认识你

从 ChatGPT **Settings → Data Controls → Export** 拿到 `conversations.json` 后导入，Cold 归档 + Warm 事实提取并行，让 LA 更快认识你。

默认 `LA_MEMORY_APPROVAL_REQUIRED=1`：非交互导入会把候选写入 `pending_queue.json`，需：

```bash
LA memory pending
LA memory approve --all   # 或 reject
```

演示若要立即写入 Warm，可临时：`export LA_MEMORY_APPROVAL_AUTO=1`。

### 4.1 ChatGPT 格式导入

准备一份导出 JSON（OpenAI「导出数据」中的 `conversations.json`），或用最小样例：

```bash
cat > /tmp/chatgpt-sample.json <<'EOF'
[
  {
    "conversation_id": "demo-1",
    "title": "个人偏好",
    "create_time": 1757058223.0,
    "update_time": 1757058263.0,
    "current_node": "a",
    "mapping": {
      "r": {"id": "r", "parent": null, "message": null},
      "u": {
        "id": "u", "parent": "r",
        "message": {
          "author": {"role": "user"},
          "content": {"content_type": "text", "parts": ["我平时用 Python 做数据分析，编辑器偏好 VS Code"]},
          "create_time": 1757058223.1
        }
      },
      "a": {
        "id": "a", "parent": "u",
        "message": {
          "author": {"role": "assistant"},
          "content": {"content_type": "text", "parts": ["已了解。"]},
          "create_time": 1757058223.2
        }
      }
    }
  }
]
EOF

LA memory ingest chatgpt /tmp/chatgpt-sample.json
LA memory search "VS Code"
```

**预期输出（示意）：**

```text
[import-chatgpt] 解析 1 个对话 …
[import-chatgpt] 提取候选记忆 …
[import-chatgpt] done · conversations=1 · memories+=1
…
[search] 检索记忆: VS Code
### 1. …
我平时用 Python 做数据分析，编辑器偏好 VS Code
来源: import-chatgpt · …
```

### 4.2 对话中自动识别（体验）

```bash
la chat --session-id tour-auto --provider ollama
```

```text
你> 对了，我的长期目标是把 LocalAgent 做成真正懂我的本地个人 AI 助手。
助手> …（正常对话）
你> /q
```

之后：

```bash
LA memory search "长期目标"
```

应能召回相关事实（具体文案取决于提取管线；可用 `LA memory ingest chat --session tour-auto` 补提取）。

---

## 5. 本地文档 RAG 深度召回

个人文档进 Cold 知识库（**不**提取 Warm 事实）；对话时用 `rag search` / `search_knowledge` 深度召回。

### 5.1 文档知识库索引

```bash
LA rag add examples/sample-project-notes.md
# 若已把多份笔记软链到 kb/：
LA rag ingest
```

**预期输出（rag ingest 示意）：**

```text
[rag ingest] 扫描 data/kb/ …
  ✓ sample-project-notes.md: chunks=5 (unchanged, skip)
[rag ingest] done · indexed=0 · skipped=1
```

加 `--force` 可强制重建索引。

> §3 已演示过一次 `rag add` + `rag search`；此处强调可对 `data/kb/` 批量 `rag ingest`。

---

## 6. 联网搜索 → 小模型也能用好网络

默认 **无需 API Key**（`ddgs`）；小模型负责「决定何时搜、如何归纳」，网络提供事实。

**输入：**

```bash
la chat --provider ollama
```

```text
你> 今天北京天气怎么样？用一两句话告诉我，并注明信息来自网络。
```

**预期输出（示意）：**

```text
[chat] 思考中…
[chat] 连接模型 (ollama)…
[chat] 生成回复…
[chat] 调用 联网搜索: 北京 今天 天气
[chat] 综合工具结果 (第 2 轮)…
根据刚才的网络检索：今天北京……（温度/天气状况）。以上信息来自实时搜索，仅供参考。
[via ollama/qwen3.5:4b]
```

**深度研究（可选）：**

```text
你> /deepsearch 2026年大模型开源动态 简要三点
助手> [多轮搜索 + 本地模型归纳 → 结构化要点]
```

可选增强（非必须）：在 config 中填入 `TAVILY_API_KEY`，`auto` 模式会优先用 Tavily。

> **对比点**：即使用 `qwen3.5:4b` 这种小模型，也能通过工具调用链接网络，而不是胡编实时信息。

---

## 7. 本地工具 → 危险命令拦截

Agent 可真正执行本机命令 / 写文件；**默认每次需你确认**；危险命令额外警告；极端命令直接拦截。

### 7.1 安全的只读命令（仍需确认）

**输入：**

```bash
la chat --cwd . --provider ollama
```

```text
你> 统计一下当前项目里 Python 文件大约有多少行（用 shell）
```

**预期输出：**

```text
[chat] 思考中…
[chat] 调用 执行命令: find . -type f -name "*.py" …
[chat] 等待用户确认操作…
⚠ Agent 请求执行命令，需你确认后才会执行。
命令: find . -type f -name "*.py" -not -path "*/.*" | xargs wc -l | tail -1
是否允许执行？ [y/N] y
[chat] 综合工具结果 (第 2 轮)…
当前项目 Python 代码合计约 N 行。
[via ollama/qwen3.5:4b]
```

输入 `n` 则会拒绝执行，Agent 不会偷偷跑命令。

### 7.2 危险命令：额外警告

**输入：**

```text
你> 帮我删掉工作区里的临时目录 tmp-demo（用 rm -rf）
```

**预期输出：**

```text
[chat] 调用 执行命令: rm -rf ./tmp-demo
[chat] 等待用户确认操作…
⚠ Agent 请求执行命令，需你确认后才会执行。
风险: 删除文件/目录
命令: rm -rf ./tmp-demo
⚠ 这是潜在危险操作，确定要执行吗？ [y/N]
```

### 7.3 硬拦截（不会执行、也不该确认通过）

例如尝试删除根目录类命令时，策略会 **blocked**，直接拒绝：

```text
错误: 禁止删除根目录。
```

### 7.4 写文件同样需确认

**输入（在意图已清晰的前提下）：**

```text
你> 在工作区根目录创建 hello-tour.txt，内容写一行：LocalAgent 产品体验
```

**预期输出（节选）：**

```text
[chat] 调用 写入文件…
⚠ Agent 请求写入文件，需你确认后才会执行。
风险: 覆盖写入本地文件
目标: hello-tour.txt (覆盖写入, … 字符)
预览: LocalAgent 产品体验
⚠ 这是潜在危险操作，确定要执行吗？ [y/N] y
已写入 hello-tour.txt。
```

策略开关（默认 `always`）：

| `LA_TOOL_APPROVAL` | 行为 |
|--------------------|------|
| `always`（默认） | 每次 `run_shell` / `write_file` 都确认 |
| `dangerous` | 仅危险操作确认 |
| `off` | 关闭（不推荐） |

---

## 8. 可审计 → Token / 费用

前面几步产生的模型调用会写入本地 `data/audit/usage.jsonl`。

**输入：**

```bash
LA audit --since 7d
LA audit --since 7d --report /tmp/la-tour-audit.md
```

**预期输出（交互式摘要，示意）：**

```text
[audit] 摘要（7d）
  调用: 47  Token: 31,280  估算费用: $0.0000
    ollama: 42 次, 28,450 tokens, $0.0000
    ddgs: 5 次, 0 tokens, $0.0000

文件安全: 未发现高风险项
记忆健康: facts=12 · knowledge_chunks=38

→ LA audit --report report.md  导出完整报告
```

**报告片段（与 [audit-report-sample.md](audit-report-sample.md) 同结构）：**

```markdown
## Token 与服务花费
| Provider | 调用 | Token | 估算费用 (USD) |
|----------|------|-------|----------------|
| ollama   | 42   | 28450 | $0.0000        |

## 文件安全
未发现高风险项。

## 记忆健康
facts=12 · knowledge_chunks=38 · bm25=ready · chroma=ready
```

> **对比点**：Ollama 本地调用费用恒为 **$0**；敏感路径/误索引风险会出现在「文件安全」段，可导出 Markdown 留存。

---

## 9. 进阶：写文件幻觉检测 + 时间优先召回

### 9.1 写文件幻觉检测

原则：用户说清楚路径与内容后直接执行；写文件需确认；若模型声称「已写入」却未调用工具，会重试或报错。

### 9.1.1 明确请求 → 确认后写入

**输入：**

```bash
la chat --provider ollama
```

```text
你> 修改根目录下的 tour-note.txt，追加一行：跨会话持续性测试
```

**预期输出（示意）：**

```text
[chat] 处理中…
[chat] 调用 写入文件…
⚠ Agent 请求写入文件，需你确认后才会执行。
…
是否允许 / 确定要执行吗？ [y/N] y
已成功将内容追加到 tour-note.txt。
```

### 9.1.2 记忆类问题 → 直接查

```text
你> 我喜欢喝什么？
```

**预期输出：**

```text
[chat] 调用 搜索记忆…
你喜欢喝美式咖啡，不喜欢拿铁。
```

---

### 9.2 时间优先召回 → 综合推理

记忆带有**发生时间**；提问若带时间域（「2023 年 5 月」「上周」「现在」），召回会**提高时间权重**，优先匹配该时间窗，再交由大模型综合作答。

### 9.2.1 准备同一主题、不同时间的记忆

```bash
LA memory add "2026年5月，架构评审后先试用轻量方案，尚未最终选定 Mem0"
LA memory add "2026年7月，最终决定采用 Mem0：更轻、更快，reflect 由 search + 本地 LLM 完成"
```

### 9.2.2 按时间域检索（Warm）

**输入：**

```bash
LA memory search "2026年5月 记忆引擎选型" --verbose
LA memory search "2026年7月 记忆引擎选型" --verbose
```

**预期行为：**

- 5 月查询 → 置顶「尚未最终选定 / 先试用轻量方案」那条，`temporal_score` 更高  
- 7 月查询 → 置顶「最终决定采用 Mem0」那条  

示意：

```text
[search] 检索记忆: 2026年5月 记忆引擎选型
### 1. …
相关度 0.91 · 时间衰减/对齐 0.95 · 2026-05-…
2026年5月，架构评审后先试用轻量方案，尚未最终选定 Mem0
```

### 9.2.3 跨记忆推理（Reflect）

**输入：**

```bash
LA memory reflect "记忆引擎选型经历了怎样的变化？"
```

**预期输出（示意）：**

```text
[reflect] 查询: 记忆引擎选型经历了怎样的变化？
召回 2 条相关记忆，正在归纳…

2026 年 5 月仍在试用轻量方案、未最终选定；到 2026 年 7 月明确采用 Mem0，
看重更轻、更快，并用 search + 本地 LLM 完成 reflect。整体是从试探到拍板的演进。
```

### 9.2.4 在 Chat 里用自然语言问时间题

```bash
la chat --provider ollama
```

```text
你> 我现在对记忆引擎的最终决定是什么？5 月时呢？
```

**预期输出（示意）：**

```text
[chat] 调用 搜索记忆…
你现在（以最新状态为准）最终决定采用 Mem0。
5 月时还在试用轻量方案，尚未最终选定。
```

> **对比点**：不是「语义最像就排前面」，而是**问题要求的时间域 × 记忆发生时间**对齐后再推理——这正是长期助手答对「当时 vs 现在」的关键。

---

## 一键串跑（可选）

在隔离目录快速过一遍非交互命令：

```bash
export LA_DATA_DIR=/tmp/la-product-tour
rm -rf "$LA_DATA_DIR"
mkdir -p "$LA_DATA_DIR"

LA memory add "我叫林晓，日常偏好喝美式咖啡，不喜欢拿铁"
LA memory add "2026年5月，我在深圳开会讨论产品路线，结论是优先做本地个人 AI 助手"
LA memory add "2026年5月，架构评审后先试用轻量方案，尚未最终选定 Mem0"
LA memory add "2026年7月，最终决定采用 Mem0：更轻、更快"

LA rag add examples/sample-project-notes.md
LA memory search "我喜欢喝什么"
LA rag search "三层记忆架构"
LA memory search "2026年5月 记忆引擎" --verbose
LA memory search "2026年7月 记忆引擎" --verbose
LA memory reflect "记忆引擎选型经历了怎样的变化？"
LA workspace --cwd .
LA audit --since 7d

echo "演示数据: $LA_DATA_DIR"
```

交互部分（chat 联网、Shell 确认、写文件）请按 §6 / §7 / §9 手动走一遍。

---

## 10. 一键总结（故事 6b）

对本地 PDF / Markdown 做「3 分钟读懂」，并进入文档对话：

**输入：**

```bash
la summarize examples/sample-project-notes.md
```

**预期：** 打印速读卡（总结 + 带 〔§…〕 的要点）；TTY 下进入 `sum>`，可继续追问该文件；`/keep` 才入库；`/exit` 结束。仅要卡片时加 `--no-chat`。

---

## 11. 新闻嗅探（故事 6c）

从 BestBlogs 精选池拉今日资讯，交互浏览：

**输入：**

```bash
la news sync
la news brief
```

**预期：** `sync` 拉取若干条；`brief` 在 TTY 进入交互浏览器（↑↓ 切换、`o` 打开浏览器、`r` 精读深聊）。脚本场景用 `la news brief --no-ui`。可选 `la news schedule on` 启用早 8 点自动 sync。

---

## 12. 一键润色（故事 6d）

把一段「催进度」草稿交给 LA，识别场合态度后改写，并把主推复制到剪贴板：

**输入：**

```bash
la polish --no-copy --scene email "您好，上次说的方案这周能给一下吗？我们这边有点着急。"
```

**预期：** 输出含【识别】【主推】【备选】【改动】；加 `--no-copy` 时不写剪贴板（便于脚本）。去掉 `--no-copy` 时默认复制主推，TTY 下可按 `2`/`3` 换拷备选。

会话内等价：`/polish --scene email 您好，上次说的方案…`

---

## 验收清单

对照 [PRD §6](../docs/PRD.md) 验收，你应能勾选：

- [ ] **故事 1–3**：用户或开发者安装 + 纯本地 / 自有 API 配置后，`la chat` Hello World  
- [ ] **故事 4**：换 `--session-id` 仍能答出姓名 / 偏好 / 5 月会议（Hot / Warm）  
- [ ] **故事 5–6**：ChatGPT 导入成功；`memory search` 与 `rag search` 分别体现 Warm / Cold  
- [ ] **记忆确认门**：后台提取后 `LA memory pending` 可见候选；`approve` / `reject` 可控写入（或设 `LA_MEMORY_APPROVAL_AUTO=1`）  
- [ ] **故事 7**：小模型对话中自动 `web_search`（默认 ddgs），答案带来源感  
- [ ] **故事 8–9**：Shell / 写文件弹出确认；危险命令有「风险」提示或硬拦截  
- [ ] **故事 10**：`LA audit` 能看到 Token 与费用；`--report out.html` 可导出 HTML  
- [ ] **故事 6b**：`la summarize` 出速读卡；TTY 进 `sum>`；默认不入库  
- [ ] **故事 6c**：`la news sync` + `la news brief`（或 `--no-ui`）能看到带原文链接的简报  
- [ ] **故事 6d**：`la polish --no-copy` 输出识别 Brief + 主推/备选；不加 `--no-copy` 时主推可粘贴  
- [ ] **进阶**：明确路径写文件确认写入；「5 月 vs 7 月」时间查询 + `reflect` 讲清演变  

---

## 下一步

| 资源 | 说明 |
|------|------|
| [walkthrough.md](walkthrough.md) | 更短的 6 场景上手 |
| [mem0-demo.md](mem0-demo.md) | Mem0 Retain / Recall / Reflect 深度演示 |
| [audit-report-sample.md](audit-report-sample.md) | 审计报告完整样例 |
| [../docs/PRD.md](../docs/PRD.md) · [../docs/TDD.md](../docs/TDD.md) | 产品设计 / 用户故事 / 章程 · 技术设计 |
| [../benchmarks/locomo/README.md](../benchmarks/locomo/README.md) | LoCoMo 长期记忆基准 |

有问题可在仓库提 Issue；体验满意的话，把 `LA_DATA_DIR` 换回默认目录，开始导入你自己的笔记与 ChatGPT 历史。
