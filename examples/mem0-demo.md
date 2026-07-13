# Mem0 记忆引擎深度演示

本演示用一条**虚构的架构决策时间线**，展示 Mem0 作为 Warm 层记忆引擎的核心能力：

| 能力 | 命令 | 说明 |
|------|------|------|
| **Retain** | `LA memory add` | 写入事实；默认 `infer=False`，由 LA enrich 做标题/标签 |
| **Semantic Recall** | `LA memory search` | Mem0 向量检索 + 本地时间重排 |
| **Reflect** | `LA memory reflect` | search top-k + LA LLM 归纳（模拟跨记忆推理） |

## 准备

```bash
# 源码开发（mem0ai 已是主依赖）
pip install -e ".[dev]"

# 确认 Mem0 就绪（需可用的嵌入模型，如 Ollama 的 bge-m3）
LA memory status
```

当前后端:     mem0 (Mem0Backend)

若显示 `json` 后端，请检查 Ollama 是否有嵌入模型，或设置 `LA_MEM0_EMBEDDER_*`。

## 一键脚本

```bash
bash examples/mem0-demo.sh
```

脚本使用 `LA_DATA_DIR=/tmp/la-mem0-demo` 隔离数据，依次执行写入、检索、reflect。

## 手写步骤摘要

```bash
export LA_DATA_DIR=/tmp/la-mem0-demo
LA memory reset --keep-knowledge

LA memory add "2026年5月，架构评审后放弃 SQLite，改用 Mem0 作为 Warm 层记忆引擎"
LA memory add "2026年7月，最终决定采用 Mem0：更轻、更快，reflect 由 search + 本地 LLM 模拟"

LA memory search "记忆引擎选型"
LA memory reflect "记忆引擎选型经历了怎样的变化？"
```

## Mem0 vs JSON 后端对比

| 维度 | JSON 后端 | Mem0 后端 |
|------|-----------|-----------|
| 语义召回 | BM25 + Jaccard | 向量检索 |
| Reflect | 降级为 recall | search + LLM |
| 依赖 | 无额外包 | `mem0ai`（主依赖） |
| 适用 | 测试 / 无嵌入模型 | 日常长期记忆 |

`LA_MEMORY_BACKEND=mem0`（默认）；显式 `json` 可强制轻量后端。

从旧 JSON / Hindsight 注册表迁到 Mem0 索引：

```bash
LA memory reindex
```
