# LocalAgent 产品体验教程

> **目标**：用一条连贯的「虚构用户」故事，在约 **30 分钟**内亲手跑通 LocalAgent 的八大优势。  
> 每一步都给出**完整输入**与**预期输出**（示例数据均为虚构，可安全复现）。  
> 命令入口：`la` / `LA`（等价）。  
> [English](product-tour.md)

---

## 你将体会到什么

| # | 优势 | 本节 |
|---|------|------|
| 1 | 极简安装：装好 → example 配置 → Hello World | [§1](#1-极简安装--hello-world) |
| 2 | 跨会话记住你：Hot 画像 / Warm 长期记忆 / Cold 文档检索 | [§2](#2-跨会话记忆--hot--warm--cold-三层结构) |
| 3 | 联网：小模型也能恰当调用网络资源 | [§3](#3-联网搜索--小模型也能用好网络) |
| 4 | 操作本机文件 + 危险命令提醒 + 每次确认 | [§4](#4-本地文件系统--安全审查与确认) |
| 5 | 可审计：Token、费用、敏感文件一网打尽 | [§5](#5-可审计--token费用敏感扫描) |
| 6 | 主动意识：意图不清先澄清，再严格按意图执行 | [§6](#6-主动意图澄清) |
| 7 | 多源记忆：对话自动 / `add` / `add-file` / `sync-file` / `import-chatgpt` | [§7](#7-多源记忆写入) |
| 8 | 时间域优先召回 + 大模型综合推理 | [§8](#8-时间优先召回--综合推理) |

**叙事设定（虚构）**：你是「林晓」，在 Mac 上用 LocalAgent 做个人助手；偏好美式咖啡；2026-05 在深圳开会定了产品路线；2026-07 决定用 Mem0 做记忆引擎。

**建议**：用隔离数据目录，不污染日常数据：

```bash
export LA_DATA_DIR=/tmp/la-product-tour
```

下文凡出现 `data/`，在隔离模式下即指 `$LA_DATA_DIR/`。

---

## 1. 极简安装 → Hello World

### 1.1 安装

**输入：**

```bash
pipx install "git+https://github.com/hezhenghui7338/localagent.git@v0.2.0"
la --version
```

**预期输出：**

```text
la-localagent 0.2.0
```

> 源码开发可改为：`pip install -e ".[dev]"`，效果相同。

### 1.2 按 example 配置

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
  "MINIMAX_API_KEY": ""
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

### 1.3 准备本地模型（首次）

```bash
la setup -y
# 或手动：ollama pull qwen3.5:4b
```

### 1.4 Hello World

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
LocalAgent v0.2.0 …
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

## 2. 跨会话记忆 → Hot / Warm / Cold 三层结构

核心承诺：**换会话、换模型，不换「我是谁」**。三层分工：

| 层 | 存什么 | 典型位置 / 命令 |
|----|--------|-----------------|
| **Hot** | 核心画像与状态（姓名、偏好、长期目标） | `data/core_profile.json` |
| **Warm** | 结构化长期事实（Mem0 / JSON） | `la add` / 对话提取 / `la search` |
| **Cold** | 文档原文片段（语义 + BM25） | `la add-file` → `la search --knowledge` |

### 2.1 写入 Warm：手动一条事实

**输入：**

```bash
la add "我叫林晓，日常偏好喝美式咖啡，不喜欢拿铁"
la add "2026年5月，我在深圳开会讨论产品路线，结论是优先做本地个人助手"
```

**预期输出（示意）：**

```text
[add] 已写入记忆: 我叫林晓，日常偏好喝美式咖啡，不喜欢拿铁
  id: a1b2c3d4 · 标题: 个人偏好 · 标签: #偏好/饮品
[add] 已写入记忆: 2026年5月，我在深圳开会讨论产品路线…
  id: e5f6g7h8 · 标题: 深圳产品路线会议 · 标签: #决策/产品
```

### 2.2 写入 Cold：导入文档

**输入：**

```bash
la add-file examples/sample-project-notes.md
la search "三层记忆架构" --knowledge
```

**预期输出（add-file）：**

```text
[add-file] 源文件: …/examples/sample-project-notes.md (1.1 KB)
[add-file] 软链: data/kb/sample-project-notes.md
  ✓ sample-project-notes.md: facts=3, chunks=5
[add-file] done
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

### 2.3 Warm 召回

**输入：**

```bash
la search "我喜欢喝什么"
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

### 2.4 跨会话验证（关键）

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
2026 年 5 月你在深圳开会讨论产品路线，结论是优先做本地个人助手。
[via ollama/qwen3.5:4b]
```

> **对比点**：普通 Chat 客户端换会话就「失忆」；LocalAgent 从 Warm/Hot 召回，**不依赖当前会话上下文**。

### 2.5 一眼看清三层

```bash
# Hot
cat "${LA_DATA_DIR:-data}/core_profile.json" 2>/dev/null || echo "(画像随对话/导入逐步 enrich)"

# Warm
la search "林晓" --top-k 3

# Cold
la search "qwen3.5:4b" --knowledge --top-k 2
```

---

## 3. 联网搜索 → 小模型也能用好网络

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

## 4. 本地文件系统 → 安全审查与确认

Agent 可真正执行本机命令 / 写文件；**默认每次需你确认**；危险命令额外警告；极端命令直接拦截。

### 4.1 安全的只读命令（仍需确认）

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

### 4.2 危险命令：额外警告

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

### 4.3 硬拦截（不会执行、也不该确认通过）

例如尝试删除根目录类命令时，策略会 **blocked**，直接拒绝：

```text
错误: 禁止删除根目录。
```

### 4.4 写文件同样需确认

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

## 5. 可审计 → Token / 费用 / 敏感扫描

前面几步产生的模型调用会写入本地 `data/audit/usage.jsonl`。

**输入：**

```bash
la audit --since 7d
la audit --since 7d --report /tmp/la-tour-audit.md
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

## 6. 主动意图澄清

原则：**少打扰**——读操作/记忆回忆直接做；只有**高代价模糊**（如改文件却没说路径）才追问 **1** 个关键问题；澄清后严格按意图执行。

### 6.1 模糊请求 → 追问（不瞎改）

**输入：**

```bash
la chat --provider ollama
```

```text
你> 帮我改个文件
```

**预期输出：**

```text
在继续之前，我想先确认你的意图：

1. 需要修改哪个文件或提供完整路径？
2. 具体的修改内容或目标是什么？

请补充说明，我会据此继续处理。
```

### 6.2 澄清后严格执行

```text
你> 修改根目录下的 tour-note.txt，追加一行：跨会话持续性测试
```

**预期输出（示意）：**

```text
[chat] 思考中…
[chat] 调用 写入文件…
⚠ Agent 请求写入文件，需你确认后才会执行。
…
是否允许 / 确定要执行吗？ [y/N] y
已成功将内容追加到 tour-note.txt。
```

### 6.3 记忆类问题 → 不追问，直接查

```text
你> 我喜欢喝什么？
```

**预期输出：**

```text
[chat] 调用 搜索记忆…
你喜欢喝美式咖啡，不喜欢拿铁。
```

（不会误当成「推荐饮品」场景去追问口味。）

关闭澄清（一般不需要）：`LA_INTENT_CLARIFY=0`。

---

## 7. 多源记忆写入

| 来源 | 命令 / 时机 | 说明 |
|------|-------------|------|
| 对话自动识别 | `la chat` 过程中 / 退出提取 | 自然聊天沉淀事实 |
| 手动一条 | `la add "…"` | 精确写入 |
| 文档提取 | `la add-file <path>` | 软链 + Warm 事实 + Cold 全文 |
| 目录同步 | `la sync-file` | 扫描 `data/kb/` 全部文档 |
| ChatGPT 导出 | `la import-chatgpt <json>` | 从历史对话提取个人记忆 |

### 7.1 手动添加（已在 §2 演示）

```bash
la add "2026年7月，最终决定采用 Mem0 作为 Warm 层记忆引擎"
```

### 7.2 文档自动提取

```bash
la add-file examples/sample-project-notes.md
# 若已把多份笔记软链到 kb/：
la sync-file
```

**预期输出（sync-file 示意）：**

```text
[sync-file] 扫描 data/kb/ …
  ✓ sample-project-notes.md: facts=3, chunks=5 (unchanged, skip)
[sync-file] done · indexed=0 · skipped=1
```

加 `--force` 可强制重建索引。

### 7.3 ChatGPT 格式导入

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

la import-chatgpt /tmp/chatgpt-sample.json
la search "VS Code"
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

### 7.4 对话中自动识别（体验）

```bash
la chat --session-id tour-auto --provider ollama
```

```text
你> 对了，我的长期目标是把 LocalAgent 做成真正懂我的本机助手。
助手> …（正常对话）
你> /q
```

之后：

```bash
la search "长期目标"
```

应能召回相关事实（具体文案取决于提取管线；可用 `la rememorize-chat --session tour-auto` 补提取）。

---

## 8. 时间优先召回 → 综合推理

记忆带有**发生时间**；提问若带时间域（「2023 年 5 月」「上周」「现在」），召回会**提高时间权重**，优先匹配该时间窗，再交由大模型综合作答。

### 8.1 准备同一主题、不同时间的记忆

```bash
la add "2026年5月，架构评审后先试用轻量方案，尚未最终选定 Mem0"
la add "2026年7月，最终决定采用 Mem0：更轻、更快，reflect 由 search + 本地 LLM 完成"
```

### 8.2 按时间域检索（Warm）

**输入：**

```bash
la search "2026年5月 记忆引擎选型" --verbose
la search "2026年7月 记忆引擎选型" --verbose
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

### 8.3 跨记忆推理（Reflect）

**输入：**

```bash
la reflect "记忆引擎选型经历了怎样的变化？"
```

**预期输出（示意）：**

```text
[reflect] 查询: 记忆引擎选型经历了怎样的变化？
召回 2 条相关记忆，正在归纳…

2026 年 5 月仍在试用轻量方案、未最终选定；到 2026 年 7 月明确采用 Mem0，
看重更轻、更快，并用 search + 本地 LLM 完成 reflect。整体是从试探到拍板的演进。
```

### 8.4 在 Chat 里用自然语言问时间题

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

la add "我叫林晓，日常偏好喝美式咖啡，不喜欢拿铁"
la add "2026年5月，我在深圳开会讨论产品路线，结论是优先做本地个人助手"
la add "2026年5月，架构评审后先试用轻量方案，尚未最终选定 Mem0"
la add "2026年7月，最终决定采用 Mem0：更轻、更快"

la add-file examples/sample-project-notes.md
la search "我喜欢喝什么"
la search "三层记忆架构" --knowledge
la search "2026年5月 记忆引擎" --verbose
la search "2026年7月 记忆引擎" --verbose
la reflect "记忆引擎选型经历了怎样的变化？"
la workspace --cwd .
la audit --since 7d

echo "演示数据: $LA_DATA_DIR"
```

交互部分（chat 联网、Shell 确认、意图澄清）请按 §3 / §4 / §6 手动走一遍——那才是「主动 Agent」的体感。

---

## 验收清单

完成教程后，你应能勾选：

- [ ] 仅安装 + example 配置即可 `la chat` 得到 Hello World  
- [ ] 换 `--session-id` 仍能答出姓名 / 偏好 / 5 月会议  
- [ ] `search` 与 `search --knowledge` 分别体现 Warm / Cold  
- [ ] 小模型对话中自动 `web_search`，答案带来源感  
- [ ] Shell / 写文件弹出确认；危险命令有「风险」提示  
- [ ] `la audit` 能看到 Token 与费用（Ollama 为 $0）  
- [ ] 「帮我改个文件」会先追问，澄清后再写  
- [ ] `add` / `add-file` / `sync-file` / `import-chatgpt` 至少各成功一次  
- [ ] 「5 月 vs 7 月」时间查询召回不同记忆，`reflect` 能讲清演变  

---

## 下一步

| 资源 | 说明 |
|------|------|
| [walkthrough.md](walkthrough.md) | 更短的 6 场景上手 |
| [mem0-demo.md](mem0-demo.md) | Mem0 Retain / Recall / Reflect 深度演示 |
| [audit-report-sample.md](audit-report-sample.md) | 审计报告完整样例 |
| [../docs/PRD.md](../docs/PRD.md) · [../docs/TDD.md](../docs/TDD.md) | 产品与技术设计 |
| [../benchmarks/locomo/README.md](../benchmarks/locomo/README.md) | LoCoMo 长期记忆基准 |

有问题可在仓库提 Issue；体验满意的话，把 `LA_DATA_DIR` 换回默认目录，开始导入你自己的笔记与 ChatGPT 历史。
