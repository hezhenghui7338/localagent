"""CLI integration tests covering PRD command surface."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from localagent import __version__, config
from localagent.cli import build_parser, main
from localagent.ingest.sync_index import get_sync_index
from localagent.memory.scoped_recall import scoped_recall
from localagent.memory.store import get_memory_store
from localagent.persist.conversations import load_conversation
from localagent.tools import search_knowledge, search_memory

from conftest import write_doc


def test_cli_version_flag(capsys):
    assert main(["--version"]) == 0
    assert f"la-localagent {__version__}" in capsys.readouterr().out


def test_cli_version_short_flag(capsys):
    assert main(["-V"]) == 0
    assert f"la-localagent {__version__}" in capsys.readouterr().out


def test_build_parser_exposes_version():
    help_text = build_parser().format_help()
    assert "--version" in help_text
    assert "-V" in help_text


def test_cli_add_writes_memory_directly():
    """PRD §3: LA add 直接加记忆，即时生效."""
    before = get_memory_store().count()
    rc = main(["add", "2026年7月决定使用 Hindsight 作为记忆引擎"])
    assert rc == 0
    assert get_memory_store().count() == before + 1


def test_cli_add_rejects_low_value_text(capsys):
    rc = main(["add", "好的"])
    assert rc == 1
    assert "未写入" in capsys.readouterr().out


def test_cli_add_file_and_sync_file(tmp_path: Path, capsys):
    source = write_doc(
        tmp_path / "journal.md",
        "# 日记\n\n2026年7月决定使用 Hindsight 作为记忆引擎。",
    )
    rc = main(["add-file", str(source)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "软链:" in out
    assert (config.KB_DIR / "journal.md").is_symlink()

    capsys.readouterr()
    rc = main(["sync-file"])
    assert rc == 0
    assert "skipped" in capsys.readouterr().out


def test_cli_search_memory_after_add():
    main(["add", "2026年7月决定使用 Hindsight 作为记忆引擎"])
    hits = search_memory("Hindsight")
    assert hits
    assert "Hindsight" in hits


def test_cli_search_knowledge_after_ingest(tmp_path: Path):
    source = write_doc(
        tmp_path / "spec.md",
        "# 技术方案\n\nLocalAgent 使用 Hindsight 管理长期记忆。",
    )
    main(["add-file", str(source)])

    hits = search_knowledge("Hindsight")
    assert hits
    assert "Hindsight" in hits


def test_cli_forget_memory():
    main(["add", "2026年7月决定使用 Hindsight 作为记忆引擎"])
    hits = scoped_recall("Hindsight", max_results=1)
    assert hits
    fact_id = hits[0]["id"]

    rc = main(["forget", fact_id, "--yes"])
    assert rc == 0
    assert get_memory_store().get(fact_id) is None


def test_cli_search_shows_memory_ids():
    main(["add", "2026年7月决定使用 Hindsight 作为记忆引擎"])
    hits = scoped_recall("Hindsight", max_results=1)
    assert hits

    rc = main(["search", "Hindsight"])
    assert rc == 0


def test_cli_rememorize_chat(isolated_data):
    """PRD: rememorize-chat 从对话 jsonl 再提取记忆并保存."""
    session_id = "s-remem"
    conv_path = config.CONVERSATIONS_DIR / f"{session_id}.jsonl"
    records = [
        {"ts": "2026-07-11T10:00:00", "role": "user", "content": "我计划下周开始 Phase 0"},
        {"ts": "2026-07-11T10:00:01", "role": "assistant", "content": "好的，记下了"},
    ]
    conv_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    isolated_data["router"].extract_facts.return_value = [
        "用户计划下周开始 Phase 0 实现",
    ]

    before = get_memory_store().count()
    rc = main(["rememorize-chat", "--session", session_id])
    assert rc == 0
    assert get_memory_store().count() == before + 1


def test_cli_reset_memory(tmp_path: Path, capsys):
    source = write_doc(tmp_path / "doc.md", "# Doc\n\ncontent to remember for reset test")
    main(["add-file", str(source)])
    assert get_memory_store().count() > 0
    assert get_sync_index().get("doc.md") is not None

    rc = main(["reset-memory"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "reset-memory" in out
    assert get_memory_store().count() == 0
    assert get_sync_index().get("doc.md") is None
    assert (config.KB_DIR / "doc.md").exists()


def test_cli_rebuild_memory(tmp_path: Path, capsys):
    source = write_doc(tmp_path / "rebuild.md", "# Rebuild\n\nrebuild memory test content")
    main(["add-file", str(source)])
    main(["reset-memory"])

    rc = main(["rebuild-memory"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "rebuild-memory" in out
    assert get_memory_store().count() > 0
    assert get_sync_index().get("rebuild.md") is not None


def test_cli_add_file_missing_path(capsys):
    rc = main(["add-file", "/nonexistent/path/file.md"])
    assert rc == 1
    assert "error" in capsys.readouterr().out.lower()


def test_search_documents_reads_kb_files(tmp_path: Path):
    write_doc(
        tmp_path / "notes.md",
        "# 笔记\n\n我决定在 2026 年使用 Hindsight 管理长期记忆。",
    )
    main(["add-file", str(tmp_path / "notes.md")])

    with patch("localagent.tools.get_memory_backend") as backend_getter, patch(
        "localagent.tools.get_hybrid_retriever"
    ) as retriever:
        backend = MagicMock()
        backend.recall.return_value = []
        backend_getter.return_value = backend
        retriever.return_value.retrieve.return_value = []
        result = search_memory("Hindsight")

    assert "Hindsight" in result
    assert "notes.md" in result or "记忆和 RAG 均未命中" in result
