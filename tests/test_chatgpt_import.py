"""Tests for ChatGPT export parsing and import."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from localagent import config
from localagent.cli import main
from localagent.ingest.progress import ConsoleProgressReporter
from localagent.memory.chatgpt_import import (
    import_chatgpt_file,
    import_chatgpt_files,
    import_chatgpt_memories_file,
    reset_chatgpt_import_index,
)
from localagent.memory.store import get_memory_store
from localagent.persist.chatgpt import (
    format_conversation_text,
    load_conversations_file,
    parse_conversation,
    reconstruct_messages,
    strip_cite_markers,
)
from localagent.persist.chatgpt_memories import detect_chatgpt_export_kind, load_memories_file


def _sample_export(*conversations: dict) -> list[dict]:
    return list(conversations)


def _make_conversation(
    *,
    conversation_id: str = "conv-1",
    title: str = "测试对话",
    is_do_not_remember: bool = False,
    user_text: str = "我喜欢用 Python 做数据分析",
    assistant_text: str = "好的，了解了。",
) -> dict:
    user_id = "user-node"
    assistant_id = "assistant-node"
    root_id = "root-node"
    return {
        "conversation_id": conversation_id,
        "id": conversation_id,
        "title": title,
        "create_time": 1757058223.0,
        "update_time": 1757058263.0,
        "current_node": assistant_id,
        "is_do_not_remember": is_do_not_remember,
        "mapping": {
            root_id: {"id": root_id, "parent": None, "message": None},
            user_id: {
                "id": user_id,
                "parent": root_id,
                "message": {
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": [user_text]},
                    "create_time": 1757058223.1,
                },
            },
            assistant_id: {
                "id": assistant_id,
                "parent": user_id,
                "message": {
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": [assistant_text]},
                    "create_time": 1757058223.2,
                },
            },
        },
    }


def test_reconstruct_messages_chronological_order():
    conv = parse_conversation(_make_conversation())
    assert [m.role for m in conv.messages] == ["user", "assistant"]
    assert conv.messages[0].content.startswith("我喜欢用 Python")


def test_strip_cite_markers():
    raw = "结论正确\ue200cite\ue202turn0search1\ue201，可以继续。"
    assert strip_cite_markers(raw) == "结论正确，可以继续。"


def test_skip_non_text_content_types():
    conv = _make_conversation()
    conv["mapping"]["assistant-node"]["message"]["content"]["content_type"] = "thoughts"
    parsed = parse_conversation(conv)
    assert [m.role for m in parsed.messages] == ["user"]


def test_format_conversation_text_includes_title_and_roles():
    conv = parse_conversation(_make_conversation(title="职业规划"))
    text = format_conversation_text(conv)
    assert "title: 职业规划" in text
    assert "user: 我喜欢用 Python 做数据分析" in text
    assert "assistant:" in text
    assert "[2025-09-05]" in text


def test_format_conversation_text_includes_message_timestamps():
    conv = parse_conversation(_make_conversation())
    text = format_conversation_text(conv)
    assert "[2025-09-05] user:" in text
    assert "[2025-09-05] assistant:" in text


def test_load_real_sample_file():
    sample = Path(__file__).resolve().parents[1] / "data/chatGPTdata/conversations-002.json"
    if not sample.exists():
        pytest.skip("sample export not present")
    conversations = load_conversations_file(sample)
    assert len(conversations) == 100
    assert conversations[0].title
    assert conversations[0].messages


def test_import_chatgpt_saves_memories(isolated_data, tmp_path: Path):
    export_path = tmp_path / "conversations-test.json"
    export_path.write_text(
        json.dumps(_sample_export(_make_conversation()), ensure_ascii=False),
        encoding="utf-8",
    )
    isolated_data["router"].extract_facts.return_value = ["用户喜欢用 Python 做数据分析"]

    before = get_memory_store().count()
    summary = import_chatgpt_file(export_path)
    assert summary.imported == 1
    assert summary.saved_count == 1
    assert get_memory_store().count() == before + 1
    fact = get_memory_store().all_facts()[-1]
    assert fact.created_at.startswith("2025-09-05")
    assert fact.metadata.get("chatgpt_created_at", "").startswith("2025-09-05")


def test_import_chatgpt_skips_do_not_remember(isolated_data, tmp_path: Path):
    export_path = tmp_path / "skip-dnr.json"
    export_path.write_text(
        json.dumps(
            _sample_export(_make_conversation(is_do_not_remember=True)),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = import_chatgpt_file(export_path)
    assert summary.imported == 0
    assert summary.skipped_do_not_remember == 1


def test_import_chatgpt_deduplicates_by_conversation_id(isolated_data, tmp_path: Path):
    export_path = tmp_path / "dup.json"
    export_path.write_text(
        json.dumps(_sample_export(_make_conversation()), ensure_ascii=False),
        encoding="utf-8",
    )
    isolated_data["router"].extract_facts.return_value = ["用户喜欢用 Python 做数据分析"]

    first = import_chatgpt_file(export_path)
    second = import_chatgpt_file(export_path)
    assert first.imported == 1
    assert second.imported == 0
    assert second.skipped_duplicate == 1


def test_import_chatgpt_force_reimports(isolated_data, tmp_path: Path):
    export_path = tmp_path / "force.json"
    export_path.write_text(
        json.dumps(_sample_export(_make_conversation()), ensure_ascii=False),
        encoding="utf-8",
    )
    isolated_data["router"].extract_facts.return_value = ["用户喜欢用 Python 做数据分析"]

    before = get_memory_store().count()
    import_chatgpt_file(export_path)
    forced = import_chatgpt_file(export_path, force=True)
    assert forced.imported == 1
    assert get_memory_store().count() == before + 2


def test_import_chatgpt_auto_saves_in_tty(isolated_data, tmp_path: Path, monkeypatch):
    """Default import saves without prompting even when stdin is a TTY."""
    export_path = tmp_path / "tty-auto-save.json"
    export_path.write_text(
        json.dumps(_sample_export(_make_conversation(conversation_id="tty-conv")), ensure_ascii=False),
        encoding="utf-8",
    )
    isolated_data["router"].extract_facts.return_value = ["TTY 下也应自动保存"]

    class FakeStdin:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdin", FakeStdin())

    before = get_memory_store().count()
    summary = import_chatgpt_file(export_path)
    assert summary.imported == 1
    assert summary.saved_count == 1
    assert get_memory_store().count() == before + 1


def test_import_chatgpt_reports_extracted_facts(isolated_data, tmp_path: Path, capsys):
    export_path = tmp_path / "verbose-import.json"
    fact_text = "用户计划在2026年系统学习 Rust 语言"
    export_path.write_text(
        json.dumps(_sample_export(_make_conversation()), ensure_ascii=False),
        encoding="utf-8",
    )
    isolated_data["router"].extract_facts.return_value = [fact_text]

    reporter = ConsoleProgressReporter(prefix="import-chatgpt")
    import_chatgpt_file(export_path, reporter=reporter)
    out = capsys.readouterr().out
    assert "→ 1 条记忆" in out
    assert fact_text in out
    assert "✓ 已保存 1 条" in out


def test_cli_import_chatgpt(isolated_data, tmp_path: Path, capsys):
    export_path = tmp_path / "cli-import.json"
    export_path.write_text(
        json.dumps(_sample_export(_make_conversation(conversation_id="cli-conv")), ensure_ascii=False),
        encoding="utf-8",
    )
    isolated_data["router"].extract_facts.return_value = ["用户计划在2026年系统学习 Rust 语言"]

    reset_chatgpt_import_index()
    before = get_memory_store().count()
    rc = main(["import-chatgpt", str(export_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "import-chatgpt" in out
    assert "imported=1" in out
    assert "用户计划在2026年系统学习 Rust 语言" in out
    assert get_memory_store().count() == before + 1


def test_cli_import_chatgpt_real_sample(isolated_data, capsys):
    sample = Path(__file__).resolve().parents[1] / "data/chatGPTdata/conversations-002.json"
    if not sample.exists():
        pytest.skip("sample export not present")

    reset_chatgpt_import_index()
    isolated_data["router"].extract_facts.return_value = ["用户关注 AI 视频工具"]

    rc = main(["import-chatgpt", str(sample)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "conversations=100" in out
    assert "imported=100" in out
    assert get_memory_store().count() == 100

    rc = main(["import-chatgpt", str(sample)])
    out = capsys.readouterr().out
    assert "dup=100" in out

    index = json.loads(config.CHATGPT_IMPORT_INDEX_FILE.read_text(encoding="utf-8"))
    assert len(index["processed"]) == 100


def _sample_memory_export(*entries: dict) -> list[dict]:
    return list(entries)


def test_load_memories_file_array_shape(tmp_path: Path):
    export_path = tmp_path / "memory.json"
    export_path.write_text(
        json.dumps(
            _sample_memory_export(
                {
                    "id": "mem_abc",
                    "content": "用户偏好使用 Python 做后端开发",
                    "enabled": True,
                    "created_at": "2025-09-14T11:32:00Z",
                }
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    memories = load_memories_file(export_path)
    assert len(memories) == 1
    assert memories[0].memory_id == "mem_abc"


def test_detect_chatgpt_export_kind():
    assert detect_chatgpt_export_kind([{"mapping": {}}]) == "conversations"
    assert detect_chatgpt_export_kind([{"content": "foo", "enabled": True}]) == "memories"
    assert detect_chatgpt_export_kind({"memory": [{"content": "bar"}]}) == "memories"


def test_import_chatgpt_memories_saves_directly(isolated_data, tmp_path: Path):
    export_path = tmp_path / "memory.json"
    export_path.write_text(
        json.dumps(
            _sample_memory_export(
                {
                    "id": "mem_direct",
                    "content": "用户在 2026 年计划系统学习 Rust",
                    "enabled": True,
                    "created_at": "2025-09-14T11:32:00+00:00",
                },
                {
                    "id": "mem_disabled",
                    "content": "已关闭的旧偏好",
                    "enabled": False,
                },
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    before = get_memory_store().count()
    summary = import_chatgpt_memories_file(export_path)
    assert summary.memories_total == 2
    assert summary.imported == 1
    assert summary.saved_count == 1
    assert summary.skipped_disabled == 1
    assert get_memory_store().count() == before + 1
    fact = get_memory_store().all_facts()[-1]
    assert fact.created_at.startswith("2025-09-14")


def test_import_chatgpt_memories_include_disabled(isolated_data, tmp_path: Path):
    export_path = tmp_path / "memory.json"
    export_path.write_text(
        json.dumps(
            _sample_memory_export(
                {"id": "mem_off", "content": "已关闭的记忆", "enabled": False},
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = import_chatgpt_memories_file(export_path, include_disabled=True)
    assert summary.imported == 1
    assert summary.saved_count == 1


def test_import_chatgpt_memories_deduplicates(isolated_data, tmp_path: Path):
    export_path = tmp_path / "memory.json"
    export_path.write_text(
        json.dumps(
            _sample_memory_export(
                {"id": "mem_dup", "content": "重复导入测试", "enabled": True},
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = import_chatgpt_memories_file(export_path)
    second = import_chatgpt_memories_file(export_path)
    assert first.imported == 1
    assert second.imported == 0
    assert second.skipped_duplicate == 1


def test_cli_import_chatgpt_memory_file(isolated_data, tmp_path: Path, capsys):
    export_path = tmp_path / "memory.json"
    export_path.write_text(
        json.dumps(
            _sample_memory_export(
                {"id": "mem_cli", "content": "CLI 导入 ChatGPT 记忆测试", "enabled": True},
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    reset_chatgpt_import_index()
    before = get_memory_store().count()
    rc = main(["import-chatgpt", str(export_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "import-chatgpt" in out
    assert "memories=1" in out
    assert get_memory_store().count() == before + 1


def test_import_chatgpt_files_multiple(isolated_data, tmp_path: Path):
    first_path = tmp_path / "conversations-a.json"
    second_path = tmp_path / "conversations-b.json"
    first_path.write_text(
        json.dumps(
            _sample_export(_make_conversation(conversation_id="conv-a", title="A")),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    second_path.write_text(
        json.dumps(
            _sample_export(_make_conversation(conversation_id="conv-b", title="B")),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    isolated_data["router"].extract_facts.return_value = ["多文件导入测试"]

    summary = import_chatgpt_files([first_path, second_path])
    assert summary.files_processed == 2
    assert summary.imported == 2


def test_cli_import_chatgpt_with_file_flag(isolated_data, tmp_path: Path, capsys):
    export_path = tmp_path / "conversations-file-flag.json"
    export_path.write_text(
        json.dumps(
            _sample_export(_make_conversation(conversation_id="file-flag-conv")),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    isolated_data["router"].extract_facts.return_value = ["--file 参数导入测试"]

    reset_chatgpt_import_index()
    rc = main(["import-chatgpt", "--file", str(export_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "imported=1" in out


def test_cli_import_chatgpt_file_force_reimports(isolated_data, tmp_path: Path, capsys):
    export_path = tmp_path / "conversations-force.json"
    export_path.write_text(
        json.dumps(
            _sample_export(_make_conversation(conversation_id="force-file-conv")),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    isolated_data["router"].extract_facts.return_value = ["--file --force 重载测试"]

    reset_chatgpt_import_index()
    before = get_memory_store().count()
    rc = main(["import-chatgpt", "--file", str(export_path)])
    assert rc == 0
    assert get_memory_store().count() == before + 1

    rc = main(["import-chatgpt", "--file", str(export_path)])
    out = capsys.readouterr().out
    assert "dup=1" in out

    rc = main(["import-chatgpt", "--file", str(export_path), "--force"])
    out = capsys.readouterr().out
    assert "imported=1" in out
    assert get_memory_store().count() == before + 2
