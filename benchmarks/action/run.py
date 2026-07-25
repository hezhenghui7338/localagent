#!/usr/bin/env python3
"""Run action planner benchmark scenarios (complexity gate + validation heuristics)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

# Ensure src on path when run from repo root.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from localagent.agent.planner.checker import milestone_done_heuristic  # noqa: E402
from localagent.agent.planner.complexity import should_use_milestone_mode  # noqa: E402
from localagent.agent.planner.state import Milestone  # noqa: E402
from localagent.agent.validation import ValidationResult, validate_tool_result  # noqa: E402


@dataclass
class Scenario:
    id: str
    prompt: str
    expect_milestone: bool


@dataclass
class CompletionCase:
    id: str
    tool_name: str
    observation: str
    done_when: str
    validation: ValidationResult
    expect_done: bool


SCENARIOS = [
    Scenario(
        "find-edit",
        "先 grep 找到 timeout 配置，然后改成 30",
        True,
    ),
    Scenario(
        "simple-qa",
        "Python 里 list 和 tuple 有什么区别？",
        False,
    ),
    Scenario(
        "find-run",
        "读 README 然后运行 pytest",
        True,
    ),
    Scenario(
        "glob-read",
        "用 glob 找 *.py 配置文件，读第一个",
        True,
    ),
]

COMPLETION_CASES = [
    CompletionCase(
        "shell-exit-fail",
        "run_shell",
        "$ false\nexit: 1\n（无输出）",
        "命令执行成功",
        ValidationResult.fail("exit", exit_code=1),
        False,
    ),
    CompletionCase(
        "shell-exit-ok",
        "run_shell",
        "$ pytest\nstdout:\n3 passed",
        "测试通过",
        ValidationResult.ok(exit_code=0),
        True,
    ),
    CompletionCase(
        "write-ok",
        "write_file",
        "已写入文件: cfg.py",
        "file saved",
        ValidationResult.ok(readback_ok=True),
        True,
    ),
    CompletionCase(
        "write-readback-fail",
        "write_file",
        "【核对失败】写入后 read-back 内容与预期不符。\n已写入文件: cfg.py",
        "file saved",
        ValidationResult.fail("readback", readback_failed=True),
        False,
    ),
]


def run_dry() -> None:
    planner_on = os.environ.get("LA_PLANNER_ENABLED", "1") != "0"
    print(f"Planner enabled: {planner_on}")
    print("-" * 60)

    passed = 0
    for sc in SCENARIOS:
        gate = should_use_milestone_mode(sc.prompt)
        ok = gate == sc.expect_milestone
        passed += int(ok)
        print(f"[gate:{sc.id}] gate={gate} expect={sc.expect_milestone} ok={ok}")

    print("-" * 60)
    print(f"gate accuracy: {passed}/{len(SCENARIOS)}")

    completion_passed = 0
    for case in COMPLETION_CASES:
        m = Milestone(id="m1", objective="step", done_when=case.done_when)
        done = milestone_done_heuristic(
            m,
            tool_calls=[{"name": case.tool_name}],
            last_observation=case.observation,
            last_tool_name=case.tool_name,
            last_validation=case.validation,
        )
        ok = done == case.expect_done
        completion_passed += int(ok)
        print(f"[completion:{case.id}] done={done} expect={case.expect_done} ok={ok}")

    print("-" * 60)
    print(f"completion heuristic: {completion_passed}/{len(COMPLETION_CASES)}")

    # Smoke: validation layer marks shell failures.
    annotated, vresult = validate_tool_result("run_shell", "$ cmd\nexit: 2\nstderr:\nerr")
    val_ok = vresult.severity == "fail" and "【核对失败】" in annotated
    print(f"[validation:shell-exit] severity={vresult.severity} ok={val_ok}")


if __name__ == "__main__":
    run_dry()
