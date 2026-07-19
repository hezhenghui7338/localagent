"""Unified `la status` / `/status` report: Daily Actions + data layers + recall note."""

from __future__ import annotations

from localagent.status.daily import (
    DailyActionsStatus,
    collect_daily_actions_status,
    format_daily_actions_lines,
)
from localagent.status.layers import (
    DataLayerStatus,
    collect_data_layer_status,
    format_data_layer_detail_lines,
    format_recall_priority_lines,
)


def format_status_report(
    *,
    daily: DailyActionsStatus | None = None,
    layers: DataLayerStatus | None = None,
) -> str:
    """Full product status: today's signals, data-layer inventory, recall order."""
    daily = daily or collect_daily_actions_status()
    layers = layers or collect_data_layer_status()
    lines = [
        "LocalAgent · Status",
        "Local First. Memory Forever. Actions Automated.",
        "",
        "── Daily Actions ──",
        *format_daily_actions_lines(daily),
        "",
        "── 数据层 ──",
        *format_data_layer_detail_lines(layers),
        "",
        "── 综合召回 ──",
        *format_recall_priority_lines(),
        "",
        "提示：",
        "  la news brief          # 今日简报",
        "  la memory pending      # 审阅待写入记忆",
        "  la memory status       # Warm / Hot 引擎诊断",
        "  la rag status          # Cold 知识库诊断",
        "  la workspace tasks     # 托管待办（done/dismiss/snooze）",
        "  la workspace add \"…\" --why \"…\"  # 显式添加待办",
        "  la workspace scan      # 诊断扫描代码 TODO（未入队）",
        "  la aware               # 当前状态 + 近 3 小时动态",
        "  la aware --since 1w    # 最近一周变化",
        "  la aware suggestion    # 感知建议（approve/reject 为其子命令）",
        "  la aware ungrant …     # 解除监测授权",
    ]
    return "\n".join(lines)
