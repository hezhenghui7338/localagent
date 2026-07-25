"""Tests for structured profile compilation."""

from __future__ import annotations

from localagent.ingest.doc_classifier import DocType, classify_document
from localagent.memory.compile.engine import (
    ProfileCompileResult,
    apply_compile_result,
    compile_all_sources,
    compile_document_profile,
    compile_kb_profiles,
    compile_warm_identity_facts,
)
from localagent.memory.compile.resume import _rule_bootstrap_updates, compile_resume
from localagent.memory.conversation_extract import ExtractedMemory
from localagent.memory.core_profile import CoreProfile, WorkEntry, load_core_profile, save_core_profile
from localagent.memory.profile_pin import apply_profile_updates, pin_from_memory_slots


RESUME_HTML = """<!doctype html>
<html lang="zh-CN">
<head><title>何征辉个人简历</title></head>
<body>
  <h1>何征辉</h1>
  <p>现居深圳 · 可立即到岗</p>
  <p>求职意向：AI Agent 开发 / 项目管理</p>
  <h2>技术栈</h2>
  <p>AI：LLM、AI Agent、RAG</p>
  <h2>工作经历</h2>
  <h3>某科技公司 · 开发负责人</h3>
  <p>2020 - 至今：主导 AI 平台建设</p>
</body>
</html>
"""


def test_classify_resume_document():
    assert classify_document(filename="简历-何征辉.html", text=RESUME_HTML) == DocType.RESUME


def test_rule_bootstrap_updates_from_resume_html():
    updates = _rule_bootstrap_updates(RESUME_HTML, source="简历-何征辉.html")
    fields = {u["field"] for u in updates}
    assert "name" in fields
    assert any(u.get("key") == "居住地" for u in updates if u["field"] == "preference")
    assert "goal" in fields


def test_apply_profile_updates_extended_schema(isolated_data):
    assert apply_profile_updates(
        [
            {"field": "name", "value": "何征辉", "confidence": 0.95},
            {"field": "skill", "category": "AI", "value": "LLM, RAG, AI Agent", "confidence": 0.9},
            {
                "field": "work_entry",
                "company": "某科技公司",
                "role": "开发负责人",
                "start": "2020",
                "confidence": 0.9,
            },
            {"field": "project", "name": "LocalAgent", "description": "本地 AI 助手", "confidence": 0.9},
            {"field": "goal", "value": "AI Agent 开发", "confidence": 0.9},
        ]
    )
    profile = load_core_profile()
    assert profile.name == "何征辉"
    assert "AI" in profile.skills
    assert any("LLM" in item for item in profile.skills["AI"])
    assert len(profile.work_experience) == 1
    assert profile.work_experience[0].company == "某科技公司"
    assert len(profile.projects) == 1
    assert "AI Agent 开发" in profile.goals


def test_pin_from_memory_slots(isolated_data):
    memories = [
        ExtractedMemory(
            text="用户住在深圳。",
            slots={"subject": "用户", "location": "深圳"},
            memory_type="fact",
        ),
        ExtractedMemory(
            text="用户是一名后端工程师。",
            slots={"subject": "用户", "object": "后端工程师"},
            memory_type="fact",
        ),
    ]
    assert pin_from_memory_slots(memories)
    profile = load_core_profile()
    assert profile.preferences.get("居住地") == "深圳"
    assert profile.preferences.get("职业") == "后端工程师"


def test_compile_resume_rule_fallback(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.PROFILE_PIN_LLM", False)

    def _fail_chat(*args, **kwargs):
        raise RuntimeError("offline")

    isolated_data["router"].chat.side_effect = _fail_chat
    result = compile_resume(RESUME_HTML, filename="简历-何征辉.html", source="简历-何征辉.html")
    assert result.profile_updates
    stats = apply_compile_result(result)
    profile = load_core_profile()
    assert profile.name == "何征辉"
    assert profile.preferences.get("居住地") == "深圳"
    assert stats["profile_updates"] >= 1


def test_format_for_prompt_budget(isolated_data):
    save_core_profile(
        CoreProfile(
            name="何征辉",
            current_status="AI 开发者",
            preferences={"居住地": "深圳"},
            skills={"AI": ["LLM", "RAG", "Agent", "Tool Calling", "Memory"]},
            work_experience=[
                WorkEntry(company="A公司", role="工程师", start="2020"),
                WorkEntry(company="B公司", role="负责人", start="2018", end="2020"),
            ],
            goals=["AI Agent 开发"],
        )
    )
    profile = load_core_profile()
    prompt = profile.format_for_prompt(max_chars=200)
    assert len(prompt) <= 203
    assert "何征辉" in prompt


def test_apply_compile_result_with_warm_memories(isolated_data):
    result = ProfileCompileResult(
        profile_updates=[{"field": "name", "value": "测试", "confidence": 0.9}],
        warm_memories=[ExtractedMemory(text="用户主导 LocalAgent 项目。")],
        source="test.md",
    )
    stats = apply_compile_result(result)
    assert stats["warm_saved"] == 1
    assert load_core_profile().name == "测试"


RESUME_MD = """李四

现居北京 · 可立即到岗

## 求职意向
后端开发

## 技术栈
Python, Go

## 工作经历
### 测试公司 · 工程师
2021 - 至今：负责 API 开发

## 教育背景
某大学 计算机
"""


def test_compile_document_profile_general_returns_empty():
    result = compile_document_profile(
        filename="notes.md",
        text="普通笔记内容，没有简历特征。",
    )
    assert result.doc_type == DocType.GENERAL
    assert not result.profile_updates
    assert not result.warm_memories


def test_compile_kb_profiles_scans_resume(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.PROFILE_PIN_LLM", False)
    resume_path = isolated_data["kb_dir"] / "简历-李四.md"
    resume_path.write_text(RESUME_MD, encoding="utf-8")

    stats = compile_kb_profiles()
    assert stats["files"] == 1
    assert stats["profile_updates"] >= 1
    profile = load_core_profile()
    assert profile.name == "李四"


def test_compile_kb_profiles_skips_general(isolated_data):
    notes_path = isolated_data["kb_dir"] / "notes.md"
    notes_path.write_text("# Notes\n\n普通文档内容。\n", encoding="utf-8")

    stats = compile_kb_profiles()
    assert stats["files"] == 0
    assert stats["profile_updates"] == 0


def test_compile_warm_identity_facts_pins_matching(isolated_data):
    from localagent.memory.backend import get_memory_backend

    backend = get_memory_backend()
    backend.retain("我叫王五，是一名后端工程师。", metadata={"source": "chat", "type": "fact"})
    backend.retain("今天天气不错。", metadata={"source": "chat", "type": "fact"})

    stats = compile_warm_identity_facts()
    assert stats["facts_scanned"] >= 1
    profile = load_core_profile()
    assert profile.name == "王五" or profile.preferences.get("职业")


def test_compile_all_sources_merges_kb_and_warm(isolated_data, monkeypatch):
    monkeypatch.setattr("localagent.config.PROFILE_PIN_LLM", False)
    (isolated_data["kb_dir"] / "简历-合并.md").write_text(RESUME_MD.replace("李四", "赵六"), encoding="utf-8")
    from localagent.memory.backend import get_memory_backend

    get_memory_backend().retain("用户居住在上海。", metadata={"source": "chat"})

    merged = compile_all_sources(source="all")
    assert "kb_files" in merged
    assert "warm_facts_scanned" in merged
    assert merged["kb_files"] >= 1
