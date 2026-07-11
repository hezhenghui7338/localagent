# LocalAgent 技术设计文档（TDD v1）

## 1. 架构

```
LA CLI → chat REPL / ingest / pending
         ↓
    LangGraph Agent (JIT tools)
         ↓
    ModelRouter (Ollama → OpenRouter → Cursor)
         ↓
    Hot: core_profile.json
    Warm: Hindsight (fallback: JSON memory_store)
    Cold: Chroma + BM25 + RRF
```

## 2. 模块结构

```
src/localagent/
├── cli.py                 # 全部 LA 命令
├── chat_repl.py           # REPL + :deepsearch
├── agent/runtime.py       # Agent 工具循环
├── models/router.py       # 三级模型回退
├── memory/
│   ├── core_profile.py    # Hot 层
│   ├── hindsight_client.py
│   ├── temporal_intent.py
│   ├── scoped_recall.py
│   └── value_filter.py
├── knowledge/
│   ├── chroma_store.py
│   ├── bm25_store.py
│   ├── hybrid.py
│   └── indexer.py
├── ingest/                # add-file / sync-file / pipeline
├── pending/               # 确认门
├── persist/               # conversations jsonl + sessions.db
├── workspace/             # git / recent files / todos
├── audit/                 # usage log, security scan, reports
└── tools/                 # search_memory / search_knowledge / web_search / workspace_context
```

## 3. 数据目录

```
data/
├── kb/                  # 软链接
├── core_profile.json
├── sync_index.json
├── pending_queue.json
├── conversations/*.jsonl
├── sessions.db
├── chroma/
├── bm25.pkl
└── audit/usage.jsonl
```

## 4. 关键设计决策

| 决策 | 选型 |
|------|------|
| 记忆引擎 | Hindsight（可选）+ JSON fallback |
| 知识检索 | Chroma + BM25 + RRF |
| 编排 | LangGraph + SQLite Checkpointer |
| 联网 | Tavily（Agent 自动触发） |
| 模型 | Ollama 优先，OpenRouter/Cursor 降级 |

## 5. 时间召回

- `TemporalIntentParser` 从问题解析时间锚点
- `scoped_recall`：语义 75% + 距锚点 25% 混合排序
