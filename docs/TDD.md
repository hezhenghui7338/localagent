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
          ├─ hybrid recall (+ optional SQLite hop expand)
          └─ optional Neo4j Cypher (counts / aggregations / multi-hop)
    Cold: Chroma + BM25 + RRF
```

精确问（多少次/列出所有/同时提到）走 `query_memory_graph` → Cypher 模板 → 计算结果；开放语义问仍走 hybrid 文本召回。**Neo4j 默认关闭**（`LA_NEO4J=0`），与 `LA_MEMORY_GRAPH` 独立；仅在需要精确计数/聚合时再 `pip install 'la-localagent[neo4j]'` 并开启——符合「只摘低垂成熟果实」。
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
│   ├── value_filter.py
│   └── graph/             # SQLite hop + Neo4j precise Cypher
│       ├── store.py       # SQLite MemoryGraphStore
│       ├── neo4j_store.py
│       ├── precise_query.py
│       ├── cypher_templates.py
│       └── cypher_guard.py
├── knowledge/
│   ├── chroma_store.py
│   ├── bm25_store.py
│   ├── hybrid.py
│   └── indexer.py
├── ingest/                # rag add / rag ingest / pipeline (Cold only; images via vision.py)
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
| 产品边界 | 只做本地 agent：数据留本机，本地可完整跑通；联网与云端模型为可选增强（见 PRD 章程） |
| Warm 写入确认 | `LA_MEMORY_APPROVAL_REQUIRED`（默认开）：非交互提取入 `pending_queue.json`；`approve`/`reject`；`LA_MEMORY_APPROVAL_AUTO=1` 跳过（CI） |
| 记忆引擎 | Mem0（主依赖）+ JSON fallback / 注册表 |
| 知识检索 | Chroma + BM25 + RRF；图片 ingest 时经 Ollama VL（`LA_VL_MODEL`）文本化后入 Cold；对话归档亦入 Cold |
| 编排 | LangGraph + SQLite Checkpointer |
| 联网 | **ddgs 默认**（无需 Key）；可选 Tavily / SearXNG |
| 模型 | Ollama 优先，OpenRouter/Cursor 降级；VL 与 chat 模型分离 |

## 5. 时间召回

- `parse_temporal_intent` 分类意图：`range` / `as_of_now` / `when_event` / `duration` / `none`
- 有日历窗（`range`、`as_of_now`）时：锚点衰减 + scope 软奖惩；词法路径时间权重约 40%，Mem0 hybrid 约 20%
- `when_event`（When did…）：时间几乎不主导排序；默认自动扩 ±1 邻轮，靠事件关键词召回后由 LLM 读记忆日期作答
- scope 只做 soft boost（窗内 1.0 / 近窗 0.5 / 窗外 0.15），不硬过滤缺日期记忆
- **例外（归档时间浏览）**：用户问「某年某月问过哪些问题」时，Agent 预取对 Cold `recorded_at` 与 Warm `query_memories(time_field=recorded)` 做 **硬时间窗**；弱主题则按月列举会话摘要，禁止窗外语义噪音与臆造

## 6. 请求路径

```
用户输入 → Agent 循环（直接执行）
  ├─ JIT 预加载（画像 / 记忆 / 联网 / 工作区，合计受 LA_PREFETCH_BUDGET_CHARS 约束）
  ├─ 工具调用 → Observe 启发式压缩后再回填（LA_OBSERVE_BUDGET_CHARS；不额外调 LLM）
  └─ write_file / run_shell 执行前确认
```

天气地点：显式城市 → 档案 `居住地` → 记忆扫描 pin → 仍无则直接搜。

联网天气：`web_search` 在核对失败或命中歌词/教案等垃圾结果时自动换查询重试；agent 禁止未重试就交卷。

## 7. 记忆评测：STM / LTM

按「短期优先、长期可慢」分两套基准；产品仍是 Hot/Warm/Cold 三层，测评用 STM/LTM 二分。

| 测评层 | 产品承载 | 主基准 | 主指标 |
|--------|----------|--------|--------|
| **STM** | 当前 `history` + 近窗 `conversations/`（`LA_STM_WINDOW_HOURS`，默认 24h） | [`benchmarks/stm/`](../benchmarks/stm/README.md) | Routing / Session Hit / Coverage / Priority Win |
| **LTM-State** | Hot 画像 + Warm 事实 | LoCoMo Warm 诊断轨 + Hot 辅轨 | Warm-only hit@k；Profile Field Hit |
| **LTM-Detail** | Cold 对话原文/摘要 | LoCoMo 联合召回 | **Joint Warm∪Cold Evidence Hit@k**（主） |

分流规则（Agent JIT）：

1. `is_session_recall_query`（今天/刚才/本场/上次）→ STM：`_prefetch_session_context`（滚动窗或上一场 session），不走向量、不预取联网
2. `is_archive_recall_query`（以前/问过…）→ Cold 归档硬窗 + Warm 补充；不预取联网
3. 个人/浏览/家庭记忆 → Warm + Cold 联合预取（个人/家庭 Cold 用 `conversation_only`）；纯画像问不预取联网
4. 时效问（天气/新闻等）→ `_prefetch_web_context`；受 `LA_PREFETCH_BUDGET_CHARS` 与 observe 压缩约束

LoCoMo 主协议：`joint_recall`（Warm∪Cold RRF → dia_id 去重 → top-k）。`--mode warm_only|cold_only` 与 `--diagnostics` 仅作归因。STM 由 `tests/test_stm_benchmark.py` 进日常 `pytest` / CI；LoCoMo 可慢/夜间跑。
