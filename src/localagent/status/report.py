"""Unified `la status` / `/status` report: Daily Actions + data layers + recall note."""

from __future__ import annotations

from localagent.i18n import t
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
        t("status.section_layers"),
        *format_data_layer_detail_lines(layers),
        "",
        t("status.section_recall"),
        *format_recall_priority_lines(),
        "",
        t("status.tips_header"),
        t("status.tip_news"),
        t("status.tip_pending"),
        t("status.tip_memory"),
        t("status.tip_rag"),
        t("status.tip_tasks"),
        t("status.tip_add"),
        t("status.tip_scan"),
        t("status.tip_aware"),
        t("status.tip_aware_since"),
        t("status.tip_aware_sug"),
        t("status.tip_ungrant"),
    ]
    return "\n".join(lines)
