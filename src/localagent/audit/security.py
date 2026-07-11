"""Security scan for indexed files and workspace symlinks."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from localagent import config

_SENSITIVE_NAME = re.compile(
    r"(^|/)(\.env(\.|$)|id_rsa|credentials\.json|secrets?\.(json|ya?ml)|.*\.pem$|.*\.key$)",
    re.IGNORECASE,
)
_SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "可能的 AWS Access Key"),
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "可能的 OpenAI/API sk- 密钥"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"), "私钥内容"),
]


@dataclass
class SecurityFinding:
    severity: str  # high, medium, low
    category: str
    path: str
    message: str
    remediation: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "category": self.category,
            "path": self.path,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass
class SecurityReport:
    findings: list[SecurityFinding] = field(default_factory=list)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "high")

    def to_text(self) -> str:
        if not self.findings:
            return "文件安全: 未发现高风险项"
        lines = [f"文件安全: {len(self.findings)} 项发现（高危 {self.high_count}）"]
        for item in self.findings[:20]:
            lines.append(f"  [{item.severity}] {item.path}: {item.message}")
            lines.append(f"    → {item.remediation}")
        if len(self.findings) > 20:
            lines.append(f"  … 共 {len(self.findings)} 项")
        return "\n".join(lines)


def _check_world_readable(path: Path) -> SecurityFinding | None:
    try:
        mode = path.stat().st_mode
    except OSError:
        return None
    if mode & 0o004:
        return SecurityFinding(
            severity="medium",
            category="permissions",
            path=str(path),
            message="文件对其他用户可读",
            remediation="考虑 chmod 600 或移出索引目录",
        )
    return None


def _scan_file_content(path: Path, *, max_bytes: int = 8192) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    try:
        sample = path.read_bytes()[:max_bytes].decode("utf-8", errors="ignore")
    except OSError:
        return findings
    for pattern, label in _SECRET_PATTERNS:
        if pattern.search(sample):
            findings.append(
                SecurityFinding(
                    severity="high",
                    category="secret_content",
                    path=str(path),
                    message=label,
                    remediation="从 kb/ 移除该文件，轮换已泄露密钥，检查 git 历史",
                )
            )
            break
    return findings


def scan_kb_symlinks() -> list[SecurityFinding]:
    """Scan data/kb/ symlinks for sensitive targets."""
    findings: list[SecurityFinding] = []
    kb = config.KB_DIR
    if not kb.is_dir():
        return findings

    for entry in kb.iterdir():
        target: Path | None = None
        if entry.is_symlink():
            try:
                target = entry.resolve()
            except OSError:
                findings.append(
                    SecurityFinding(
                        severity="medium",
                        category="symlink",
                        path=str(entry),
                        message="软链目标无法解析",
                        remediation="检查 LA add-file 源路径是否有效",
                    )
                )
                continue
        elif entry.is_file():
            target = entry

        if target is None:
            continue

        rel_name = entry.name
        if _SENSITIVE_NAME.search(rel_name) or _SENSITIVE_NAME.search(str(target)):
            findings.append(
                SecurityFinding(
                    severity="high",
                    category="sensitive_filename",
                    path=f"{entry} → {target}",
                    message="索引了敏感文件名（.env、密钥等）",
                    remediation="LA reset-memory 后删除 kb/ 软链，勿将密钥文件加入索引",
                )
            )

        if target.is_file():
            perm = _check_world_readable(target)
            if perm:
                perm.path = f"{entry} → {target}"
                findings.append(perm)
            findings.extend(_scan_file_content(target))

    return findings


def scan_workspace(workspace: Path | None = None) -> list[SecurityFinding]:
    """Light scan of workspace for accidentally indexed sensitive paths."""
    from localagent.workspace.context import resolve_workspace

    root = workspace or resolve_workspace()
    findings: list[SecurityFinding] = []
    env_path = root / ".env"
    if env_path.is_file() and (config.KB_DIR / ".env").exists():
        findings.append(
            SecurityFinding(
                severity="high",
                category="env_indexed",
                path=str(config.KB_DIR / ".env"),
                message="工作区 .env 已被索引到 kb/",
                remediation="删除 kb/.env 软链并 reset-memory 中相关条目",
            )
        )
    return findings


def run_security_scan(workspace: Path | None = None) -> SecurityReport:
    findings = scan_kb_symlinks() + scan_workspace(workspace)
    # Deduplicate by path+message
    seen: set[tuple[str, str]] = set()
    unique: list[SecurityFinding] = []
    for item in findings:
        key = (item.path, item.message)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(key=lambda f: {"high": 0, "medium": 1, "low": 2}[f.severity])
    return SecurityReport(findings=unique)
