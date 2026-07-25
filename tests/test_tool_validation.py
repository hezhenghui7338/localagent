"""Tests for post-execution tool result validation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from localagent.agent.planner.checker import milestone_done_heuristic
from localagent.agent.planner.state import Milestone
from localagent.agent.validation.followup import build_tool_followup, validation_requests_auto_retry
from localagent.agent.validation import (
    ValidationResult,
    output_has_validation_failure,
    validate_tool_result,
)
from localagent.agent.validation.annotate import annotate_output
from localagent.agent.validation.programmatic.read_search import (
    validate_glob,
    validate_grep,
    validate_read_file,
)
from localagent.agent.validation.programmatic.shell import validate_shell
from localagent.agent.validation.programmatic.web_search import validate_web_search
from localagent.agent.validation.pre_call import build_pre_call_followup, check_tool_call
from localagent.agent.validation.types import ValidationContext


def test_shell_validator_nonzero_exit_fails():
    raw = "$ pytest\nexit: 1\nstdout:\nFAILED tests/test_foo.py"
    ctx = ValidationContext(tool_name="run_shell", raw=raw)
    result = validate_shell(ctx)
    assert result.severity == "fail"
    assert result.evidence.get("exit_code") == 1


def test_shell_validator_pytest_failure_pattern():
    raw = "$ pytest\nstdout:\n===== 1 failed in 0.5s ====="
    ctx = ValidationContext(tool_name="run_shell", raw=raw)
    result = validate_shell(ctx)
    assert result.severity == "fail"
    assert result.evidence.get("test_failed") is True


def test_shell_validator_success():
    raw = "$ echo ok\nstdout:\nok"
    ctx = ValidationContext(tool_name="run_shell", raw=raw)
    result = validate_shell(ctx)
    assert result.severity == "ok"


def test_shell_validator_stderr_only_warns():
    raw = "$ cmd\nstderr:\nwarning: something"
    ctx = ValidationContext(tool_name="run_shell", raw=raw)
    result = validate_shell(ctx)
    assert result.severity == "warn"


def test_annotate_output_prepends_markers():
    result = ValidationResult.fail("测试失败。")
    text = annotate_output("raw output", result)
    assert text.startswith("【核对失败】")
    assert "raw output" in text


def test_output_has_validation_failure():
    assert output_has_validation_failure("【核对失败】exit 非零")
    assert not output_has_validation_failure("一切正常")


def test_validate_tool_result_shell_integration():
    raw = "$ false\nexit: 1\n（无输出）"
    annotated, result = validate_tool_result("run_shell", raw)
    assert result.severity == "fail"
    assert "【核对失败】" in annotated


def test_validate_tool_result_unknown_tool_passthrough():
    raw = "some result"
    annotated, result = validate_tool_result("grep", raw)
    assert annotated == raw
    assert result.severity == "ok"


def test_write_file_readback_pass(isolated_data, monkeypatch):
    from localagent import config

    ws = config.WORKSPACE_DIR
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LA_WORKSPACE", str(ws))
    monkeypatch.setattr("localagent.config.VALIDATE_READBACK", True)

    target = ws / "out.txt"
    target.write_text("hello world", encoding="utf-8")
    raw = "已写入文件: out.txt\n内容预览:\nhello world"
    annotated, result = validate_tool_result(
        "write_file",
        raw,
        arguments={"path": "out.txt", "content": "hello world", "mode": "overwrite"},
    )
    assert result.severity == "ok"
    assert result.evidence.get("readback_ok") is True
    assert annotated == raw


def test_write_file_readback_fail(isolated_data, monkeypatch):
    from localagent import config

    ws = config.WORKSPACE_DIR
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LA_WORKSPACE", str(ws))
    monkeypatch.setattr("localagent.config.VALIDATE_READBACK", True)

    target = ws / "bad.txt"
    target.write_text("wrong content", encoding="utf-8")
    raw = "已写入文件: bad.txt\n内容预览:\nexpected"
    annotated, result = validate_tool_result(
        "write_file",
        raw,
        arguments={"path": "bad.txt", "content": "expected content", "mode": "overwrite"},
    )
    assert result.severity == "fail"
    assert "【核对失败】" in annotated
    assert result.evidence.get("readback_failed") is True


def test_edit_file_readback_pass(isolated_data, monkeypatch):
    from localagent import config

    ws = config.WORKSPACE_DIR
    ws.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LA_WORKSPACE", str(ws))
    monkeypatch.setattr("localagent.config.VALIDATE_READBACK", True)

    target = ws / "cfg.py"
    target.write_text("timeout = 30\n", encoding="utf-8")
    raw = "已编辑文件: cfg.py"
    _, result = validate_tool_result(
        "edit_file",
        raw,
        arguments={
            "path": "cfg.py",
            "old_string": "timeout = 10",
            "new_string": "timeout = 30",
        },
    )
    assert result.severity == "ok"


def test_milestone_done_rejects_shell_nonzero_exit():
    m = Milestone(id="m1", objective="run tests", done_when="测试通过")
    obs = "$ pytest\nexit: 1\nstdout:\nFAILED"
    vresult = ValidationResult.fail("exit", exit_code=1)
    assert not milestone_done_heuristic(
        m,
        tool_calls=[{"name": "run_shell"}],
        last_observation=obs,
        last_tool_name="run_shell",
        last_validation=vresult,
    )


def test_milestone_done_accepts_shell_success():
    m = Milestone(id="m1", objective="run tests", done_when="测试通过")
    obs = "$ pytest\nstdout:\n3 passed"
    vresult = ValidationResult.ok(exit_code=0)
    assert milestone_done_heuristic(
        m,
        tool_calls=[{"name": "run_shell"}],
        last_observation=obs,
        last_tool_name="run_shell",
        last_validation=vresult,
    )


def test_milestone_done_no_longer_accepts_long_observation_only():
    m = Milestone(id="m1", objective="run", done_when="done")
    obs = "x" * 50
    assert not milestone_done_heuristic(
        m,
        tool_calls=[{"name": "run_shell"}],
        last_observation=obs,
        last_tool_name="run_shell",
    )


def test_tool_followup_fail_branch():
    result = "【核对失败】命令退出码非零 (exit: 1)。\n$ false"
    text = build_tool_followup("run_shell", result)
    assert "【校验未通过】" in text
    assert "重试" in text


def test_tool_followup_warn_branch():
    vresult = ValidationResult.warn("stderr 有输出")
    text = build_tool_followup("run_shell", "stderr output", vresult)
    assert "【校验警告】" in text


def test_validation_auto_retry_readback_followup(monkeypatch):
    monkeypatch.setattr("localagent.config.VALIDATION_AUTO_RETRY", True)
    vresult = ValidationResult.fail(
        "写入后 read-back 内容与预期不符。",
        retry_hint="检查 content 与 path 后重试 write_file。",
        readback_failed=True,
    )
    assert validation_requests_auto_retry(vresult) is True
    text = build_tool_followup(
        "write_file",
        "【核对失败】写入后 read-back 内容与预期不符。",
        vresult,
    )
    assert "必须重试" in text
    assert "write_file" in text


def test_validation_auto_retry_disabled(monkeypatch):
    monkeypatch.setattr("localagent.config.VALIDATION_AUTO_RETRY", False)
    vresult = ValidationResult.fail("read-back fail", readback_failed=True)
    assert validation_requests_auto_retry(vresult) is False
    text = build_tool_followup("write_file", "【核对失败】read-back fail", vresult)
    assert "必须重试" not in text


def test_read_file_validator_missing_file_fails():
    raw = "错误: 文件不存在: missing.py"
    _, result = validate_tool_result("read_file", raw)
    assert result.severity == "fail"


def test_read_file_validator_ok():
    raw = "文件: src/a.py（共 10 行）\n     1|hello"
    _, result = validate_tool_result("read_file", raw)
    assert result.severity == "ok"


def test_grep_validator_no_match_warns():
    raw = "未找到匹配: pattern='foo'"
    _, result = validate_tool_result("grep", raw)
    assert result.severity == "warn"
    assert result.evidence.get("no_matches") is True


def test_glob_validator_no_match_warns():
    raw = "未找到匹配文件: pattern='*.missing' path=."
    _, result = validate_tool_result("glob", raw)
    assert result.severity == "warn"


def test_pre_call_warns_read_streak_on_mutation_milestone():
    prior = [
        {"name": "read_file", "arguments": {"path": "a.py"}},
        {"name": "grep", "arguments": {"pattern": "x"}},
    ]
    result = check_tool_call(
        "read_file",
        {"path": "b.py"},
        milestone_objective="修改 config 中的 timeout",
        tool_calls=prior,
    )
    assert result is not None
    assert result.severity == "warn"
    assert result.evidence.get("pre_call") is True
    followup = build_pre_call_followup(result)
    assert "edit_file" in followup


def test_pre_call_allows_after_side_effect_tool():
    prior = [
        {"name": "read_file", "arguments": {"path": "a.py"}},
        {"name": "read_file", "arguments": {"path": "b.py"}},
        {"name": "edit_file", "arguments": {"path": "b.py"}},
    ]
    result = check_tool_call(
        "read_file",
        {"path": "c.py"},
        milestone_objective="修改 timeout",
        tool_calls=prior,
    )
    assert result is None


def test_semantic_validation_upgrades_warn(monkeypatch):
    monkeypatch.setattr("localagent.config.VALIDATION_LLM", True)
    monkeypatch.setattr("localagent.config.VALIDATION_LLM_MAX", 1)

    router = MagicMock()
    router.chat.return_value = '{"severity": "fail", "reason": "结果不满足完成条件"}'
    raw = "$ cmd\nstderr:\nwarning"
    _, result = validate_tool_result(
        "run_shell",
        raw,
        user_query="运行测试",
        milestone_done_when="测试通过",
        router=router,
        semantic_calls=0,
    )
    assert result.severity == "fail"
    assert result.evidence.get("llm_verified") is True
    router.chat.assert_called_once()


def test_semantic_validation_skipped_on_hard_fail():
    router = MagicMock()
    raw = "$ false\nexit: 1"
    _, result = validate_tool_result(
        "run_shell",
        raw,
        router=router,
        semantic_calls=0,
    )
    assert result.severity == "fail"
    router.chat.assert_not_called()


def test_web_search_validator_ok_on_results():
    raw = "1. Example result\n   https://example.com\n   snippet text"
    ctx = ValidationContext(tool_name="web_search", raw=raw)
    result = validate_web_search(ctx)
    assert result.severity == "ok"


def test_web_search_validator_warn_on_freshness():
    raw = "【时效警告】结果可能已过期\n1. old news"
    ctx = ValidationContext(tool_name="web_search", raw=raw)
    result = validate_web_search(ctx)
    assert result.severity == "warn"
    assert result.evidence.get("freshness_warning") is True


def test_web_search_validator_fail_on_marker():
    raw = "【核对失败】联网搜索结果未通过核对"
    ctx = ValidationContext(tool_name="web_search", raw=raw)
    result = validate_web_search(ctx)
    assert result.severity == "fail"
