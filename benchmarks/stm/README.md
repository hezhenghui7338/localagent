# LocalAgent 短期记忆（STM）评测

与 [LoCoMo 长期记忆评测](../locomo/README.md) 并列：**STM 高优先、可 CI、无强依赖大模型**。

原则：刚发生的事必须清楚；「今天/刚才/上次」走会话 transcript（STM 滚动窗，默认 24h，`LA_STM_WINDOW_HOURS`），不依赖 Warm/Cold 向量。

## 场景

| ID | 场景 | 主指标 |
|----|------|--------|
| S1 | 会话内工作记忆（`history`） | Context Coverage / Answer Hit |
| S2 | 近窗 / 上一场会话回顾（`persist/conversations`） | Session Hit + 路由正确 |
| S3 | STM 优先于过时 Warm | Priority Win Rate |
| Hot | 画像字段持久化（辅） | Profile Field Hit |

路由子集同时校验 `is_session_recall_query` vs `is_archive_recall_query`。

## 通过线

| 指标 | 门槛 |
|------|------|
| Routing Accuracy | ≥ 0.95 |
| Session Hit | ≥ 0.90 |
| In-session Coverage | ≥ 0.95 |
| Priority Win Rate | ≥ 0.90 |

## 运行

```bash
# CI / 日常（秒级）
python -m benchmarks.stm

# 或
python -m benchmarks.stm.run --fixture benchmarks/stm/fixtures/cases.json
```

产物默认写入 `benchmarks/data/runs/stm/stm_YYYYMMDD_HHMMSS.json`。

## 与 LTM 的边界

- **STM**：当前 `history` + 近 `LA_STM_WINDOW_HOURS`（默认 24）小时内 conversations；问题形态如「今天聊了啥」「刚才说了什么」「上次对话问了啥」。
- **LTM**：跨会话事实 / 归档 → [LoCoMo](../locomo/README.md)，主协议为 Warm∪Cold 联合 top-k。
