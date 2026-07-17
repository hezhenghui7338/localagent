"""Tests for one-click polish and clipboard helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from localagent.writing.polish import (
    PolishError,
    PolishResult,
    TasteBrief,
    apply_clipboard,
    copy_variant,
    detect_taste,
    is_skip_choice,
    polish_text,
    rewrite,
)
from localagent.writing.scenes import (
    SCENE_BIZ,
    SCENE_EMAIL,
    SCENE_MOMENTS,
    SCENE_RESUME,
    get_scene_pack,
    heuristic_scene,
    normalize_scene,
)


def test_normalize_scene_aliases():
    assert normalize_scene("邮件") == SCENE_EMAIL
    assert normalize_scene("朋友圈") == SCENE_MOMENTS
    assert normalize_scene("简历") == SCENE_RESUME
    assert normalize_scene("企微") == SCENE_BIZ
    assert normalize_scene("email") == SCENE_EMAIL
    assert normalize_scene("nope") is None


def test_heuristic_scene_email_and_resume():
    email_id, conf = heuristic_scene("尊敬的张总：您好，关于上周邮件主题，此致")
    assert email_id == SCENE_EMAIL
    assert conf > 0.4

    resume_id, _ = heuristic_scene("负责电商后台，主导库存优化项目，工作经历如下")
    assert resume_id == SCENE_RESUME


def test_format_report_structure():
    brief = TasteBrief(
        scene=SCENE_EMAIL,
        audience="同事",
        attitude="催促但留台阶",
        risks="避免指责",
        preserve=["上周"],
        confidence=0.9,
    )
    result = PolishResult(
        brief=brief,
        primary="主推正文",
        softer="更软正文",
        firmer="更硬正文",
        changes="收紧开头",
        soft_label="更软",
        firm_label="更硬",
    )
    report = result.format_report()
    assert "【识别】" in report
    assert "商务邮件" in report
    assert "【主推】" in report
    assert "主推正文" in report
    assert "【备选·更软】" in report
    assert "【改动】" in report


def test_copy_variant_and_skip():
    brief = TasteBrief(
        scene=SCENE_BIZ,
        audience="对方",
        attitude="清晰",
        risks="",
    )
    result = PolishResult(
        brief=brief,
        primary="A",
        softer="B",
        firmer="C",
        changes="x",
        soft_label="更软",
        firm_label="更硬",
    )
    assert is_skip_choice("")
    assert is_skip_choice("n")
    assert copy_variant(result, "1") == ("主推", "A")
    assert copy_variant(result, "2") == ("备选·更软", "B")
    assert copy_variant(result, "3") == ("备选·更硬", "C")
    assert copy_variant(result, "n") is None


def test_apply_clipboard_auto_and_swap():
    brief = TasteBrief(scene=SCENE_BIZ, audience="x", attitude="y", risks="")
    result = PolishResult(
        brief=brief,
        primary="PRIMARY",
        softer="SOFT",
        firmer="FIRM",
        changes="z",
    )
    copied: list[str] = []

    def fake_copy(text: str) -> bool:
        copied.append(text)
        return True

    inputs = iter(["2", "n"])

    lines = apply_clipboard(
        result,
        enabled=True,
        interactive=True,
        input_fn=lambda _prompt: next(inputs),
        copy_fn=fake_copy,
    )
    assert copied[0] == "PRIMARY"
    assert "SOFT" in copied
    assert any("已复制【主推】" in line for line in lines)


def test_apply_clipboard_disabled():
    brief = TasteBrief(scene=SCENE_BIZ, audience="x", attitude="y", risks="")
    result = PolishResult(brief=brief, primary="P", softer="S", firmer="F", changes="")
    assert apply_clipboard(result, enabled=False) == []


def test_detect_taste_forced_scene_without_llm():
    with patch("localagent.writing.polish._chat_json", return_value=None):
        brief = detect_taste("随便一段话", scene="email")
    assert brief.scene == SCENE_EMAIL
    assert "清晰" in brief.attitude or brief.attitude


def test_detect_taste_uses_llm_json():
    payload = {
        "scene": "moments",
        "audience": "好友",
        "attitude": "轻松真诚",
        "risks": "少鸡汤",
        "preserve": ["周末"],
        "confidence": 0.88,
    }
    with patch("localagent.writing.polish._chat_json", return_value=payload):
        brief = detect_taste("周末爬山打卡 #周末")
    assert brief.scene == SCENE_MOMENTS
    assert brief.audience == "好友"
    assert brief.preserve == ["周末"]


def test_rewrite_requires_primary():
    brief = TasteBrief(scene=SCENE_BIZ, audience="x", attitude="y", risks="")
    with patch("localagent.writing.polish._chat_json", return_value={"primary": ""}):
        with pytest.raises(PolishError):
            rewrite("草稿", brief)


def test_polish_text_pipeline_mocked():
    detect_payload = {
        "scene": "biz",
        "audience": "同事",
        "attitude": "简洁",
        "risks": "别催太狠",
        "preserve": [],
        "confidence": 0.7,
    }
    rewrite_payload = {
        "primary": "方便时同步一下进度，谢谢。",
        "softer": "有空时麻烦同步下进度～",
        "firmer": "请今天同步进度。",
        "changes": "去掉抱怨",
    }

    def fake_json(prompt: str, **kwargs):
        if "场合顾问" in prompt or "判断场景" in prompt:
            return detect_payload
        return rewrite_payload

    with patch("localagent.writing.polish._chat_json", side_effect=fake_json):
        result = polish_text("进度怎么样了，我们很急")
    assert "同步" in result.primary
    assert "【主推】" in result.format_report()


def test_cmd_polish_dispatch():
    from localagent.cli import build_parser
    from localagent.session_commands import dispatch_cli_argv, normalize_session_argv

    parser = build_parser()
    assert "polish" in parser.format_help()
    assert normalize_session_argv('/polish --scene email "hello"')[:2] == ["polish", "--scene"]

    rewrite_payload = {
        "primary": "主推句",
        "softer": "软句",
        "firmer": "硬句",
        "changes": "改了",
    }
    detect_payload = {
        "scene": "email",
        "audience": "同事",
        "attitude": "礼貌",
        "risks": "",
        "preserve": [],
        "confidence": 0.9,
    }

    def fake_json(prompt: str, **kwargs):
        if "判断场景" in prompt or "场合顾问" in prompt:
            return detect_payload
        return rewrite_payload

    with (
        patch("localagent.writing.polish._chat_json", side_effect=fake_json),
        patch("localagent.writing.polish.apply_clipboard", return_value=[]),
    ):
        rc = dispatch_cli_argv(
            ["polish", "--no-copy", "--scene", "email", "催一下进度"],
            allow_chat=False,
        )
    assert rc == 0


def test_clipboard_copy_text_mocked():
    from localagent.ui import clipboard

    with patch.object(clipboard, "_mac_copy", return_value=True):
        with patch.object(clipboard.platform, "system", return_value="Darwin"):
            assert clipboard.copy_text("hello") is True
    with patch.object(clipboard, "_linux_copy", return_value=False):
        with patch.object(clipboard.platform, "system", return_value="Linux"):
            assert clipboard.copy_text("hello") is False


def test_get_scene_pack_resume_hard_rules():
    pack = get_scene_pack("resume")
    assert any("禁止编造" in r for r in pack.hard_rules)
