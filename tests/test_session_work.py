"""Session working memory tests."""

from __future__ import annotations

from localagent.agent.planner.state import ActionPlan, Milestone
from localagent.persist.session_work import (
    clear_session_work,
    format_work_prefetch,
    is_continue_query,
    load_session_work,
    plan_to_work_dict,
    resume_action_plan,
    save_session_work,
    sync_session_work,
    tool_targets_from_calls,
    work_path,
    work_stale,
    work_to_action_plan,
)


def test_is_continue_query():
    assert is_continue_query("继续")
    assert is_continue_query("请接着改")
    assert is_continue_query("continue please")
    assert not is_continue_query("今天天气怎么样")


def test_tool_targets_from_calls_dedupes():
    calls = [
        {"name": "read_file", "arguments": {"path": "src/a.py"}},
        {"name": "edit_file", "arguments": {"path": "src/a.py"}},
        {"name": "write_file", "arguments": {"path": "src/b.py"}},
    ]
    assert tool_targets_from_calls(calls) == ["src/a.py", "src/b.py"]


def test_plan_to_work_dict_and_prefetch():
    plan = ActionPlan(
        goal="修复测试",
        milestones=[
            Milestone(id="m1", objective="读文件", done_when="ok", status="done"),
            Milestone(id="m2", objective="改代码", done_when="ok", status="pending"),
        ],
    )
    work = {
        "active_plan": plan_to_work_dict(plan, partial=True),
        "last_tool_targets": ["src/foo.py"],
    }
    text = format_work_prefetch(work)
    assert "【进行中的任务】" in text
    assert "修复测试" in text
    assert "读文件" in text
    assert "改代码" in text
    assert "src/foo.py" in text


def test_session_work_roundtrip(isolated_data):
    sid = "s-testwork01"
    save_session_work(
        sid,
        {
            "active_plan": {"goal": "g", "partial": True, "milestones": []},
            "last_tool_targets": ["a.py"],
        },
    )
    path = work_path(sid)
    assert path.is_file()
    loaded = load_session_work(sid)
    assert loaded is not None
    assert loaded["active_plan"]["goal"] == "g"
    assert loaded.get("updated_at")
    clear_session_work(sid)
    assert not path.is_file()


def test_sync_session_work_partial_plan(isolated_data):
    sid = "s-testwork02"
    plan = ActionPlan(
        goal="多步任务",
        milestones=[
            Milestone(id="m1", objective="步骤一", done_when="ok", status="done"),
            Milestone(id="m2", objective="步骤二", done_when="ok", status="pending"),
        ],
    )
    sync_session_work(
        sid,
        user_message="帮我改",
        action_plan=plan,
        partial=True,
        tool_calls=[{"name": "read_file", "arguments": {"path": "x.py"}}],
    )
    stored = load_session_work(sid)
    assert stored is not None
    assert stored["active_plan"]["goal"] == "多步任务"
    assert stored["last_tool_targets"] == ["x.py"]


def test_sync_session_work_clears_on_complete(isolated_data):
    sid = "s-testwork03"
    save_session_work(
        sid,
        {
            "active_plan": {"goal": "old", "partial": True, "milestones": []},
            "last_tool_targets": [],
        },
    )
    plan = ActionPlan(
        goal="完成",
        milestones=[
            Milestone(id="m1", objective="一步", done_when="ok", status="done"),
        ],
    )
    sync_session_work(
        sid,
        user_message="done",
        action_plan=plan,
        partial=False,
        tool_calls=[],
    )
    assert load_session_work(sid) is None


def test_work_stale():
    assert work_stale(None) is True
    assert work_stale({"updated_at": "2099-01-01T00:00:00+00:00"}) is False


def test_work_to_action_plan_roundtrip():
    plan = ActionPlan(
        goal="修复测试",
        milestones=[
            Milestone(
                id="m1",
                objective="读文件",
                done_when="已知路径",
                status="done",
                summary="ok",
            ),
            Milestone(
                id="m2",
                objective="改代码",
                done_when="文件已修改",
                status="pending",
            ),
        ],
        replans_used=1,
    )
    restored = work_to_action_plan(plan_to_work_dict(plan, partial=True))
    assert restored is not None
    assert restored.goal == "修复测试"
    assert restored.replans_used == 1
    assert restored.milestones[0].status == "done"
    assert restored.milestones[1].done_when == "文件已修改"
    assert restored.pending[0].objective == "改代码"


def test_resume_action_plan_requires_continue(isolated_data):
    sid = "s-resume01"
    plan = ActionPlan(
        goal="多步",
        milestones=[
            Milestone(id="m1", objective="一步", done_when="ok", status="done"),
            Milestone(id="m2", objective="二步", done_when="ok", status="pending"),
        ],
    )
    save_session_work(
        sid,
        {"active_plan": plan_to_work_dict(plan, partial=True), "last_tool_targets": []},
    )
    assert resume_action_plan(sid, "今天天气") is None
    resumed = resume_action_plan(sid, "请继续")
    assert resumed is not None
    assert resumed.goal == "多步"
    assert len(resumed.pending) == 1
    assert resumed.pending[0].objective == "二步"
