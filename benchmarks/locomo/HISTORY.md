# LoCoMo 评测历史

按时间归档的 hit@k 跑分。主文档只保留[当前结果](README.md)；本文件追加记录，**不覆盖**旧条目。

约定：

- 原始 JSON 留在 `benchmarks/data/runs/<work-dir>/`，文件名带标签或时间戳，避免互相覆盖。
- 新跑完一次后：在本文件**顶部**追加一节，并按需更新 [README.md](README.md) 的「当前」表。

样本除非另注，均为 `conv-26`，题量 150（排除 adversarial cat5；仅有 `evidence` 的题），入库 420 条。

---

## 2026-07-16 · 主协议升级为 Joint Warm∪Cold RRF

| 项目 | 值 |
|------|-----|
| 变更 | `measure_recall` 默认 `mode=joint`：`joint_recall` = Warm∪Cold 双向 RRF + dia_id 去重；`--mode warm_only\|cold_only` 与 `--diagnostics` 作归因 |
| 产品对齐 | 个人/家庭记忆预取默认联合 Cold（`conversation_only`）；STM 分流不变（见 `benchmarks/stm/`） |
| 辅轨 | `--incremental-sessions`；`python -m benchmarks.locomo.measure_profile`（Hot Profile Field Hit） |
| Joint 基线 | **协议已切 Joint**；正式分表仍待对 `locomo-mem0/conv-26` 重跑（需 CE：`pip install 'la-localagent[rerank]'`）。当前 README 主表数字为 Warm-only **历史对照**，勿当成 Joint。临时实验轨见下方 layered（不升格） |

```bash
python -m benchmarks.locomo.measure_recall \
  --skip-ingest --sample-ids conv-26 \
  --work-dir benchmarks/data/runs/locomo-mem0 \
  --diagnostics --label joint_rrf
```

对照：此前 README 主结果（Warm-only / 旧 Warm-优先 backfill）overall Hit@1=0.433 / Hit@5=0.627 / Hit@8=0.673（2026-07-14 `recall_hitk_rerank.json`）。

### 2026-07-16 实验轨：`locomo-mem0-layered`（Cold 入库 + entities/slots + 弃答重召回）

| 项目 | 值 |
|------|-----|
| work-dir | `benchmarks/data/runs/locomo-mem0-layered`（439 Warm facts + Cold locomo chunks） |
| 产物 | [`recall_hitk_20260716_102042_layered_graph.json`](../data/runs/locomo-mem0-layered/recall_hitk_20260716_102042_layered_graph.json) |
| 配置 | Joint 路径 + graph protect；Mem0 Qdrant 锁冲突时 JSON fallback + CE |

| Category | n | Hit@1 | Hit@5 | Hit@8 |
|----------|--:|------:|------:|------:|
| overall | 150 | 0.360 | 0.620 | **0.727** |
| multi-hop | 32 | 0.063 | 0.500 | **0.750** |
| temporal | 37 | **0.703** | **0.838** | **0.865** |
| open-domain | 11 | 0.273 | 0.455 | 0.636 |
| single-hop | 70 | 0.329 | 0.586 | 0.657 |

相对 07-14 主结果：Hit@8 / temporal 抬升；multi-hop Hit@1 回退（摘要/干扰占 top-1）。**不替换 README 主表**。配套代码：`joint_recall`、Cold ingest、entities/slots 保留、弃答 follow-up、`SAID_ABOUT` 图边。

---

## 2026-07-14 · memory_class 软加权回归（Phase A）

| 项目 | 值 |
|------|-----|
| 配置 | Mem0 hybrid + CE rerank + `LA_MEMORY_RECALL_CLASS_BOOST=1` / `LA_MEMORY_CLASS_WEIGHT=0.10`；`LA_MEMORY_GRAPH=0` |
| 对照 | 同日主结果 `recall_hitk_rerank.json`（无 class boost） |
| 产物 | [`recall_hitk_20260714_185804_memory_class.json`](../data/runs/locomo-mem0/recall_hitk_20260714_185804_memory_class.json) |

| Category | 名称 | n | Hit@1 | Hit@5 | Hit@8 |
|----------|------|--:|------:|------:|------:|
| overall | — | 150 | **0.433** | **0.627** | **0.673** |
| 1 | multi-hop | 32 | 0.344 | 0.563 | 0.688 |
| 2 | temporal | 37 | 0.676 | 0.784 | 0.784 |
| 3 | open-domain | 11 | 0.273 | 0.636 | 0.636 |
| 4 | single-hop | 70 | 0.371 | 0.571 | 0.614 |

**结论**：与无 class boost 的 CE 基线**逐类完全一致**。LoCoMo 入库几乎全是带 `dia_id` 的情景条，class 对齐分为常数，不改变相对排序——符合预期（无回归，亦无在纯情景库上抬分）。收益应在「语义事实 + 情景日记」混池场景验证。

---

## 2026-07-14 · graph protect + force-inject + cross-encoder（推荐开图配置）

| 项目 | 值 |
|------|-----|
| 配置 | Mem0 hybrid + CE rerank + `LA_MEMORY_GRAPH=1` / `HOPS=2` / `BOOST=0` / `PROTECT_TOP=1` / `FORCE_IN_TOP=3`；宽池 rerank 后再裁 top-k |
| 对照 | 同日 `recall_hitk_rerank_ce.json`（无图 + CE） |
| 产物 | [`recall_hitk_graph_protect_force_wide_ce.json`](../data/runs/locomo-mem0/recall_hitk_graph_protect_force_wide_ce.json) |

| Category | 名称 | n | Hit@1 | Hit@5 | Hit@8 | vs 无图 CE |
|----------|------|--:|------:|------:|------:|-----------|
| overall | — | 150 | **0.433** | **0.633** | **0.680** | @1 持平；@5 +0.7pp；@8 +0.7pp |
| 1 | multi-hop | 32 | **0.344** | 0.563 | **0.719** | @1 持平；@8 +3.1pp |
| 2 | temporal | 37 | 0.676 | **0.811** | **0.811** | @5/@8 +2.7pp |
| 3 | open-domain | 11 | 0.273 | 0.636 | 0.636 | 持平 |
| 4 | single-hop | 70 | 0.371 | 0.571 | 0.600 | @8 −1.4pp |

**结论**：seed-only 精排后保护 #1，再把图扩展强制塞进 #2…，可在**不掉 Hit@1** 的前提下小幅抬高 Hit@5/8。依赖 `sentence-transformers`（`pip install 'la-localagent[rerank]'`）；CE 缺失时 Hit@1 会静默掉到 ~0.35。

---

## 2026-07-14 · 诊断笔记（CE 缺失时的假象）

下午若干跑分（`recall_hitk_graph.json` / `graph_protect*` / `rerank_recheck`）在 **CrossEncoder 未加载**（当时 venv 无 `sentence-transformers`）下完成，分数与无精排 hybrid 相同（overall @1≈0.347）。此前相对 `recall_hitk_rerank.json`（@1=0.433）的「开图 Hit@1 暴跌 / Hit@5 大涨」**不能**当作图层因果——主要是 CE 开/关混比。已在 `rerank.py` 对 CE 不可用打 **warning**。

---

## 2026-07-14 · memory graph hop（实验，无 CE，勿作对照）

| 项目 | 值 |
|------|-----|
| 配置 | Mem0 hybrid + cross-encoder + `LA_MEMORY_GRAPH=1` / `HOPS=2` |
| 图规模 | 974 entities / 400 relations / 420 facts |
| 产物 | [`recall_hitk_graph.json`](../data/runs/locomo-mem0/recall_hitk_graph.json) |

| Category | 名称 | n | Hit@1 | Hit@5 | Hit@8 |
|----------|------|--:|------:|------:|------:|
| overall | — | 150 | 0.347 | 0.653 | 0.740 |
| 1 | multi-hop | 32 | 0.094 | 0.688 | 0.750 |
| 2 | temporal | 37 | 0.622 | 0.784 | 0.892 |
| 3 | open-domain | 11 | 0.182 | 0.455 | 0.636 |
| 4 | single-hop | 70 | 0.343 | 0.600 | 0.671 |

相对同日 rerank 基线：Hit@5/8 上升（multi-hop Hit@5 +12.5pp），Hit@1 明显回退（图边噪声挤占 top-1）。

---

## 2026-07-14 · hybrid + cross-encoder rerank（当前主结果）

| 项目 | 值 |
|------|-----|
| 配置 | Mem0 hybrid（向量 + 词法 RRF + `finalize_hybrid_rank`）+ `LA_MEMORY_RERANK_BACKEND=cross_encoder` |
| 产物 | [`recall_hitk_rerank.json`](../data/runs/locomo-mem0/recall_hitk_rerank.json) |

| Category | 名称 | n | Hit@1 | Hit@5 | Hit@8 |
|----------|------|--:|------:|------:|------:|
| overall | — | 150 | **0.433** | **0.627** | **0.673** |
| 1 | multi-hop | 32 | 0.344 | 0.563 | 0.688 |
| 2 | temporal | 37 | 0.676 | 0.784 | 0.784 |
| 3 | open-domain | 11 | 0.273 | 0.636 | 0.636 |
| 4 | single-hop | 70 | 0.371 | 0.571 | 0.614 |

读数：Temporal 最好；multi-hop Hit@1 相对早期 hybrid 从 0.125 升到 0.344（rerank 把池内证据排到第一）。

辅证 QA F1（同库更早一次 `recall_generate` + cursor）：Overall **0.339** → [`results_recall_generate_cursor.json`](../data/runs/locomo-mem0/results_recall_generate_cursor.json)。

---

## 2026-07-14 · phase_a（中间实验）

| 项目 | 值 |
|------|-----|
| 产物 | [`recall_hitk_phase_a.json`](../data/runs/locomo-mem0/recall_hitk_phase_a.json) |

| Category | n | Hit@1 | Hit@5 | Hit@8 |
|----------|--:|------:|------:|------:|
| overall | 150 | 0.347 | 0.653 | 0.740 |
| 1 multi-hop | 32 | 0.094 | 0.688 | 0.750 |
| 2 temporal | 37 | 0.622 | 0.784 | 0.892 |
| 3 open-domain | 11 | 0.182 | 0.455 | 0.636 |
| 4 single-hop | 70 | 0.343 | 0.600 | 0.671 |

---

## 2026-07-14 · hybrid（无 cross-encoder）

| 项目 | 值 |
|------|-----|
| 配置 | Mem0 hybrid，未开 cross-encoder rerank |
| 产物 | [`recall_hitk_hybrid.json`](../data/runs/locomo-mem0/recall_hitk_hybrid.json) |

| Category | n | Hit@1 | Hit@5 | Hit@8 |
|----------|--:|------:|------:|------:|
| overall | 150 | 0.360 | 0.573 | 0.660 |
| 1 multi-hop | 32 | 0.125 | 0.500 | 0.625 |
| 2 temporal | 37 | 0.649 | 0.730 | 0.811 |
| 3 open-domain | 11 | 0.182 | 0.455 | 0.455 |
| 4 single-hop | 70 | 0.343 | 0.543 | 0.629 |

---

## 2026-07-13 · 初测

| 项目 | 值 |
|------|-----|
| 产物 | [`recall_hitk.json`](../data/runs/locomo-mem0/recall_hitk.json) |

| Category | n | Hit@1 | Hit@5 | Hit@8 |
|----------|--:|------:|------:|------:|
| overall | 150 | 0.353 | 0.520 | 0.667 |
| 1 multi-hop | 32 | 0.156 | 0.375 | 0.438 |
| 2 temporal | 37 | 0.486 | 0.703 | 0.865 |
| 3 open-domain | 11 | 0.364 | 0.455 | 0.727 |
| 4 single-hop | 70 | 0.371 | 0.500 | 0.657 |
