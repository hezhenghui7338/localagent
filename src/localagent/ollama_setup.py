"""Ensure Ollama is installed and a usable chat model is available."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from localagent import config
from localagent.hardware import (
    DEFAULT_TIER_MODEL,
    MINI_OLLAMA_MODEL,
    format_ram_gb,
    model_size_hint,
    recommend_ollama_model,
    tier_for_ram,
    total_ram_bytes,
)

DEFAULT_OLLAMA_MODEL = DEFAULT_TIER_MODEL
_INSTALL_SCRIPT = "https://ollama.com/install.sh"
_OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
_WINGET_OLLAMA_ID = "Ollama.Ollama"
_EMBED_HINTS = ("embed", "bge", "nomic", "e5", "minilm", "mxbai")
_COMPLETION_CAPS = frozenset({"completion", "tools", "vision"})


@dataclass(frozen=True)
class OllamaSetupResult:
    installed: bool
    installed_now: bool = False
    served: bool = False
    model: str = DEFAULT_OLLAMA_MODEL
    model_ready: bool = False
    pulled_now: bool = False
    adopted_existing: bool = False
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


def _env_explicit_ollama_model() -> str | None:
    for key in ("LA_OLLAMA_MODEL", "OLLAMA_MODEL"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


def _yaml_ollama_model() -> str | None:
    """Return a user-chosen ollama.model from on-disk model_servers, if any.

    The first-run bootstrap template always writes ``qwen3.5:4b``; treat that
    bootstrap default as unset so RAM tiering can still apply.
    """
    try:
        from localagent.model_servers import (
            load_model_servers_from_file,
            resolve_model_servers_path,
        )

        path = resolve_model_servers_path(project_root=config.PROJECT_ROOT)
        if path is None or not path.is_file():
            return None
        for server in load_model_servers_from_file(path):
            if server.provider != "ollama":
                continue
            model = server.model.strip()
            if not model or model == DEFAULT_OLLAMA_MODEL:
                return None
            return model
    except Exception:
        return None
    return None


def resolve_preferred_ollama_model(
    model: str | None = None,
    *,
    ram_bytes: int | None = None,
) -> tuple[str, str]:
    """Resolve the preferred chat model and why it was chosen.

    Priority: explicit arg → LA_OLLAMA_MODEL / OLLAMA_MODEL env →
    non-default on-disk model_servers.yaml → RAM tier recommendation.
    """
    explicit = (model or "").strip()
    if explicit:
        return explicit, "explicit"

    env_model = _env_explicit_ollama_model()
    if env_model:
        return env_model, "env"

    yaml_model = _yaml_ollama_model()
    if yaml_model:
        return yaml_model, "config"

    detected = total_ram_bytes() if ram_bytes is None else ram_bytes
    recommended = recommend_ollama_model(detected)
    return recommended, "ram"


def is_ollama_reachable(base_url: str | None = None, *, timeout: float = 2.0) -> bool:
    url = (base_url or default_ollama_base_url()).rstrip("/")
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{url}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


def _fetch_ollama_models(path: str, *, base_url: str | None = None, timeout: float = 5.0) -> list[dict[str, Any]]:
    url = (base_url or default_ollama_base_url()).rstrip("/")
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(f"{url}{path}")
            resp.raise_for_status()
            models = resp.json().get("models") or []
    except Exception:
        return []
    return [m for m in models if isinstance(m, dict)]


def _model_capabilities(model: dict[str, Any]) -> set[str]:
    caps = model.get("capabilities")
    if isinstance(caps, list):
        return {str(c) for c in caps}
    details = model.get("details") or {}
    detail_caps = details.get("capabilities")
    if isinstance(detail_caps, list):
        return {str(c) for c in detail_caps}
    return set()


def _is_completion_model(model: dict[str, Any]) -> bool:
    name = str(model.get("name") or model.get("model") or "").strip().lower()
    caps = _model_capabilities(model)
    if name and any(hint in name for hint in _EMBED_HINTS):
        if not caps or caps == {"embedding"} or ("embedding" in caps and not (caps & _COMPLETION_CAPS)):
            return False
    if not caps:
        return True
    if caps == {"embedding"}:
        return False
    return bool(caps & _COMPLETION_CAPS) or "embedding" not in caps


def _model_name(model: dict[str, Any]) -> str:
    return str(model.get("name") or model.get("model") or "").strip()


def list_local_models(base_url: str | None = None) -> list[dict[str, Any]]:
    return _fetch_ollama_models("/api/tags", base_url=base_url)


def list_running_models(base_url: str | None = None) -> list[dict[str, Any]]:
    """Models currently loaded in VRAM (Ollama ``/api/ps``)."""
    return _fetch_ollama_models("/api/ps", base_url=base_url, timeout=3.0)


def list_local_model_names(base_url: str | None = None) -> list[str]:
    names: list[str] = []
    for item in list_local_models(base_url):
        name = _model_name(item)
        if name:
            names.append(name)
    return names


def list_completion_model_names(base_url: str | None = None) -> list[str]:
    names: list[str] = []
    for item in list_local_models(base_url):
        if not _is_completion_model(item):
            continue
        name = _model_name(item)
        if name:
            names.append(name)
    return names


def list_running_completion_model_names(base_url: str | None = None) -> list[str]:
    names: list[str] = []
    for item in list_running_models(base_url):
        if not _is_completion_model(item):
            continue
        name = _model_name(item)
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


def pick_available_completion_model(
    preferred: str | None = None,
    *,
    base_url: str | None = None,
) -> str | None:
    """Choose a usable local chat model.

    Priority: exact preferred match → same tag → currently loaded → first installed.
    """
    preferred = (preferred or "").strip()
    installed = list_local_models(base_url)
    completion = [m for m in installed if _is_completion_model(m) and _model_name(m)]
    if not completion:
        return None

    names = [_model_name(m) for m in completion]
    if preferred and preferred in names:
        return preferred

    if preferred:
        tag = preferred.split(":", 1)[-1] if ":" in preferred else ""
        if tag:
            for name in names:
                if name.endswith(f":{tag}"):
                    return name
        for name in names:
            if name == preferred or name.startswith(f"{preferred}-") or name.startswith(f"{preferred}:"):
                return name

    running = list_running_completion_model_names(base_url)
    for name in running:
        if name in names:
            return name

    return names[0]


def _persist_ollama_model(model: str) -> bool:
    """Best-effort write adopted model into model_servers.yaml."""
    try:
        from localagent.env_config import set_server_model
        from localagent.models.router import reset_model_router

        set_server_model("ollama", model)
        reset_model_router()
        return True
    except Exception:
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


def _open_ollama_download(*, log: Callable[[str], None] | None = None) -> None:
    emit = log or (lambda msg: print(f"[ollama] {msg}"))
    emit(f"请手动安装 Ollama: {_OLLAMA_DOWNLOAD_URL}")
    emit("安装完成后请重开终端，再运行: la setup")
    try:
        webbrowser.open(_OLLAMA_DOWNLOAD_URL)
    except Exception:
        pass


def _install_ollama_windows(*, log: Callable[[str], None]) -> None:
    winget = shutil.which("winget")
    if winget:
        emit = log
        emit(f"正在通过 winget 安装 Ollama（{_WINGET_OLLAMA_ID}）…")
        try:
            _run(
                [
                    winget,
                    "install",
                    "-e",
                    "--id",
                    _WINGET_OLLAMA_ID,
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                ]
            )
        except subprocess.CalledProcessError as exc:
            emit(f"winget 安装失败（exit {exc.returncode}），改为手动安装引导…")
            _open_ollama_download(log=emit)
            raise RuntimeError(
                f"winget 安装 Ollama 失败。请手动安装: {_OLLAMA_DOWNLOAD_URL}"
            ) from exc
        return
    _open_ollama_download(log=log)
    raise RuntimeError(
        f"未找到 winget，请手动安装 Ollama: {_OLLAMA_DOWNLOAD_URL}"
    )


def install_ollama(*, log: Callable[[str], None] | None = None) -> None:
    """Install Ollama via Homebrew, install.sh, or Windows winget."""
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
    if system == "Windows":
        _install_ollama_windows(log=emit)
        return
    raise RuntimeError(
        f"当前系统暂不支持自动安装 Ollama，请手动安装: {_OLLAMA_DOWNLOAD_URL}"
    )


def start_ollama_serve(*, log: Callable[[str], None] | None = None) -> None:
    """Start ``ollama serve`` in the background if the API is not reachable."""
    emit = log or (lambda msg: print(f"[ollama] {msg}"))
    binary = ollama_bin()
    if not binary:
        raise RuntimeError(f"Ollama 未安装（which ollama 为空）。请安装: {_OLLAMA_DOWNLOAD_URL}")
    base = default_ollama_base_url()
    if is_ollama_reachable(base):
        return
    # Windows Ollama often already runs as a background app/service.
    if platform.system() == "Windows":
        emit(f"等待本机 Ollama 服务…（API {base}；若未启动请从开始菜单打开 Ollama）")
    else:
        emit(f"正在启动 ollama serve…（等待 API {base}）")
    popen_kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if platform.system() == "Windows":
        # CREATE_NEW_PROCESS_GROUP — avoid tying serve to this console.
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    subprocess.Popen([binary, "serve"], **popen_kwargs)  # noqa: S603
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
    if platform.system() == "Windows":
        raise RuntimeError(
            f"ollama API 超时（{base} 无响应）。请从开始菜单启动 Ollama，"
            f"或手动运行: ollama serve。安装包: {_OLLAMA_DOWNLOAD_URL}"
        )
    raise RuntimeError(
        f"ollama serve 启动超时（{base} 无响应）。请手动运行: ollama serve"
    )


def pull_model(model: str, *, log: Callable[[str], None] | None = None) -> None:
    emit = log or (lambda msg: print(f"[ollama] {msg}"))
    binary = ollama_bin()
    if not binary:
        raise RuntimeError("Ollama 未安装")
    base = default_ollama_base_url()
    size = model_size_hint(model)
    emit(f"正在拉取模型 {model}（首次约 {size}；API {base}）…")
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


def _prompt_model_choice(
    recommended: str,
    *,
    ram_bytes: int | None,
    log: Callable[[str], None],
) -> str:
    """Interactive model pick when pulling a fresh default; Enter keeps recommendation."""
    tier = tier_for_ram(ram_bytes)
    log(
        f"检测到系统内存 {format_ram_gb(ram_bytes)} → 推荐 {recommended}"
        f"（{tier.label}，{tier.size_hint}）"
    )
    if tier.note:
        log(tier.note)
    if recommended == MINI_OLLAMA_MODEL:
        log("Mini 档可跑通基础对话；复杂 Agent/多工具能力有限。")
    if not sys.stdin.isatty():
        return recommended
    try:
        answer = input(
            f"拉取模型 [{recommended}]（回车确认；或输入其他标签，如 {MINI_OLLAMA_MODEL}）: "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return recommended
    return answer or recommended


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
    - When no model is configured, prefer a RAM-tier recommendation.
    """
    emit = log or (lambda msg: print(f"[ollama] {msg}"))
    ram = total_ram_bytes()
    preferred, source = resolve_preferred_ollama_model(model, ram_bytes=ram)
    preferred = preferred.strip() or DEFAULT_OLLAMA_MODEL
    target = preferred
    if source == "ram":
        emit(
            f"检测到系统内存 {format_ram_gb(ram)} → 选用 {preferred}"
            f"（{tier_for_ram(ram).label}，{model_size_hint(preferred)}）"
        )

    if _env_skip():
        base = default_ollama_base_url()
        installed = is_ollama_installed()
        served = is_ollama_reachable(base) if installed else False
        adopted = pick_available_completion_model(preferred, base_url=base) if served else None
        ready = adopted is not None
        used = adopted or preferred
        next_steps = (
            "下一步: 取消跳过则 la setup；或配置云端 Key 后 LA chat --provider openrouter|cursor"
        )
        return OllamaSetupResult(
            installed=installed,
            model=used,
            model_ready=ready,
            served=served,
            adopted_existing=bool(adopted and adopted != preferred),
            skipped=True,
            message=(
                f"已跳过 Ollama 安装引导（LA_SKIP_OLLAMA_SETUP=1）。"
                f"{' 本机已有模型 '+used+'。' if ready else ' '}"
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
            emit(
                "本地对话优先用本机已有 Ollama 模型；"
                f"若无可用模型再按内存拉取推荐模型（当前推荐 {preferred}）。"
                "只用云端（OpenRouter/Cursor 等）可跳过。"
            )
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
                message=(
                    "安装命令已执行，但仍未找到 ollama，请重开终端后再试"
                    + (
                        f"（Windows 可从开始菜单启动 Ollama，或见 {_OLLAMA_DOWNLOAD_URL}）"
                        if platform.system() == "Windows"
                        else ""
                    )
                ),
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

    adopted_existing = False
    pulled_now = False
    model_ready = False
    if served:
        adopted = pick_available_completion_model(preferred)
        if adopted:
            target = adopted
            model_ready = True
            if adopted != preferred:
                adopted_existing = True
                emit(f"未找到配置模型 {preferred}，改用本机已有模型 {adopted}")
                if _persist_ollama_model(adopted):
                    emit(f"已将 ollama.model 更新为 {adopted}")

    if served and not model_ready and pull:
        pull_target = preferred
        should_pull = assume_yes
        available = list_completion_model_names()
        if not should_pull and prompt:
            if source == "ram":
                pull_target = _prompt_model_choice(preferred, ram_bytes=ram, log=emit)
            hint = (
                f"未找到可用对话模型（推荐 {pull_target}）"
                if not available
                else f"未找到配置模型 {pull_target}"
            )
            size = model_size_hint(pull_target)
            should_pull = prompt_yes_no(
                f"{hint}，是否现在拉取 {pull_target}？（约 {size}）",
                default=True,
            )
        elif not prompt and not assume_yes:
            return OllamaSetupResult(
                installed=True,
                installed_now=installed_now,
                served=served,
                model=preferred,
                model_ready=False,
                declined=True,
                skipped=True,
                message=(
                    f"未拉取模型 {preferred}。需要时运行: la setup 或 ollama pull {preferred}"
                ),
            )

        if not should_pull:
            return OllamaSetupResult(
                installed=True,
                installed_now=installed_now,
                served=served,
                model=preferred,
                model_ready=False,
                declined=True,
                skipped=True,
                message=(
                    f"已跳过拉取 {pull_target}。可改用云端模型，"
                    f"或稍后: la setup / ollama pull {pull_target}"
                ),
            )

        try:
            pull_model(pull_target, log=emit)
            pulled_now = True
            target = pull_target
            model_ready = has_model(pull_target)
            if model_ready and _persist_ollama_model(pull_target):
                emit(f"已将 ollama.model 更新为 {pull_target}")
        except Exception as exc:
            return OllamaSetupResult(
                installed=True,
                installed_now=installed_now,
                served=served,
                model=pull_target,
                model_ready=False,
                message=f"拉取模型失败: {exc}",
            )

    if model_ready:
        if adopted_existing:
            msg = f"已就绪（改用本机已有模型 {target}；原配置 {preferred}）"
        else:
            msg = f"已就绪（模型 {target}）"
    elif not served:
        serve_hint = (
            "请从开始菜单启动 Ollama，或运行: ollama serve"
            if platform.system() == "Windows"
            else "请运行: ollama serve"
        )
        msg = (
            f"Ollama 未响应，{serve_hint}。诊断: "
            + _diagnose_hint(base_url=default_ollama_base_url(), target=preferred)
        )
    else:
        msg = (
            f"模型 {preferred} 尚未就绪。诊断: "
            + _diagnose_hint(base_url=default_ollama_base_url(), target=preferred)
        )
    return OllamaSetupResult(
        installed=True,
        installed_now=installed_now,
        served=served,
        model=target,
        model_ready=model_ready,
        pulled_now=pulled_now,
        adopted_existing=adopted_existing,
        message=msg,
    )
