"""Security scan for indexed files and workspace symlinks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from localagent import config
from localagent.i18n import t

SENSITIVE_NAME_RE = re.compile(
    r"(^|/)(\.env(\.|$)|id_rsa|credentials\.json|secrets?\.(json|ya?ml)|.*\.pem$|.*\.key$)",
    re.IGNORECASE,
)
# Back-compat alias
_SENSITIVE_NAME = SENSITIVE_NAME_RE
_SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "audit.sec_aws_key"),
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "audit.sec_openai_key"),
    (re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"), "audit.sec_private_key"),
]


def is_sensitive_path(path: str | Path) -> bool:
    """True if basename/path looks like secrets (.env, keys, credentials)."""
    text = str(path)
    name = Path(text).name
    return bool(SENSITIVE_NAME_RE.search(name) or SENSITIVE_NAME_RE.search(text))


def sensitive_path_reason(path: str | Path) -> str:
    return t("audit.sec_path_blocked", name=Path(path).name)


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
            return t("audit.sec_ok")
        lines = [t("audit.sec_header", n=len(self.findings), high=self.high_count)]
        for item in self.findings[:20]:
            lines.append(f"  [{item.severity}] {item.path}: {item.message}")
            lines.append(f"    → {item.remediation}")
        if len(self.findings) > 20:
            lines.append(t("audit.sec_more", n=len(self.findings)))
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
            message=t("audit.sec_world_readable"),
            remediation=t("audit.sec_world_fix"),
        )
    return None


def _scan_file_content(path: Path, *, max_bytes: int = 8192) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    try:
        sample = path.read_bytes()[:max_bytes].decode("utf-8", errors="ignore")
    except OSError:
        return findings
    for pattern, label_key in _SECRET_PATTERNS:
        if pattern.search(sample):
            findings.append(
                SecurityFinding(
                    severity="high",
                    category="secret_content",
                    path=str(path),
                    message=t(label_key),
                    remediation=t("audit.sec_secret_fix"),
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
                        message=t("audit.sec_symlink_bad"),
                        remediation=t("audit.sec_symlink_fix"),
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
                    message=t("audit.sec_sensitive_name"),
                    remediation=t("audit.sec_sensitive_fix"),
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
                message=t("audit.sec_env_indexed"),
                remediation=t("audit.sec_env_fix"),
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
