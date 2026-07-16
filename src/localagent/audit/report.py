"""Audit report generation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from localagent.audit.events import aggregate_behavior, load_events
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


def _format_behavior_section(behavior: dict[str, Any]) -> str:
    lines = [
        "## Agent 行为与护栏",
        "",
        f"- 本地命令 `run_shell`: {behavior['shell_count']} 次",
        f"- 写文件 `write_file`: {behavior['write_file_count']} 次",
        f"- 联网查询 `web_search`: {behavior['web_search_count']} 次",
        f"- 护栏触发: {behavior['guardrail_triggers']} 次",
        "",
    ]
    if behavior["outcomes"]:
        lines.append("### 工具决策结果")
        lines.append("")
        for outcome, count in sorted(behavior["outcomes"].items(), key=lambda x: -x[1]):
            lines.append(f"- `{outcome}`: {count}")
        lines.append("")
    if behavior["blocked"]:
        lines.append("### 本周期拦截")
        lines.append("")
        for item in behavior["blocked"][:10]:
            reason = (item.get("reason") or "").replace("|", "\\|")
            lines.append(f"- `{item.get('tool')}`: {reason}")
        lines.append("")
    if behavior["denied"]:
        lines.append("### 用户拒绝")
        lines.append("")
        for item in behavior["denied"][:10]:
            reason = (item.get("reason") or "").replace("|", "\\|")
            lines.append(f"- `{item.get('tool')}`: {reason}")
        lines.append("")
    if not behavior["outcomes"] and behavior["guardrail_triggers"] == 0:
        lines.append("暂无行为事件记录。")
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
    behavior = aggregate_behavior(load_events(since_dt))
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
        _format_behavior_section(behavior),
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
    behavior = aggregate_behavior(load_events(since_dt))
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
    lines.append(
        f"行为: shell={behavior['shell_count']}  write={behavior['write_file_count']}  "
        f"web={behavior['web_search_count']}  护栏={behavior['guardrail_triggers']}"
    )
    blocked_n = behavior["outcomes"].get("blocked", 0)
    denied_n = behavior["outcomes"].get("denied", 0)
    if blocked_n or denied_n:
        lines.append(f"  拦截 blocked={blocked_n}  拒绝 denied={denied_n}")
    lines.append("")
    lines.append(security.to_text())
    lines.append("")
    lines.append(
        f"记忆健康: facts={health.memory_facts} · kb={health.kb_files} · "
        f"indexed={health.indexed_files}"
    )
    if health.notes:
        for note in health.notes:
            lines.append(f"  ! {note}")
    lines.append("")
    lines.append("工作区（摘要）:")
    ws_lines = format_workspace_summary(days=workspace_days).splitlines()[:8]
    lines.extend(f"  {line}" for line in ws_lines)
    lines.append("")
    lines.append("→ LA audit --report report.md  导出 Markdown；--report report.html 导出 HTML")
    return "\n".join(lines)


def markdown_to_html(md: str) -> str:
    """Minimal Markdown → HTML for audit reports (no extra dependency)."""
    import html
    import re

    lines = md.splitlines()
    out: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN"><head><meta charset="utf-8"/>',
        "<title>LocalAgent 审计报告</title>",
        "<style>",
        "body{font-family:system-ui,-apple-system,sans-serif;max-width:900px;"
        "margin:2rem auto;padding:0 1rem;line-height:1.5;color:#1a1a1a}",
        "table{border-collapse:collapse;width:100%;margin:1rem 0}",
        "th,td{border:1px solid #ccc;padding:0.4rem 0.6rem;text-align:left}",
        "th{background:#f4f4f4}",
        "code{background:#f0f0f0;padding:0.1rem 0.3rem;border-radius:3px}",
        "pre{background:#f6f8fa;padding:0.8rem;overflow:auto}",
        "h1,h2,h3{margin-top:1.4rem}",
        "</style></head><body>",
    ]
    in_code = False
    in_table = False
    for raw in lines:
        line = raw.rstrip()
        if line.startswith("```"):
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                out.append("<pre>")
                in_code = True
            continue
        if in_code:
            out.append(html.escape(line))
            continue
        if line.startswith("|") and "|" in line[1:]:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells):
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                out.append("<table>")
                in_table = True
            row = "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells)
            out.append(f"<tr>{row}</tr>")
            continue
        if in_table:
            out.append("</table>")
            in_table = False
        if line.startswith("# "):
            out.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("- "):
            out.append(f"<li>{html.escape(line[2:])}</li>")
        elif line.strip() == "---":
            out.append("<hr/>")
        elif line.strip() == "":
            out.append("<br/>")
        else:
            # light inline code
            escaped = html.escape(line)
            escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
            out.append(f"<p>{escaped}</p>")
    if in_table:
        out.append("</table>")
    if in_code:
        out.append("</pre>")
    out.append("</body></html>")
    return "\n".join(out)


def write_report(path: Path, *, since: str | None = None, workspace_days: int = 7) -> Path:
    content = generate_report(since=since, workspace_days=workspace_days)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".html", ".htm"}:
        path.write_text(markdown_to_html(content), encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")
    return path
