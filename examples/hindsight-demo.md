# Hindsight 记忆引擎深度演示

本演示用一条**虚构的架构决策时间线**，展示 Hindsight 作为 Warm 层记忆引擎的核心能力：

| 能力 | 演示命令 | 说明 |
|------|----------|------|
| **Retain** | `LA add` | 写入记忆并自动提取标题、标签、发生时间 |
| **4 路 Recall** | `LA search` | 语义检索，Hindsight 并行多策略召回 |
| **时间感知** | `LA search "2026年5月"` | 结合发生时间重排序 |
| **结构化浏览** | `LA memories --tag 决策` | 按标签过滤、排序 |
| **Reflect** | `LA reflect` | 跨多条记忆推理，处理矛盾与演变 |
| **对话集成** | `LA chat` | Agent 按需 JIT 召回 / 推理 |

> 示例数据均为虚构，可安全复现。建议使用隔离数据目录，不污染日常 `data/`。

---

## 前置条件

```bash
# Python 3.11+ 虚拟环境
python3.11 -m venv .venv311 && source .venv311/bin/activate

# 完整安装 + Hindsight
pip install -e ".[hindsight,dev]"

# 本地 Ollama（对话与 reflect 推理）
ollama pull qwen3.5:4b

# 确认 Hindsight 就绪
LA memory-status
```

**预期 `memory-status` 输出要点：**

```text
当前后端:     hindsight (HindsightBackend)
Retain 模式:  chunks
记忆条数:     …
```

若显示 `json` 后端，请检查 Python 版本与 `pip install -e ".[hindsight]"`。

---

## 第 1 步：构建「演变中的决策」记忆库

LocalAgent 的 Warm 层擅长保存**随时间变化的事实**。下面 4 条记忆构成一条决策演变链——从立项到最终选型，中间还有反复：

```bash
export LA_DATA_DIR=/tmp/la-hindsight-demo
LA reset-memory --keep-knowledge   # 清空隔离 bank，不影响日常 data/

LA add "2026年3月，开发者决定用 Python 重写个人助手，项目代号 LocalAgent"
LA add "2026年5月，架构评审后放弃 SQLite，改用 Hindsight 作为 Warm 层记忆引擎"
LA add "2026年6月，团队曾考虑回退到 JSON 存储，因为 Hindsight 安装包体积较大"
LA add "2026年7月，最终决定保留 Hindsight，因为 reflect 推理和 4 路并行 recall 不可替代"

# 补充两条独立偏好，用于后续 reflect 综合
LA add "技术偏好：所有个人数据必须留在 Mac 本地，不上传云端"
LA add "LocalAgent 默认模型是 qwen3.5:4b，通过 Ollama 本地运行"
```

**预期 `add` 输出：**

```text
[add] 已写入记忆 (id=f3887af1...)
      「2026年3月，开发者决定用 Python 重写个人…」 · 工作/技术/决策
```

注意标题保留了 `2026年3月` 等时间前缀，标签自动推断为 `#决策`、`#技术` 等。

---

## 第 2 步：语义 Recall —— 模糊查询也能命中

```bash
LA search "记忆引擎选型"
```

**预期：** 返回与 Hindsight / SQLite / JSON 相关的多条记忆，按相关度排序，并显示：

- 标题（如 `2026年5月，架构评审后放弃 SQLite…`）
- 发生时间（`2026-05-01`）
- 标签（`#决策`）
- 来源（`LA add`）

```text
找到 5 条相关记忆（查询: 记忆引擎选型）

### 1. 2026年5月，架构评审后放弃 SQLite…
相关度 0.62 · 2026-05-01 · 事实 · #决策
...
```

---

## 第 3 步：时间感知 Recall —— 「2026年5月发生了什么」

```bash
LA search "2026年5月 决定" --verbose
```

**预期：** 2026 年 5 月的记忆排在前列（放弃 SQLite、改用 Hindsight），而非 7 月的最终决定。

`--verbose` 会额外显示语义分、时间衰减分与时间锚点，便于理解重排序逻辑。

---

## 第 4 步：结构化浏览 —— 标签与时间过滤

```bash
# 列出所有标签
LA memories --list-tags

# 只看「决策」类记忆，按时间倒序
LA memories --tag 决策 --sort newest

# 限定 2026 年上半年的决策
LA memories --tag 决策 --since 2026-01-01 --until 2026-06-30
```

**预期 `--list-tags`：**

```text
共 3 个标签：
  #决策  (3)
  #技术  (2)
  #工作  (1)
```

---

## 第 5 步：Reflect —— 跨记忆推理（Hindsight 独有）

当问题需要**综合多条记忆、梳理演变过程**时，普通 keyword recall 不够，需要 reflect：

```bash
LA reflect "LocalAgent 的记忆引擎选型经历了怎样的变化？最终为什么保留 Hindsight？"
```

**预期：** Hindsight 会检索相关记忆并生成归纳性回答，大致包含：

1. 3 月立项 LocalAgent
2. 5 月从 SQLite 转向 Hindsight
3. 6 月曾考虑回退 JSON（体积顾虑）
4. 7 月因 reflect + 4 路 recall 能力而保留 Hindsight

若当前为 JSON 后端，`LA reflect` 会降级为 recall 并提示安装 Hindsight。

---

## 第 6 步：对话中自然使用记忆

```bash
LA chat --provider ollama
```

在 REPL 中尝试：

```text
你> 我们关于记忆引擎做过哪些决定？最后怎么选的？
助手> [调用 search_memory 或 reflect_memory，综合 3–7 月的决策链回答]

你> 2026年6月团队担心的是什么？
助手> [召回 6 月「考虑回退 JSON」的记忆]

你> 我的技术偏好是什么？
助手> [召回「数据留在 Mac 本地」的偏好记忆]
```

---

## 一键演示脚本

```bash
bash examples/hindsight-demo.sh
```

脚本使用 `LA_DATA_DIR=/tmp/la-hindsight-demo` 隔离数据，依次执行写入、检索、reflect，并打印关键输出。

---

## Hindsight vs JSON 后端对比

| 维度 | JSON 后端 | Hindsight 后端 |
|------|-----------|----------------|
| 写入 | 本地启发式 enrich | Retain + 向量索引 |
| 召回 | BM25 式 token 匹配 | 4 路并行 recall + 语义 |
| 推理 | 无 | reflect 跨记忆归纳 |
| 维护 | 手动 | consolidation 自动合并 |
| 依赖 | 无额外包 | Python 3.11+，`hindsight-all` |

日常使用无需手动切换：`LA_MEMORY_BACKEND=auto` 会在 Hindsight 可用时自动启用。

---

## 清理

```bash
LA reset-memory          # 清空演示记忆（保留知识库）
rm -rf /tmp/la-hindsight-demo
```
