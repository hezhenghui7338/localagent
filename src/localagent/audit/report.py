"""Audit report generation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from localagent.audit.health import collect_memory_health
from localagent.audit.security import run_security_scan
from localagent.audit.usage import aggregate_usage, load_usage_events, parse_since
from localagent.workspace.context import format_workspace_summary, resolve_workspace


def _format_usage_section(stats: dict[str, Any]) -> str:
    lines = [
        "## Token 与服务花费",
        "",
        f"- 调用次数: {stats['total_calls']}",
        f"- Token 合计: {stats['total_tokens']:,}",
        f"- 估算费用 (USD): ${stats['total_cost_usd']:.4f}",
        "",
    ]
    if stats["by_provider"]:
        lines.append("### 按 Provider")
        lines.append("")
        lines.append("| Provider | 调用 | Token | 估算费用 (USD) |")
        lines.append("|----------|------|-------|----------------|")
        for name, bucket in sorted(stats["by_provider"].items()):
            lines.append(
                f"| {name} | {bucket['calls']} | {bucket['tokens']:,} | ${bucket['cost_usd']:.4f} |"
            )
        lines.append("")

    if stats["by_command"]:
        lines.append("### 按命令类型")
        lines.append("")
        for cmd, count in sorted(stats["by_command"].items(), key=lambda x: -x[1]):
            lines.append(f"- `{cmd}`: {count} 次")
        lines.append("")

    if stats["by_model"]:
        lines.append("### 按模型")
        lines.append("")
        lines.append("| 模型 | 调用 | Token | 估算费用 (USD) |")
        lines.append("|------|------|-------|----------------|")
        for name, bucket in sorted(stats["by_model"].items(), key=lambda x: -x[1]["tokens"]):
            lines.append(
                f"| {name} | {bucket['calls']} | {bucket['tokens']:,} | ${bucket['cost_usd']:.4f} |"
            )
        lines.append("")

    return "\n".join(lines)


def _format_security_section(report) -> str:
    lines = ["## 文件安全", ""]
    if not report.findings:
        lines.append("未发现高风险项。")
        return "\n".join(lines)
    lines.append(f"共 {len(report.findings)} 项（高危 {report.high_count}）")
    lines.append("")
    lines.append("| 级别 | 路径 | 说明 | 建议 |")
    lines.append("|------|------|------|------|")
    for item in report.findings:
        path = item.path.replace("|", "\\|")
        msg = item.message.replace("|", "\\|")
        fix = item.remediation.replace("|", "\\|")
        lines.append(f"| {item.severity} | `{path}` | {msg} | {fix} |")
    lines.append("")
    return "\n".join(lines)


def generate_report(
    *,
    since: str | None = None,
    workspace_days: int = 7,
    include_workspace: bool = True,
) -> str:
    """Build full Markdown audit report."""
    since_dt = parse_since(since) if since else None
    events = load_usage_events(since_dt)
    usage_stats = aggregate_usage(events)
    security = run_security_scan()
    health = collect_memory_health()
    workspace = resolve_workspace()

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    range_hint = f"（自 {since}）" if since else "（全部记录）"

    parts = [
        "# LocalAgent 审计报告",
        "",
        f"生成时间: {generated}  ",
        f"统计范围: {range_hint}  ",
        f"工作区: `{workspace}`",
        "",
        _format_usage_section(usage_stats),
        _format_security_section(security),
        "## 记忆健康",
        "",
        health.to_text(),
        "",
    ]

    if include_workspace:
        parts.extend(
            [
                "## 工作区快照",
                "",
                "```text",
                format_workspace_summary(days=workspace_days, workspace=workspace),
                "```",
                "",
            ]
        )

    parts.append("---")
    parts.append("*费用为基于默认单价的估算，可在 .env 中设置 LA_COST_* 覆盖。*")
    return "\n".join(parts)


def print_audit_summary(*, since: str | None = None, workspace_days: int = 7) -> str:
    """Interactive CLI summary (plain text)."""
    since_dt = parse_since(since) if since else None
    events = load_usage_events(since_dt)
    stats = aggregate_usage(events)
    security = run_security_scan()
    health = collect_memory_health()

    range_hint = f"（{since}）" if since else ""
    lines = [
        f"[audit] 摘要{range_hint}",
        f"  调用: {stats['total_calls']}  Token: {stats['total_tokens']:,}  "
        f"估算费用: ${stats['total_cost_usd']:.4f}",
    ]
    if stats["by_provider"]:
        for name, bucket in stats["by_provider"].items():
            lines.append(
                f"    {name}: {bucket['calls']} 次, {bucket['tokens']:,} tokens, "
                f"${bucket['cost_usd']:.4f}"
            )
    lines.append("")
    lines.append(security.to_text())
    lines.append("")
    lines.append(f"记忆健康: facts={health.memory_facts}")
    if health.notes:
        for note in health.notes:
            lines.append(f"  ! {note}")
    lines.append("")
    lines.append("工作区（摘要）:")
    ws_lines = format_workspace_summary(days=workspace_days).splitlines()[:8]
    lines.extend(f"  {line}" for line in ws_lines)
    lines.append("")
    lines.append("→ LA audit --report report.md  导出完整报告")
    return "\n".join(lines)


def write_report(path: Path, *, since: str | None = None, workspace_days: int = 7) -> Path:
    content = generate_report(since=since, workspace_days=workspace_days)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
