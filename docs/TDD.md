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
    Warm: Mem0 (fallback: JSON memory_store)
    Cold: Chroma + BM25 + RRF
```

## 2. 模块结构

```
src/localagent/
├── cli.py                 # 全部 LA 命令
├── chat_repl.py           # REPL + slash 命令 (/…)
├── session_commands.py    # 会话内 / 命令分发（与外层 CLI 共享）
├── agent/
│   └── runtime.py         # Agent 工具循环
├── models/router.py       # 三级模型回退
├── memory/
│   ├── core_profile.py    # Hot 层
│   ├── backend.py         # MemoryBackend 工厂
│   ├── backends/
│   │   ├── json_backend.py
│   │   └── mem0_backend.py
│   ├── temporal_intent.py
│   ├── scoped_recall.py
│   └── value_filter.py
├── knowledge/
│   ├── chroma_store.py
│   ├── bm25_store.py
│   ├── hybrid.py
│   └── indexer.py
├── ingest/                # rag add / rag ingest / pipeline (Cold only)
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
├── mem0/                # Mem0 qdrant + history.db
├── bm25.pkl
└── audit/usage.jsonl
```

## 4. 关键设计决策

| 决策 | 选型 |
|------|------|
| 记忆引擎 | Mem0（主依赖）+ JSON fallback / 注册表 |
| 知识检索 | Chroma + BM25 + RRF |
| 编排 | LangGraph + SQLite Checkpointer |
| 联网 | ddgs 默认（可选 Tavily / SearXNG） |
| 模型 | Ollama 优先，OpenRouter/Cursor 降级 |

## 5. 时间召回

- `parse_temporal_intent` 分类意图：`range` / `as_of_now` / `when_event` / `duration` / `none`
- 有日历窗（`range`、`as_of_now`）时：锚点衰减 + scope 软奖惩；词法路径时间权重约 40%，Mem0 hybrid 约 20%
- `when_event`（When did…）：时间几乎不主导排序；默认自动扩 ±1 邻轮，靠事件关键词召回后由 LLM 读记忆日期作答
- scope 只做 soft boost（窗内 1.0 / 近窗 0.5 / 窗外 0.15），不硬过滤缺日期记忆

## 6. 请求路径

```
用户输入 → Agent 循环（直接执行）
  ├─ JIT 预加载（画像 / 记忆 / 联网 / 工作区）
  ├─ 工具调用
  └─ write_file / run_shell 执行前确认
```

天气地点：显式城市 → 档案 `居住地` → 记忆扫描 pin → 仍无则直接搜并软提示可换城市。

联网天气：`web_search` 在核对失败或命中歌词/教案等垃圾结果时自动换查询重试；agent 禁止未重试就交卷。
