"""End-to-end tests for LA shell tab completion."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import PROJECT_ROOT, run_la

pytestmark = pytest.mark.e2e

ZSH_SCRIPT = PROJECT_ROOT / "scripts" / "la-completion.zsh"
VENV_BIN = PROJECT_ROOT / ".venv" / "bin"


def _zsh_interactive(script: str, *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    """Run zsh interactively without sourcing the user's ~/.zshrc (avoids hangs)."""
    env = os.environ.copy()
    env["PATH"] = f"{VENV_BIN}:{env.get('PATH', '')}"
    # -f: skip global/user RCS so slow/interactive .zshrc cannot stall e2e.
    # -i: keep interactive mode so la-completion.zsh registers compdef.
    return subprocess.run(
        ["zsh", "-fic", script],
        text=True,
        capture_output=True,
        env=env,
        cwd=PROJECT_ROOT,
        timeout=timeout,
    )


def test_e2e_complete_memory_prefix():
    result = run_la(["complete", "--", "LA", "mem"])
    assert result.returncode == 0
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert lines == ["memory"]


def test_e2e_complete_all_commands():
    result = run_la(["complete", "--", "LA"])
    assert result.returncode == 0
    lines = set(result.stdout.splitlines())
    assert {"chat", "memory", "tasks"}.issubset(lines)


def test_e2e_complete_chat_provider_flag():
    result = run_la(["complete", "--", "LA", "chat", "--"])
    assert result.returncode == 0
    assert "--provider" in result.stdout


@pytest.mark.skipif(not ZSH_SCRIPT.is_file(), reason="zsh completion script missing")
@pytest.mark.skipif(not (VENV_BIN / "LA").exists(), reason="LA not installed in .venv")
def test_e2e_zsh_compdef_registers_la():
    result = _zsh_interactive(
        f'source "{ZSH_SCRIPT}"; [[ "${{_comps[LA]}}" == _la ]] && echo compdef_ok'
    )
    assert result.returncode == 0, result.stderr
    assert "compdef_ok" in result.stdout


@pytest.mark.skipif(not ZSH_SCRIPT.is_file(), reason="zsh completion script missing")
@pytest.mark.skipif(not (VENV_BIN / "LA").exists(), reason="LA not installed in .venv")
def test_e2e_zsh_la_memory_tab_candidates():
    """Simulate LA mem<Tab>: _la should offer memory."""
    result = _zsh_interactive(
        f"source '{ZSH_SCRIPT}'; "
        "words=(LA mem); CURRENT=2; "
        'suggestions=("${(@f)$(LA complete -- "${words[@]}")}"); '
        'print -rl -- "${suggestions[@]}"'
    )
    assert result.returncode == 0, result.stderr
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert lines == ["memory"], lines


@pytest.mark.skipif(sys.platform == "darwin", reason="complete-init e2e writes ~/.zshrc on dev machine")
def test_e2e_complete_init_writes_block(tmp_path: Path):
    """Run complete-init in isolation (non-macOS CI only)."""
    home = tmp_path / "home"
    home.mkdir()
    zshrc = home / ".zshrc"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{VENV_BIN}:{env.get('PATH', '')}"

    result = subprocess.run(
        [sys.executable, "-m", "localagent.cli", "complete-init", "zsh"],
        text=True,
        capture_output=True,
        env=env,
        cwd=PROJECT_ROOT,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    text = zshrc.read_text(encoding="utf-8")
    assert "compinit -C" in text
    assert "compdef _la LA la" in text
