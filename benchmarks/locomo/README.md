# LoCoMo × LocalAgent 长期记忆评测

用 ACL 2024 基准 [LoCoMo](https://github.com/snap-research/locomo)（*Evaluating Very Long-Term Conversational Memory of LLM Agents*）衡量 LocalAgent **长期记忆（LTM）**：Warm 事实 + Cold 对话细节的联合召回与问答能力。

短期记忆（会话内 / 当日）见并列套件 **[../stm/README.md](../stm/README.md)**。

历次跑分与配置差异见 **[HISTORY.md](HISTORY.md)**（只追加、不覆盖）。本页只维护**当前主结果**。

## Benchmark 结果（当前）

> **主指标 = Joint Warm∪Cold 证据 hit@k**：`joint_recall`（双向 RRF）后，gold dialog（`evidence`）是否出现在 top-k。  
> Warm-only / Cold-only 为诊断轨（`--diagnostics` 或 `--mode warm_only|cold_only`）。  
> 端到端 QA F1 受答题模型影响，仅作辅证。

> **当前表状态（2026-07-16）**：评测**协议**已切换为 Joint RRF；下表数字仍是 2026-07-14 **Warm-only / 旧 backfill** 历史对照，**不是** Joint 正式主基线。  
> Joint 正式分表待在带 cross-encoder 的环境对 `locomo-mem0/conv-26` 重跑后替换（见 HISTORY）。实验轨可参考 `locomo-mem0-layered`（Hit@1=0.360 / Hit@8=0.727），**不升格为主表**。
| 项目 | 值 |
|------|-----|
| 日期 | 2026-07-14 |
| 样本 | LoCoMo `conv-26`（19 sessions / 419 turns / 199 QA） |
| 记忆后端 | Mem0 hybrid（向量 + 词法 RRF + `finalize_hybrid_rank`）+ cross-encoder rerank |
| 入库条数 | 420（含 conversation meta） |
| 评测题量 | **150**（排除 adversarial cat5；仅统计有 `evidence` 的题） |
| 产物 | [`benchmarks/data/runs/locomo-mem0/recall_hitk_rerank.json`](../data/runs/locomo-mem0/recall_hitk_rerank.json) |

### 证据召回 hit@k

| Category | 名称 | n | Hit@1 | Hit@5 | Hit@8 |
|----------|------|--:|------:|------:|------:|
| overall | — | 150 | **0.433** | **0.627** | **0.673** |
| 4 | single-hop | 70 | 0.371 | 0.571 | 0.614 |
| 2 | temporal | 37 | 0.676 | 0.784 | 0.784 |
| 1 | multi-hop | 32 | 0.344 | 0.563 | 0.688 |
| 3 | open-domain | 11 | 0.273 | 0.636 | 0.636 |

**读数要点**

- **Temporal** 最好（Hit@5 ≈ 0.78）：时间意图 + session 时间戳，时间类问题更容易命中。
- **Multi-hop** Hit@1 相对早期 hybrid（0.125）提升到 0.344：cross-encoder 把池内证据更稳地排到第一。
- **Single-hop** 中等偏上（Hit@5 ≈ 0.57）：混合检索 + rerank 对字面重叠题更稳。
- **Open-domain** Hit@5 已到 0.64，但题量少、仍偏弱：跨轮综合与语义改写仍是改进重点。

**关系图默认关闭**（产品默认走 hybrid + CE）。开图为可选实验：`LA_MEMORY_GRAPH=1` + `PROTECT_TOP=1` + `FORCE_IN_TOP=3` + `BOOST=0`，且必须装 CE（`pip install 'la-localagent[rerank]'`）。  
相对无图 CE：Hit@1 持平（0.433），Hit@5/8 仅小幅上升 — 见 [HISTORY.md § graph protect](HISTORY.md#2026-07-14--graph-protect--force-inject--cross-encoder推荐开图配置)。说明见主文档 README「Optional Warm relation graph」。

### 辅证：端到端 QA F1

| 项目 | 值 |
|------|-----|
| 设置 | Mem0 `recall_generate` + provider=`cursor`（composer-2.5），top_k=8，n=152 |
| Overall F1 | **0.339** |
| 产物 | [`results_recall_generate_cursor.json`](../data/runs/locomo-mem0/results_recall_generate_cursor.json) |

> QA F1 受答题模型影响，仅作辅证；正式对比长期记忆能力请以 hit@k 为主。

## 如何追加一次新评测（勿覆盖旧 JSON）

```bash
# 默认写出带时间戳的文件：recall_hitk_YYYYMMDD_HHMMSS.json
python -m benchmarks.locomo.measure_recall \
  --skip-ingest --sample-ids conv-26 \
  --work-dir benchmarks/data/runs/locomo-mem0 \
  --label rerank

# 或显式指定路径（请用新文件名，不要复用旧产物名）
python -m benchmarks.locomo.measure_recall \
  --skip-ingest --sample-ids conv-26 \
  --work-dir benchmarks/data/runs/locomo-mem0 \
  --out benchmarks/data/runs/locomo-mem0/recall_hitk_20260714_graph_v2.json
```

跑完后：

1. 在 [HISTORY.md](HISTORY.md) **顶部**追加一节（配置 + 分表 + 产物路径）。
2. 若该次成为新的「主结果」，再更新本页「Benchmark 结果（当前）」表。

## 评测协议

对每段超长多 session 对话：

1. **Ingest**：把每条 dialog turn 写入 Warm（`retain`）并索引 Cold；隔离到独立 `LA_DATA_DIR`。可选 `--incremental-sessions` 按 session 分批 retain。
2. **Recall（主）**：`joint_recall` = Warm pool + Cold `conversation_only` → RRF 融合 → `dia_id` 去重 → top-k
3. **Answer**（可选）：用联合召回上下文让 LLM 生成短答案（对齐 LoCoMo RAG）
4. **Score**：召回用证据 hit@k；问答按官方 `task_eval/evaluation.py` 算 F1
5. **Hot 辅轨**：`python -m benchmarks.locomo.measure_profile`（画像字段 EM，不进 hit@k）

| category | 名称 | QA 计分 |
|----------|------|------|
| 1 | multi-hop | 逗号拆分子答案后平均 F1 |
| 2 | temporal | token F1 |
| 3 | open-domain | token F1（gold 取 `;` 前段） |
| 4 | single-hop | token F1 |
| 5 | adversarial | 正确弃答得 1，否则 0（召回评测默认跳过） |

## 快速开始

```bash
# 在仓库根目录
pip install -e ".[dev]"
pip install nltk   # 与官方一致的 Porter stemmer（无则自动降级）

# 1) 下载官方数据 (~2.8MB)
python -m benchmarks.locomo.run download

# 2) 入库 + 测召回（推荐作为记忆能力主流程；默认 Mem0 hybrid）
python -m benchmarks.locomo.run run \
  --sample-ids conv-26 --mode recall --max-questions 1 \
  --work-dir benchmarks/data/runs/locomo-mem0
python -m benchmarks.locomo.measure_recall \
  --skip-ingest --sample-ids conv-26 \
  --work-dir benchmarks/data/runs/locomo-mem0 \
  --diagnostics --label joint_smoke

# 3) 可选：端到端 QA（依赖 LLM provider）
python -m benchmarks.locomo.run run \
  --sample-ids conv-26 --max-questions 20 \
  --mode recall_generate --provider cursor \
  --skip-ingest --work-dir benchmarks/data/runs/locomo-mem0
```

## 答题模式

| `--mode` | 行为 |
|----------|------|
| `recall` | 仅拼接 top-k 记忆文本（测检索覆盖，不调用生成） |
| `recall_generate` | 召回 + LLM 短答（默认，对齐 LoCoMo RAG） |
| `reflect` | 走 `LA reflect`（Mem0 search + LLM；JSON 后端会降级为 recall） |

常用筛选：

```bash
# 只测时间推理 + 单跳
python -m benchmarks.locomo.run run --categories 2 4 --max-samples 1

# 已 ingest 过，只重跑答题
python -m benchmarks.locomo.run run --skip-ingest --sample-ids conv-26

# 限制 ingest 轮数（调试用）
python -m benchmarks.locomo.run run --max-turns 100 --max-questions 10 --max-samples 1
```

## 环境注意

- 评测会为每个 `sample_id` 创建独立数据目录，**不会写入**日常 `data/`。
- `recall_generate` / `reflect` 依赖当前 `config/model_servers.yaml`（或 `.env`）里可用的补全模型。
- 默认 Mem0；`LA_MEMORY_BACKEND=json` 时用 JSON + `scoped_recall`。
- 官方数据仅用于研究评测，请遵守 [LoCoMo](https://github.com/snap-research/locomo) 许可与引用要求。

## 引用

```bibtex
@article{maharana2024evaluating,
  title={Evaluating very long-term conversational memory of llm agents},
  author={Maharana, Adyasha and Lee, Dong-Ho and Tulyakov, Sergey and Bansal, Mohit and Barbieri, Francesco and Fang, Yuwei},
  journal={arXiv preprint arXiv:2402.17753},
  year={2024}
}
```
