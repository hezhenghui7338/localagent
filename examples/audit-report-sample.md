# LocalAgent 审计报告

生成时间: 2026-07-11 10:30 UTC  
统计范围: （自 7d）  
工作区: `/Users/demo/code/localagent`

## Token 与服务花费

- 调用次数: 47
- Token 合计: 31,280
- 估算费用 (USD): $0.0200

### 按 Provider

| Provider | 调用 | Token | 估算费用 (USD) |
|----------|------|-------|----------------|
| ollama | 42 | 28,450 | $0.0000 |
| tavily | 5 | 0 | $0.0500 |

> **重点：Ollama 本地模型完全免费。** 上表 42 次对话、记忆提取与检索全部走本地 `qwen3.5:4b`，Token 消耗不计费。仅联网搜索（Tavily）产生少量 API 费用；若关闭联网功能，总费用为 **$0**。

### 按命令类型

- `chat`: 18 次
- `extract_facts`: 14 次
- `web_search`: 5 次
- `deepsearch`: 2 次
- `enrich_memory`: 8 次

### 按模型

| 模型 | 调用 | Token | 估算费用 (USD) |
|------|------|-------|----------------|
| qwen3.5:4b | 42 | 28,450 | $0.0000 |

## 文件安全

未发现高风险项。

## 记忆健康

facts=12 · knowledge_chunks=38 · bm25=ready · chroma=ready

## 工作区快照

```text
工作区: /Users/demo/code/localagent
最近 7 天修改的文件:
  - 2026-07-11 10:15  examples/walkthrough.md
  - 2026-07-11 09:40  README.md
  - 2026-07-10 18:22  src/localagent/cli.py

Git 分支: main
工作区: 干净（无未提交变更）
最近提交:
  - 086c125 Initial commit: LocalAgent CLI

待办项 (2 条，显示前 10):
  - [checkbox] examples/sample-project-notes.md:28  补充 examples 目录，方便新用户上手
  - [todo] examples/sample-project-notes.md:29  支持更多文档格式导入
```

---
*费用为基于默认单价的估算，可在 .env 中设置 LA_COST_* 覆盖。*
