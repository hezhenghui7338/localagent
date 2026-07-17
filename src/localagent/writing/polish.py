"""One-click text polish — scene-aware rewrite with clipboard-ready output."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from localagent.writing.scenes import (
    SCENE_BIZ,
    SCENE_IDS,
    ScenePack,
    get_scene_pack,
    heuristic_scene,
    normalize_scene,
)

StatusFn = Callable[[str], None]

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


class PolishError(Exception):
    """User-facing polish failure."""


@dataclass
class TasteBrief:
    scene: str
    audience: str
    attitude: str
    risks: str
    preserve: list[str] = field(default_factory=list)
    confidence: float = 0.5
    profile_note: str = ""
    low_confidence: bool = False

    @property
    def scene_label(self) -> str:
        return get_scene_pack(self.scene).label


@dataclass
class PolishResult:
    brief: TasteBrief
    primary: str
    softer: str
    firmer: str
    changes: str
    soft_label: str = "更软"
    firm_label: str = "更硬"

    def format_report(self) -> str:
        pack = get_scene_pack(self.brief.scene)
        bits = [
            f"场景={pack.label}",
            f"读者={self.brief.audience or '未指定'}",
            f"态度={self.brief.attitude}",
        ]
        if self.brief.risks:
            bits.append(f"风险={self.brief.risks}")
        if self.brief.profile_note:
            bits.append(f"文风={self.brief.profile_note}")
        if self.brief.low_confidence:
            bits.append("置信偏低·按默认场景处理")
        lines = [
            "【识别】" + " · ".join(bits),
            "【主推】",
            self.primary.strip(),
            f"【备选·{self.soft_label}】",
            self.softer.strip(),
            f"【备选·{self.firm_label}】",
            self.firmer.strip(),
            "【改动】" + (self.changes.strip() or "微调措辞与语气"),
        ]
        return "\n".join(lines)


def _extract_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    text = _JSON_FENCE.sub("", text).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _profile_snippet() -> str:
    try:
        from localagent.memory.core_profile import load_core_profile

        profile = load_core_profile()
        prefs = profile.preferences or {}
        # Only writing-related keys — avoid dumping coding/home prefs as "文风".
        writing_keys = ("写作风格", "邮件语气", "表达习惯", "文风", "语气")
        bits: list[str] = []
        for key in writing_keys:
            val = (prefs.get(key) or "").strip()
            if val:
                bits.append(f"{key}: {val}")
        if not bits:
            return ""
        if profile.name:
            bits.insert(0, f"姓名: {profile.name}")
        return "；".join(bits)[:400]
    except Exception:
        return ""


def _chat_json(
    prompt: str,
    *,
    temperature: float,
    on_status: StatusFn | None = None,
) -> dict[str, Any] | None:
    from localagent.models.router import ChatMessage, get_model_router

    if on_status:
        on_status("调用模型…")
    try:
        reply = get_model_router().chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=temperature,
            usage_command="polish",
        )
    except Exception:
        return None
    return _extract_json(reply or "")


def detect_taste(
    text: str,
    *,
    scene: str | None = None,
    tone: str | None = None,
    on_status: StatusFn | None = None,
) -> TasteBrief:
    """Infer scene / audience / attitude. Forced ``scene`` skips auto-detect."""
    draft = (text or "").strip()
    if not draft:
        raise PolishError("草稿为空")

    forced = normalize_scene(scene)
    profile = _profile_snippet()
    heur_scene, heur_conf = heuristic_scene(draft)

    prompt = (
        "你是写作场合顾问。根据草稿判断场景与应有态度。"
        "只输出一个 JSON 对象，不要 markdown，不要解释。字段：\n"
        f'  "scene": 必须是 {list(SCENE_IDS)} 之一\n'
        '  "audience": 读者是谁（短词）\n'
        '  "attitude": 该有的态度/语气（一句）\n'
        '  "risks": 表达上最该避免什么（短句）\n'
        '  "preserve": 必须保留的事实/人名/数字（字符串数组）\n'
        '  "confidence": 0到1的小数\n'
        f"可选强制场景: {forced or '无'}\n"
        f"用户语气偏好提示: {tone or '无'}\n"
        f"用户画像片段: {profile or '无'}\n\n"
        f"草稿:\n{draft[:4000]}"
    )
    if on_status:
        on_status("识别场景与态度…")
    data = _chat_json(prompt, temperature=0.1, on_status=on_status)

    if forced:
        pack = get_scene_pack(forced)
        audience = ""
        attitude = pack.default_attitude
        risks = ""
        preserve: list[str] = []
        confidence = 1.0
        if data:
            audience = str(data.get("audience") or "").strip()
            attitude = str(data.get("attitude") or attitude).strip()
            risks = str(data.get("risks") or "").strip()
            preserve = [str(x).strip() for x in (data.get("preserve") or []) if str(x).strip()]
        if tone:
            attitude = f"{attitude}；用户要求: {tone}"
        return TasteBrief(
            scene=pack.id,
            audience=audience or "未指定",
            attitude=attitude,
            risks=risks,
            preserve=preserve,
            confidence=confidence,
            profile_note=profile,
            low_confidence=False,
        )

    if data:
        sid = normalize_scene(str(data.get("scene") or "")) or heur_scene
        try:
            confidence = float(data.get("confidence", heur_conf))
        except (TypeError, ValueError):
            confidence = heur_conf
        attitude = str(data.get("attitude") or get_scene_pack(sid).default_attitude).strip()
        if tone:
            attitude = f"{attitude}；用户要求: {tone}"
        preserve = [str(x).strip() for x in (data.get("preserve") or []) if str(x).strip()]
        low = confidence < 0.45
        if low:
            sid = SCENE_BIZ
        return TasteBrief(
            scene=sid,
            audience=str(data.get("audience") or "未指定").strip() or "未指定",
            attitude=attitude,
            risks=str(data.get("risks") or "").strip(),
            preserve=preserve,
            confidence=confidence,
            profile_note=profile,
            low_confidence=low,
        )

    # Heuristic fallback when model/JSON fails
    pack = get_scene_pack(heur_scene)
    attitude = pack.default_attitude
    if tone:
        attitude = f"{attitude}；用户要求: {tone}"
    return TasteBrief(
        scene=pack.id,
        audience="未指定",
        attitude=attitude,
        risks="避免越界承诺与指责",
        preserve=[],
        confidence=heur_conf,
        profile_note=profile,
        low_confidence=heur_conf < 0.45,
    )


def _pack_rules_block(pack: ScenePack) -> str:
    rules = "\n".join(f"- {r}" for r in pack.hard_rules)
    banned = "、".join(pack.banned_phrases)
    return f"场景规则（{pack.label}）:\n{rules}\n禁用套话: {banned}"


def rewrite(
    text: str,
    brief: TasteBrief,
    *,
    tone: str | None = None,
    on_status: StatusFn | None = None,
) -> PolishResult:
    """Rewrite draft given a taste brief. Raises PolishError on hard failure."""
    draft = (text or "").strip()
    if not draft:
        raise PolishError("草稿为空")
    pack = get_scene_pack(brief.scene)
    preserve = "、".join(brief.preserve) if brief.preserve else "（无额外清单，勿新增事实）"
    prompt = (
        "你是资深中文写作润色编辑。根据场合态度改写草稿，保留原意与事实。\n"
        "只输出一个 JSON 对象，不要 markdown，不要解释。字段：\n"
        '  "primary": 主推版本（完整正文）\n'
        f'  "softer": {pack.soft_label}备选（完整正文）\n'
        f'  "firmer": {pack.firm_label}备选（完整正文）\n'
        '  "changes": 改动说明（一句，列关键变化）\n'
        "硬约束：\n"
        "- 不新增原文没有的数字、公司、职位、承诺或截止日\n"
        "- 不要工具调用、不要前言后语\n"
        "- 三个版本都必须是可直接发送的完整正文\n"
        f"{_pack_rules_block(pack)}\n"
        f"读者: {brief.audience}\n"
        f"态度: {brief.attitude}\n"
        f"风险: {brief.risks or '无'}\n"
        f"必须保留: {preserve}\n"
        f"用户语气要求: {tone or '无'}\n"
        f"用户画像: {brief.profile_note or '无'}\n\n"
        f"草稿:\n{draft[:5000]}"
    )
    if on_status:
        on_status("改写中…")
    data = _chat_json(prompt, temperature=0.45, on_status=on_status)
    if not data:
        raise PolishError("模型未返回可用改写结果，请稍后重试或切换 /provider")

    primary = str(data.get("primary") or "").strip()
    softer = str(data.get("softer") or "").strip()
    firmer = str(data.get("firmer") or "").strip()
    changes = str(data.get("changes") or "").strip()
    if not primary:
        raise PolishError("模型未给出主推正文")
    if not softer:
        softer = primary
    if not firmer:
        firmer = primary
    return PolishResult(
        brief=brief,
        primary=primary,
        softer=softer,
        firmer=firmer,
        changes=changes or "微调措辞与语气",
        soft_label=pack.soft_label,
        firm_label=pack.firm_label,
    )


def polish_text(
    text: str,
    *,
    scene: str | None = None,
    tone: str | None = None,
    on_status: StatusFn | None = None,
) -> PolishResult:
    """Full pipeline: detect taste → rewrite."""
    brief = detect_taste(text, scene=scene, tone=tone, on_status=on_status)
    return rewrite(text, brief, tone=tone, on_status=on_status)


def copy_variant(result: PolishResult, choice: str) -> tuple[str, str] | None:
    """Map user choice to (label, text).

    Returns None for skip (empty / n) or unrecognized input — callers distinguish
    via ``is_skip_choice``.
    """
    key = (choice or "").strip().lower()
    if is_skip_choice(key):
        return None
    if key in ("1", "p", "primary", "主推"):
        return ("主推", result.primary)
    if key in ("2", "s", "soft", "softer", result.soft_label.lower(), "更软", "更淡", "更稳"):
        return (f"备选·{result.soft_label}", result.softer)
    if key in ("3", "f", "firm", "firmer", result.firm_label.lower(), "更硬", "更燃", "更亮"):
        return (f"备选·{result.firm_label}", result.firmer)
    return None


def is_skip_choice(choice: str) -> bool:
    return (choice or "").strip().lower() in ("", "n", "no", "q", "quit", "跳过")


def apply_clipboard(
    result: PolishResult,
    *,
    enabled: bool = True,
    interactive: bool | None = None,
    input_fn: Callable[[str], str] | None = None,
    copy_fn: Callable[[str], bool] | None = None,
) -> list[str]:
    """Copy primary (and optionally variants). Returns status lines (caller prints them)."""
    from localagent.ui.clipboard import copy_text

    lines: list[str] = []
    if not enabled:
        return lines

    do_copy = copy_fn or copy_text
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()

    if do_copy(result.primary):
        hint = (
            f"✓ 已复制【主推】到剪贴板 · 按 2={result.soft_label} / "
            f"3={result.firm_label} 换拷 · 1=再拷主推 · Enter/n 结束"
            if interactive
            else "✓ 已复制【主推】到剪贴板"
        )
        lines.append(hint)
        print(hint)
    else:
        msg = "剪贴板不可用，请手动复制【主推】区块"
        lines.append(msg)
        print(msg)
        return lines

    if not interactive:
        return lines

    reader = input_fn or input
    while True:
        try:
            choice = reader("复制> ")
        except EOFError:
            break
        except KeyboardInterrupt:
            print()
            lines.append("已结束复制")
            break
        if is_skip_choice(choice):
            break
        mapped = copy_variant(result, choice)
        if mapped is None:
            msg = f"无效选项: {choice!r}（1=主推 / 2={result.soft_label} / 3={result.firm_label} / n）"
            lines.append(msg)
            print(msg)
            continue
        label, body = mapped
        if do_copy(body):
            msg = f"✓ 已复制【{label}】到剪贴板"
        else:
            msg = f"复制【{label}】失败，请手动复制"
        lines.append(msg)
        print(msg)
    return lines


# Re-export for callers / tests
__all__ = [
    "PolishError",
    "PolishResult",
    "TasteBrief",
    "apply_clipboard",
    "copy_variant",
    "detect_taste",
    "is_skip_choice",
    "polish_text",
    "rewrite",
]
