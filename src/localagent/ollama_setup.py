"""Ensure Ollama is installed and the default chat model is available."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable

import httpx

from localagent import config

DEFAULT_OLLAMA_MODEL = "qwen3.5:4b"
_INSTALL_SCRIPT = "https://ollama.com/install.sh"


@dataclass(frozen=True)
class OllamaSetupResult:
    installed: bool
    installed_now: bool = False
    served: bool = False
    model: str = DEFAULT_OLLAMA_MODEL
    model_ready: bool = False
    pulled_now: bool = False
    message: str = ""
    skipped: bool = False
    declined: bool = False


def _env_skip() -> bool:
    return os.getenv("LA_SKIP_OLLAMA_SETUP", "").strip().lower() in ("1", "true", "yes")


def ollama_bin() -> str | None:
    return shutil.which("ollama")


def is_ollama_installed() -> bool:
    return ollama_bin() is not None


def default_ollama_base_url() -> str:
    server = config.get_model_server("ollama")
    if server and server.base_url:
        return server.base_url.rstrip("/")
    return (config.OLLAMA_BASE_URL or "http://localhost:11434").rstrip("/")


def default_ollama_model() -> str:
    server = config.get_model_server("ollama")
    if server and server.model:
        return server.model
    return config.OLLAMA_MODEL or DEFAULT_OLLAMA_MODEL


def is_ollama_reachable(base_url: str | None = None, *, timeout: float = 2.0) -> bool:
    url = (base_url or default_ollama_base_url()).rstrip("/")
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{url}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


def list_local_model_names(base_url: str | None = None) -> list[str]:
    url = (base_url or default_ollama_base_url()).rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{url}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models") or []
    except Exception:
        return []
    names: list[str] = []
    for item in models:
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def has_model(model: str, *, base_url: str | None = None) -> bool:
    target = model.strip()
    if not target:
        return False
    names = list_local_model_names(base_url)
    for name in names:
        if name == target or name.startswith(f"{target}-") or name.startswith(f"{target}:"):
            return True
    return False


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=check, text=True, capture_output=False)


def prompt_yes_no(question: str, *, default: bool = True) -> bool:
    """Ask a yes/no question on a TTY; non-interactive defaults to ``default``."""
    if not sys.stdin.isatty():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        answer = input(f"{question} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default
    if answer in ("y", "yes", "是"):
        return True
    if answer in ("n", "no", "否"):
        return False
    return default


def install_ollama(*, log: Callable[[str], None] | None = None) -> None:
    """Install Ollama via Homebrew (macOS) or the official install script."""
    emit = log or (lambda msg: print(f"[ollama] {msg}"))
    system = platform.system()
    if system == "Darwin" and shutil.which("brew"):
        emit("正在通过 Homebrew 安装 Ollama…")
        _run(["brew", "install", "ollama"])
        return
    if system in ("Darwin", "Linux"):
        emit("正在通过官方安装脚本安装 Ollama…")
        _run(["bash", "-c", f"curl -fsSL {_INSTALL_SCRIPT} | sh"])
        return
    raise RuntimeError(
        "当前系统暂不支持自动安装 Ollama，请手动安装: https://ollama.com/download"
    )


def start_ollama_serve(*, log: Callable[[str], None] | None = None) -> None:
    """Start ``ollama serve`` in the background if the API is not reachable."""
    emit = log or (lambda msg: print(f"[ollama] {msg}"))
    binary = ollama_bin()
    if not binary:
        raise RuntimeError("Ollama 未安装（which ollama 为空）。请安装: https://ollama.com/download")
    base = default_ollama_base_url()
    if is_ollama_reachable(base):
        return
    emit(f"正在启动 ollama serve…（等待 API {base}）")
    subprocess.Popen(  # noqa: S603
        [binary, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    deadline = time.time() + 30
    last_emit = 0.0
    while time.time() < deadline:
        if is_ollama_reachable(base):
            emit("ollama API 已就绪")
            return
        elapsed = time.time() - (deadline - 30)
        if elapsed - last_emit >= 5:
            emit(f"等待 ollama API… {int(elapsed)}s / 30s")
            last_emit = elapsed
        time.sleep(0.5)
    raise RuntimeError(
        f"ollama serve 启动超时（{base} 无响应）。请手动运行: ollama serve"
    )


def pull_model(model: str, *, log: Callable[[str], None] | None = None) -> None:
    emit = log or (lambda msg: print(f"[ollama] {msg}"))
    binary = ollama_bin()
    if not binary:
        raise RuntimeError("Ollama 未安装")
    base = default_ollama_base_url()
    emit(f"正在拉取模型 {model}（首次约 2.5GB；API {base}）…")
    try:
        _run([binary, "pull", model])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"拉取模型失败（exit {exc.returncode}）。可重试: ollama pull {model}"
        ) from exc


def _diagnose_hint(*, base_url: str, target: str) -> str:
    bits = [
        f"platform={platform.system()}",
        f"ollama_bin={ollama_bin() or 'missing'}",
        f"base_url={base_url}",
        f"api={'ok' if is_ollama_reachable(base_url) else 'down'}",
        f"target={target}",
    ]
    names = list_local_model_names(base_url)[:5]
    if names:
        bits.append(f"local_models={','.join(names)}")
    return " · ".join(bits)


def ensure_ollama_ready(
    model: str | None = None,
    *,
    install: bool = True,
    pull: bool = True,
    start_serve: bool = True,
    prompt: bool = True,
    assume_yes: bool = False,
    log: Callable[[str], None] | None = None,
) -> OllamaSetupResult:
    """Check Ollama / model availability; install only after user consent.

    - Default: ask before installing Ollama or pulling a missing model.
    - ``assume_yes=True`` (e.g. ``la setup -y``): proceed without prompts.
    - ``prompt=False``: never install/pull automatically (detect only).
    - ``LA_SKIP_OLLAMA_SETUP=1``: skip entirely.
    """
    emit = log or (lambda msg: print(f"[ollama] {msg}"))
    target = (model or default_ollama_model()).strip() or DEFAULT_OLLAMA_MODEL

    if _env_skip():
        base = default_ollama_base_url()
        installed = is_ollama_installed()
        served = is_ollama_reachable(base) if installed else False
        ready = has_model(target, base_url=base) if served else False
        next_steps = (
            "下一步: 取消跳过则 la setup；或配置云端 Key 后 LA chat --provider openrouter|cursor"
        )
        return OllamaSetupResult(
            installed=installed,
            model=target,
            model_ready=ready,
            served=served,
            skipped=True,
            message=(
                f"已跳过 Ollama 安装引导（LA_SKIP_OLLAMA_SETUP=1）。"
                f"{' 本机已有模型 '+target+'。' if ready else ' '}"
                f"{next_steps}"
            ),
        )

    installed_now = False
    if not is_ollama_installed():
        if not install:
            return OllamaSetupResult(
                installed=False,
                model=target,
                message="未安装 Ollama",
            )

        should_install = assume_yes
        if not should_install and prompt:
            emit("未检测到本机 Ollama。")
            emit("本地对话默认使用 Ollama + qwen3.5:4b；若只用云端模型（OpenRouter/Cursor 等）可跳过。")
            should_install = prompt_yes_no("是否现在本地安装 Ollama？", default=True)
        elif not prompt and not assume_yes:
            return OllamaSetupResult(
                installed=False,
                model=target,
                declined=True,
                skipped=True,
                message="未安装 Ollama（未交互确认）。需要时运行: la setup",
            )

        if not should_install:
            return OllamaSetupResult(
                installed=False,
                model=target,
                declined=True,
                skipped=True,
                message=(
                    "已跳过 Ollama 安装。可配置云端模型后继续，"
                    "或稍后运行: la setup"
                ),
            )

        try:
            install_ollama(log=emit)
        except Exception as exc:
            return OllamaSetupResult(
                installed=False,
                model=target,
                message=f"安装失败: {exc}",
            )
        installed_now = True
        if not is_ollama_installed():
            return OllamaSetupResult(
                installed=False,
                installed_now=True,
                model=target,
                message="安装命令已执行，但仍未找到 ollama，请重开终端后再试",
            )
        emit("Ollama 安装完成")

    served = is_ollama_reachable()
    if not served and start_serve:
        try:
            start_ollama_serve(log=emit)
            served = True
        except Exception as exc:
            return OllamaSetupResult(
                installed=True,
                installed_now=installed_now,
                served=False,
                model=target,
                message=str(exc),
            )

    model_ready = has_model(target) if served else False
    pulled_now = False
    if served and not model_ready and pull:
        should_pull = assume_yes
        if not should_pull and prompt:
            should_pull = prompt_yes_no(
                f"未找到模型 {target}，是否现在拉取？（约 2.5GB）",
                default=True,
            )
        elif not prompt and not assume_yes:
            return OllamaSetupResult(
                installed=True,
                installed_now=installed_now,
                served=served,
                model=target,
                model_ready=False,
                declined=True,
                skipped=True,
                message=f"未拉取模型 {target}。需要时运行: la setup 或 ollama pull {target}",
            )

        if not should_pull:
            return OllamaSetupResult(
                installed=True,
                installed_now=installed_now,
                served=served,
                model=target,
                model_ready=False,
                declined=True,
                skipped=True,
                message=(
                    f"已跳过拉取 {target}。可改用云端模型，"
                    f"或稍后: la setup / ollama pull {target}"
                ),
            )

        try:
            pull_model(target, log=emit)
            pulled_now = True
            model_ready = has_model(target)
        except Exception as exc:
            return OllamaSetupResult(
                installed=True,
                installed_now=installed_now,
                served=served,
                model=target,
                model_ready=False,
                message=f"拉取模型失败: {exc}",
            )

    if model_ready:
        msg = f"已就绪（模型 {target}）"
    elif not served:
        msg = (
            "Ollama 未响应，请运行: ollama serve。诊断: "
            + _diagnose_hint(base_url=default_ollama_base_url(), target=target)
        )
    else:
        msg = (
            f"模型 {target} 尚未就绪。诊断: "
            + _diagnose_hint(base_url=default_ollama_base_url(), target=target)
        )
    return OllamaSetupResult(
        installed=True,
        installed_now=installed_now,
        served=served,
        model=target,
        model_ready=model_ready,
        pulled_now=pulled_now,
        message=msg,
    )
