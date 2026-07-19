"""Unified ingest engine smoke tests."""

from __future__ import annotations

from pathlib import Path

from localagent.cli import main
from localagent.ingest.engine import run_ingest
from localagent.ingest.types import IngestStage, SourceKind
from localagent.memory.store import get_memory_store


def test_hard_cut_old_write_commands(isolated_data, capsys):
    assert main(["memory", "add", "should not write"]) == 2
    out = capsys.readouterr().out
    assert "已移除" in out
    assert "ingest text" in out
    assert get_memory_store().count() == 0

    assert main(["memory", "ingest", "chat"]) == 2
    assert "已移除" in capsys.readouterr().out

    assert main(["rag", "add", "/tmp/x.md"]) == 2
    assert "ingest doc" in capsys.readouterr().out

    assert main(["rag", "ingest"]) == 2
    assert main(["rag", "rebuild"]) == 2


def test_ingest_text_four_stages(isolated_data, capsys):
    before = get_memory_store().count()
    report = run_ingest(SourceKind.TEXT, text="2026年用户决定用 LA ingest 统一写入路径")
    assert IngestStage.PERSIST.value in report.stages_done
    assert IngestStage.COLD.value in report.stages_done
    assert IngestStage.WARM.value in report.stages_done
    assert report.warm_saved >= 1
    assert report.cold_chunks >= 1
    assert report.persisted_paths
    assert get_memory_store().count() == before + report.warm_saved

    rc = main(["ingest", "text", "另一条通过 CLI 写入的记忆事实"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ingest text" in out
    assert "warm=" in out.lower() or "Warm" in out or "cold=" in out


def test_ingest_doc_and_kb(isolated_data, tmp_path: Path, capsys):
    doc = tmp_path / "note.md"
    doc.write_text("# 笔记\n\n短文档入库测试。\n", encoding="utf-8")
    rc = main(["ingest", "doc", str(doc)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ingest doc" in out

    rc = main(["ingest", "kb"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ingest kb" in out


def test_ingest_chatgpt_archives_export(isolated_data, tmp_path: Path):
    from localagent import config
    import json

    from tests.test_chatgpt_import import _make_conversation, _sample_export

    export = tmp_path / "conversations.json"
    export.write_text(
        json.dumps(_sample_export(_make_conversation(conversation_id="archive-c1")), ensure_ascii=False),
        encoding="utf-8",
    )
    isolated_data["router"].extract_memories.return_value = []
    report = run_ingest(SourceKind.CHATGPT, paths=[export], force=True)
    assert report.persisted_paths
    archived = Path(report.persisted_paths[0])
    assert archived.parent.resolve() == config.CHATGPT_DATA_DIR.resolve()
    assert archived.is_file()
