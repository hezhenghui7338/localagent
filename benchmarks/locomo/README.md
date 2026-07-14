# LoCoMo × LocalAgent 长期记忆评测

用 ACL 2024 基准 [LoCoMo](https://github.com/snap-research/locomo)（*Evaluating Very Long-Term Conversational Memory of LLM Agents*）衡量 LocalAgent Warm 层记忆（JSON / Mem0）的长期召回与问答能力。

## Benchmark 结果（当前）

> **主指标 = 证据召回 hit@k**：问题对应的 gold dialog（`evidence`）是否出现在 `recall` 的 top-k 中。  
> 这直接反映 LA 的长期记忆检索能力；端到端 QA F1 受答题模型影响，仅作辅证。

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
- **Multi-hop** Hit@1 提升明显（0.125 → 0.344）：cross-encoder 把池内证据更稳地排到第一。
- **Single-hop** 中等偏上（Hit@5 ≈ 0.57）：混合检索 + rerank 对字面重叠题更稳。
- **Open-domain** Hit@5 已到 0.64，但题量少、仍偏弱：跨轮综合与语义改写仍是改进重点。

复现本表（需已入库的 `locomo-mem0` work-dir；默认 hybrid + `LA_MEMORY_RERANK_BACKEND=cross_encoder`）：

```bash
python -m benchmarks.locomo.measure_recall \
  --skip-ingest --sample-ids conv-26 \
  --work-dir benchmarks/data/runs/locomo-mem0 \
  --out benchmarks/data/runs/locomo-mem0/recall_hitk_rerank.json
```

### 辅证：端到端 QA F1

| 项目 | 值 |
|------|-----|
| 设置 | Mem0 `recall_generate` + provider=`cursor`（composer-2.5），top_k=8，n=152 |
| Overall F1 | **0.339** |
| 产物 | [`results_recall_generate_cursor.json`](../data/runs/locomo-mem0/results_recall_generate_cursor.json) |

> QA F1 受答题模型影响，仅作辅证；正式对比长期记忆能力请以 hit@k 为主。该 F1 跑于 hybrid 复测前的同一 Mem0 库，未在 hybrid 上重跑全量答题。

## 评测协议

对每段超长多 session 对话：

1. **Ingest**：把每条 dialog turn 写成记忆（`retain`），隔离到独立 `LA_DATA_DIR`
2. **Recall**：用问题查询记忆（`recall`，top-k）
3. **Answer**（可选）：用召回上下文让 LLM 生成短答案（对齐 LoCoMo RAG）
4. **Score**：召回用证据 hit@k；问答按官方 `task_eval/evaluation.py` 算 F1

| category | 名称 | QA 计分 |
|----------|------|------|
| 1 | multi-hop | 逗号拆分子答案后平均 F1 |
| 2 | temporal | token F1 |
| 3 | open-domain | token F1（gold 取 `;` 前段） |
| 4 | single-hop | token F1 |
| 5 | adversarial | 正确弃答得 1，否则 0（召回评测默认跳过） |

## 主指标：记忆召回 hit@k

```bash
python -m benchmarks.locomo.measure_recall \
  --skip-ingest --sample-ids conv-26 \
  --work-dir benchmarks/data/runs/locomo-mem0
```

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
  --work-dir benchmarks/data/runs/locomo-mem0

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
