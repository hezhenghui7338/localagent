"""Detect local hardware and recommend an Ollama chat model by system RAM."""

from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelTier:
    """One RAM tier → recommended Ollama model."""

    min_ram_bytes: int
    model: str
    size_hint: str
    label: str
    note: str = ""


# Thresholds leave headroom for OS + LA/Chroma. Ordered ascending by min_ram_bytes.
MODEL_TIERS: tuple[ModelTier, ...] = (
    ModelTier(
        min_ram_bytes=0,
        model="qwen2.5:0.5b",
        size_hint="~0.4–1 GB",
        label="Mini",
        note="可跑通 Chat/基础记忆；复杂 Agent/多工具会明显变弱",
    ),
    ModelTier(
        min_ram_bytes=6 * (1024**3),
        model="qwen2.5:1.5b",
        size_hint="~1–2 GB",
        label="轻量",
        note="轻量日常问答",
    ),
    ModelTier(
        min_ram_bytes=10 * (1024**3),
        model="qwen2.5:3b",
        size_hint="~2 GB",
        label="过渡",
        note="中低配过渡档",
    ),
    ModelTier(
        min_ram_bytes=14 * (1024**3),
        model="qwen3.5:4b",
        size_hint="~2.5 GB",
        label="推荐",
        note="当前主推质量档",
    ),
)

DEFAULT_TIER_MODEL = MODEL_TIERS[-1].model
MINI_OLLAMA_MODEL = MODEL_TIERS[0].model


def total_ram_bytes() -> int | None:
    """Return total system RAM in bytes, or None if detection fails."""
    system = platform.system()
    try:
        if system == "Darwin":
            return _ram_darwin()
        if system == "Linux":
            return _ram_linux()
        if system == "Windows":
            return _ram_windows()
    except Exception:
        return None
    return None


def _ram_darwin() -> int | None:
    out = subprocess.run(
        ["sysctl", "-n", "hw.memsize"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        return None
    text = (out.stdout or "").strip()
    if not text.isdigit():
        return None
    return int(text)


def _ram_linux() -> int | None:
    try:
        text = open("/proc/meminfo", encoding="utf-8").read()  # noqa: SIM115
    except OSError:
        return None
    match = re.search(r"^MemTotal:\s+(\d+)\s+kB", text, re.MULTILINE)
    if not match:
        return None
    return int(match.group(1)) * 1024


def _ram_windows() -> int | None:
    import ctypes
    from ctypes import wintypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_uint64),
            ("ullAvailPhys", ctypes.c_uint64),
            ("ullTotalPageFile", ctypes.c_uint64),
            ("ullAvailPageFile", ctypes.c_uint64),
            ("ullTotalVirtual", ctypes.c_uint64),
            ("ullAvailVirtual", ctypes.c_uint64),
            ("ullAvailExtendedVirtual", ctypes.c_uint64),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):  # type: ignore[attr-defined]
        return None
    value = int(stat.ullTotalPhys)
    return value if value > 0 else None


def format_ram_gb(ram_bytes: int | None) -> str:
    if ram_bytes is None or ram_bytes <= 0:
        return "未知"
    gb = ram_bytes / (1024**3)
    if gb >= 10:
        return f"{gb:.0f} GB"
    return f"{gb:.1f} GB"


def tier_for_ram(ram_bytes: int | None) -> ModelTier:
    """Pick the highest tier whose min_ram_bytes <= ram_bytes.

    Unknown RAM falls back to the recommended (highest) tier.
    """
    if ram_bytes is None or ram_bytes <= 0:
        return MODEL_TIERS[-1]
    chosen = MODEL_TIERS[0]
    for tier in MODEL_TIERS:
        if ram_bytes >= tier.min_ram_bytes:
            chosen = tier
    return chosen


def recommend_ollama_model(ram_bytes: int | None = None) -> str:
    """Return the Ollama model tag recommended for ``ram_bytes`` (or detected RAM)."""
    if ram_bytes is None:
        ram_bytes = total_ram_bytes()
    return tier_for_ram(ram_bytes).model


def model_size_hint(model: str) -> str:
    """Human-readable download size hint for known tier models."""
    target = (model or "").strip()
    for tier in MODEL_TIERS:
        if tier.model == target:
            return tier.size_hint
    return "体积视模型而定"


def tier_by_model(model: str) -> ModelTier | None:
    target = (model or "").strip()
    for tier in MODEL_TIERS:
        if tier.model == target:
            return tier
    return None
