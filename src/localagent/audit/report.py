"""Audit report generation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from localagent.audit.events import aggregate_behavior, load_events
from localagent.audit.health import collect_memory_health
from localagent.audit.security import run_security_scan
from localagent.audit.usage import aggregate_usage, load_usage_events, parse_since
from localagent.i18n import resolve_lang, t
from localagent.workspace.context import format_workspace_summary, resolve_workspace


def _format_usage_section(stats: dict[str, Any]) -> str:
    lines = [
        t("audit.md_usage"),
        "",
        t("audit.md_calls", n=stats["total_calls"]),
        t("audit.md_tokens", n=f"{stats['total_tokens']:,}"),
        t("audit.md_cost", cost=stats["total_cost_usd"]),
        "",
    ]
    if stats["by_provider"]:
        lines.append(t("audit.md_by_provider"))
        lines.append("")
        lines.append(t("audit.md_table_provider"))
        lines.append("|----------|------|-------|----------------|")
        for name, bucket in sorted(stats["by_provider"].items()):
            lines.append(
                f"| {name} | {bucket['calls']} | {bucket['tokens']:,} | ${bucket['cost_usd']:.4f} |"
            )
        lines.append("")

    if stats["by_command"]:
        lines.append(t("audit.md_by_command"))
        lines.append("")
        for cmd, count in sorted(stats["by_command"].items(), key=lambda x: -x[1]):
            lines.append(t("audit.md_cmd_count", cmd=cmd, n=count))
        lines.append("")

    if stats["by_model"]:
        lines.append(t("audit.md_by_model"))
        lines.append("")
        lines.append(t("audit.md_table_model"))
        lines.append("|------|------|-------|----------------|")
        for name, bucket in sorted(stats["by_model"].items(), key=lambda x: -x[1]["tokens"]):
            lines.append(
                f"| {name} | {bucket['calls']} | {bucket['tokens']:,} | ${bucket['cost_usd']:.4f} |"
            )
        lines.append("")

    return "\n".join(lines)


def _format_security_section(report) -> str:
    lines = [t("audit.md_security"), ""]
    if not report.findings:
        lines.append(t("audit.md_security_none"))
        return "\n".join(lines)
    lines.append(t("audit.md_security_count", n=len(report.findings), high=report.high_count))
    lines.append("")
    lines.append(t("audit.md_table_security"))
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
        t("audit.md_behavior"),
        "",
        t("audit.md_shell", n=behavior["shell_count"]),
        t("audit.md_write", n=behavior["write_file_count"]),
        t("audit.md_web", n=behavior["web_search_count"]),
        t("audit.md_guard", n=behavior["guardrail_triggers"]),
        "",
    ]
    if behavior["outcomes"]:
        lines.append(t("audit.md_outcomes"))
        lines.append("")
        for outcome, count in sorted(behavior["outcomes"].items(), key=lambda x: -x[1]):
            lines.append(f"- `{outcome}`: {count}")
        lines.append("")
    if behavior["blocked"]:
        lines.append(t("audit.md_blocked"))
        lines.append("")
        for item in behavior["blocked"][:10]:
            reason = (item.get("reason") or "").replace("|", "\\|")
            lines.append(f"- `{item.get('tool')}`: {reason}")
        lines.append("")
    if behavior["denied"]:
        lines.append(t("audit.md_denied"))
        lines.append("")
        for item in behavior["denied"][:10]:
            reason = (item.get("reason") or "").replace("|", "\\|")
            lines.append(f"- `{item.get('tool')}`: {reason}")
        lines.append("")
    if not behavior["outcomes"] and behavior["guardrail_triggers"] == 0:
        lines.append(t("audit.md_no_behavior"))
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
    range_hint = (
        t("audit.md_range_since", since=since) if since else t("audit.md_range_all")
    )

    parts = [
        t("audit.md_title"),
        "",
        t("audit.md_generated", when=generated) + "  ",
        t("audit.md_range", range=range_hint) + "  ",
        t("audit.md_workspace", workspace=workspace),
        "",
        _format_usage_section(usage_stats),
        _format_behavior_section(behavior),
        _format_security_section(security),
        t("audit.md_memory"),
        "",
        health.to_text(),
        "",
    ]

    if include_workspace:
        parts.extend(
            [
                t("audit.md_ws_snap"),
                "",
                "```text",
                format_workspace_summary(days=workspace_days, workspace=workspace),
                "```",
                "",
            ]
        )

    parts.append("---")
    parts.append(t("audit.md_footer"))
    return "\n".join(parts)


def print_audit_summary(*, since: str | None = None, workspace_days: int = 7) -> str:
    """Interactive CLI summary (plain text)."""
    since_dt = parse_since(since) if since else None
    events = load_usage_events(since_dt)
    stats = aggregate_usage(events)
    behavior = aggregate_behavior(load_events(since_dt))
    security = run_security_scan()
    health = collect_memory_health()

    range_hint = f"（{since}）" if since and resolve_lang() == "zh" else (f" ({since})" if since else "")
    lines = [
        t("audit.summary_title", range=range_hint),
        t(
            "audit.calls_line",
            calls=stats["total_calls"],
            tokens=f"{stats['total_tokens']:,}",
            cost=stats["total_cost_usd"],
        ),
    ]
    if stats["by_provider"]:
        for name, bucket in stats["by_provider"].items():
            lines.append(
                t(
                    "audit.provider_line",
                    name=name,
                    calls=bucket["calls"],
                    tokens=f"{bucket['tokens']:,}",
                    cost=bucket["cost_usd"],
                )
            )
    lines.append("")
    lines.append(
        t(
            "audit.behavior_line",
            shell=behavior["shell_count"],
            write=behavior["write_file_count"],
            web=behavior["web_search_count"],
            guard=behavior["guardrail_triggers"],
        )
    )
    blocked_n = behavior["outcomes"].get("blocked", 0)
    denied_n = behavior["outcomes"].get("denied", 0)
    if blocked_n or denied_n:
        lines.append(t("audit.blocked_denied", blocked=blocked_n, denied=denied_n))
    lines.append("")
    lines.append(security.to_text())
    lines.append("")
    lines.append(
        t(
            "audit.memory_health_line",
            facts=health.memory_facts,
            kb=health.kb_files,
            indexed=health.indexed_files,
        )
    )
    if health.notes:
        for note in health.notes:
            lines.append(f"  ! {note}")
    lines.append("")
    lines.append(t("audit.workspace_header"))
    ws_lines = format_workspace_summary(days=workspace_days).splitlines()[:8]
    lines.extend(f"  {line}" for line in ws_lines)
    lines.append("")
    lines.append(t("audit.export_hint"))
    return "\n".join(lines)


def markdown_to_html(md: str) -> str:
    """Minimal Markdown → HTML for audit reports (no extra dependency)."""
    import html
    import re

    lang = "en" if resolve_lang() == "en" else "zh-CN"
    lines = md.splitlines()
    out: list[str] = [
        "<!DOCTYPE html>",
        f'<html lang="{lang}"><head><meta charset="utf-8"/>',
        f"<title>{t('audit.html_title')}</title>",
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
        elif line.startswith("*") and line.endswith("*") and len(line) > 2:
            out.append(f"<p><em>{html.escape(line.strip('*'))}</em></p>")
        elif line:
            out.append(f"<p>{html.escape(line)}</p>")
    if in_table:
        out.append("</table>")
    if in_code:
        out.append("</pre>")
    out.append("</body></html>")
    return "\n".join(out)


def write_report(
    path: Path | str,
    *,
    since: str | None = None,
    workspace_days: int = 7,
) -> Path:
    """Write Markdown or HTML audit report to path."""
    out = Path(path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    md = generate_report(since=since, workspace_days=workspace_days)
    if out.suffix.lower() in {".html", ".htm"}:
        out.write_text(markdown_to_html(md), encoding="utf-8")
    else:
        out.write_text(md, encoding="utf-8")
    return out
