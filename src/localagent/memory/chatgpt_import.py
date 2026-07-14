"""Import memories from ChatGPT export JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from localagent import config
from localagent.ingest.progress import ProgressEvent, ProgressReporter
from localagent.memory.save import confirm_save_extracted, confirm_save_facts
from localagent.memory.value_filter import is_narrative_memory
from localagent.models.router import get_model_router
from localagent.persist.chatgpt import (
    ChatGPTConversation,
    format_conversation_text,
    load_conversations_file,
    timestamp_to_iso,
)
from localagent.persist.chatgpt_memories import (
    ChatGPTSavedMemory,
    detect_chatgpt_export_kind,
    is_memory_export_filename,
    load_memories_file,
)

_MEMORY_INDEX_PREFIX = "mem:"


def _format_fact_details(facts: list[str]) -> list[str]:
    return [f"{index}. {fact}" for index, fact in enumerate(facts, start=1)]


def _report_skip(
    reporter: ProgressReporter | None,
    *,
    skip_reason: str | None,
    interactive: bool,
) -> None:
    if reporter is None or interactive or not skip_reason:
        return
    messages = {
        "do_not_remember": "→ 跳过（Do not remember）",
        "empty": "→ 跳过（无内容）",
        "duplicate": "→ 跳过（已导入）",
        "no_facts": "→ 未提取到记忆",
        "disabled": "→ 跳过（已禁用）",
    }
    if skip_reason.startswith("failed:"):
        message = f"→ 失败: {skip_reason[7:]}"
    else:
        message = messages.get(skip_reason)
    if message:
        reporter.update(ProgressEvent(phase="skip", message=message))


def _report_extracted_facts(
    reporter: ProgressReporter | None,
    facts: list[str],
    *,
    interactive: bool,
) -> None:
    if reporter is None or interactive or not facts:
        return
    reporter.update(
        ProgressEvent(
            phase="facts",
            message=f"→ {len(facts)} 条记忆",
            details=_format_fact_details(facts),
        )
    )


def _report_saved(
    reporter: ProgressReporter | None,
    saved_count: int,
    *,
    interactive: bool,
) -> None:
    if reporter is None or interactive or not saved_count:
        return
    reporter.update(ProgressEvent(phase="saved", message=f"✓ 已保存 {saved_count} 条"))


@dataclass
class ImportSummary:
    files_processed: int = 0
    conversations_total: int = 0
    memories_total: int = 0
    skipped_do_not_remember: int = 0
    skipped_empty: int = 0
    skipped_disabled: int = 0
    skipped_duplicate: int = 0
    failed: int = 0
    imported: int = 0
    saved_count: int = 0
    errors: list[str] = field(default_factory=list)

    def format_summary(self) -> str:
        parts = [
            f"files={self.files_processed}",
            f"conversations={self.conversations_total}",
            f"memories={self.memories_total}",
            f"imported={self.imported}",
            f"saved={self.saved_count}",
            (
                "skipped("
                f"dnr={self.skipped_do_not_remember}, "
                f"empty={self.skipped_empty}, "
                f"disabled={self.skipped_disabled}, "
                f"dup={self.skipped_duplicate}, "
                f"failed={self.failed})"
            ),
        ]
        return ", ".join(parts)


def _load_index() -> dict[str, dict]:
    path = config.CHATGPT_IMPORT_INDEX_FILE
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        processed = raw.get("processed", {})
        return processed if isinstance(processed, dict) else {}
    except Exception:
        return {}


def _save_index(processed: dict[str, dict]) -> None:
    config.ensure_data_dirs()
    config.CHATGPT_IMPORT_INDEX_FILE.write_text(
        json.dumps({"processed": processed}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _mark_processed(
    processed: dict[str, dict],
    conversation: ChatGPTConversation,
    *,
    source_file: str,
    saved_count: int,
    persist: bool = True,
) -> None:
    processed[conversation.conversation_id] = {
        "conversation_id": conversation.conversation_id,
        "title": conversation.title,
        "source_file": source_file,
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "saved_count": saved_count,
    }
    if persist:
        _save_index(processed)


def import_conversation(
    conversation: ChatGPTConversation,
    *,
    source_file: str,
    force: bool = False,
    processed: dict[str, dict] | None = None,
    interactive: bool = False,
    reporter: ProgressReporter | None = None,
) -> tuple[int, str | None]:
    """
    Import one conversation and save extracted memories.

    Returns (saved_count, skip_reason).
    skip_reason is one of: do_not_remember, empty, duplicate, no_facts, failed.
    """
    if processed is None:
        processed = _load_index()

    if conversation.is_do_not_remember:
        _report_skip(reporter, skip_reason="do_not_remember", interactive=interactive)
        return 0, "do_not_remember"

    if not conversation.conversation_id:
        _report_skip(reporter, skip_reason="empty", interactive=interactive)
        return 0, "empty"

    if not force and conversation.conversation_id in processed:
        _report_skip(reporter, skip_reason="duplicate", interactive=interactive)
        return 0, "duplicate"

    if not conversation.messages:
        _report_skip(reporter, skip_reason="empty", interactive=interactive)
        return 0, "empty"

    text = format_conversation_text(conversation)
    router = get_model_router()
    try:
        memories = router.extract_memories(
            text,
            context=(
                f"chatgpt import title={conversation.title!r} "
                f"conversation_id={conversation.conversation_id}"
            ),
        )
    except RuntimeError as exc:
        _report_skip(reporter, skip_reason=f"failed:{exc}", interactive=interactive)
        return 0, f"failed:{exc}"
    if not memories:
        _mark_processed(processed, conversation, source_file=source_file, saved_count=0)
        _report_skip(reporter, skip_reason="no_facts", interactive=interactive)
        return 0, "no_facts"

    facts = [m.text for m in memories]
    title = conversation.title or conversation.conversation_id[:12]
    _report_extracted_facts(reporter, facts, interactive=interactive)
    metadata: dict[str, object] = {
        "source": "import-chatgpt",
        "session_id": f"chatgpt:{conversation.conversation_id}",
        "conversation_id": conversation.conversation_id,
        "source_file": source_file,
    }
    conv_created = timestamp_to_iso(conversation.create_time)
    conv_updated = timestamp_to_iso(conversation.update_time)
    if conv_created:
        metadata["chatgpt_created_at"] = conv_created
        metadata["recorded_at"] = conv_created
    if conv_updated:
        metadata["chatgpt_updated_at"] = conv_updated
    ids = confirm_save_extracted(
        memories,
        metadata=metadata,
        title=f"《{title}》提取到 {len(memories)} 条记忆",
        interactive=interactive,
    )
    _report_saved(reporter, len(ids), interactive=interactive)
    _mark_processed(processed, conversation, source_file=source_file, saved_count=len(ids))
    return len(ids), None


def _memory_index_key(memory_id: str) -> str:
    return f"{_MEMORY_INDEX_PREFIX}{memory_id}"


def _mark_memory_processed(
    processed: dict[str, dict],
    memory: ChatGPTSavedMemory,
    *,
    source_file: str,
    saved_count: int,
    persist: bool = True,
) -> None:
    processed[_memory_index_key(memory.memory_id)] = {
        "memory_id": memory.memory_id,
        "source_file": source_file,
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "saved_count": saved_count,
        "content_preview": memory.content[:80],
    }
    if persist:
        _save_index(processed)


def import_saved_memory(
    memory: ChatGPTSavedMemory,
    *,
    source_file: str,
    force: bool = False,
    include_disabled: bool = False,
    processed: dict[str, dict] | None = None,
    interactive: bool = False,
    reporter: ProgressReporter | None = None,
) -> tuple[int, str | None]:
    """Import one ChatGPT saved memory (memory.json entry). Returns (saved_count, skip_reason)."""
    if processed is None:
        processed = _load_index()

    if not memory.content.strip():
        _report_skip(reporter, skip_reason="empty", interactive=interactive)
        return 0, "empty"

    if not include_disabled and not memory.enabled:
        _report_skip(reporter, skip_reason="disabled", interactive=interactive)
        return 0, "disabled"

    if not is_narrative_memory(memory.content):
        _report_skip(reporter, skip_reason="no_facts", interactive=interactive)
        return 0, "no_facts"

    index_key = _memory_index_key(memory.memory_id)
    if not force and index_key in processed:
        _report_skip(reporter, skip_reason="duplicate", interactive=interactive)
        return 0, "duplicate"

    metadata = {
        "source": "import-chatgpt-memory",
        "chatgpt_memory_id": memory.memory_id,
        "source_file": source_file,
        "enabled": memory.enabled,
        # Saved memories already carry a recording time; inline years are often future plans.
        "extract_occurred_from_text": False,
    }
    if memory.created_at:
        metadata["chatgpt_created_at"] = memory.created_at
        metadata["recorded_at"] = memory.created_at
    if memory.updated_at:
        metadata["chatgpt_updated_at"] = memory.updated_at

    _report_extracted_facts(reporter, [memory.content], interactive=interactive)
    ids = confirm_save_facts(
        [memory.content],
        metadata=metadata,
        title=f"ChatGPT 记忆 {memory.memory_id[:12]}",
        interactive=interactive,
    )
    saved_count = len(ids)
    _report_saved(reporter, saved_count, interactive=interactive)
    _mark_memory_processed(
        processed,
        memory,
        source_file=source_file,
        saved_count=saved_count,
    )
    return saved_count, None


def import_chatgpt_memories_file(
    path: Path,
    *,
    force: bool = False,
    include_disabled: bool = False,
    reporter: ProgressReporter | None = None,
    interactive: bool = False,
) -> ImportSummary:
    summary = ImportSummary()
    if not path.exists():
        summary.errors.append(f"file not found: {path}")
        return summary
    if not path.is_file():
        summary.errors.append(f"not a file: {path}")
        return summary

    if reporter is not None:
        reporter.update(ProgressEvent(phase="load", message=f"读取记忆 {path.name}"))

    try:
        memories = load_memories_file(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        summary.errors.append(f"{path.name}: {exc}")
        return summary

    summary.files_processed = 1
    summary.memories_total = len(memories)
    processed = _load_index()
    source_file = path.name
    total = len(memories)

    if reporter is not None:
        reporter.update(
            ProgressEvent(
                phase="import",
                message=f"导入 {path.name} 中的 ChatGPT 记忆",
                current=0,
                total=total,
            )
        )

    for index, memory in enumerate(memories, start=1):
        if reporter is not None:
            preview = memory.content[:40] + ("…" if len(memory.content) > 40 else "")
            reporter.update(
                ProgressEvent(
                    phase="memory",
                    message=f"写入记忆: {preview}",
                    current=index,
                    total=total,
                )
            )
        saved_count, skip_reason = import_saved_memory(
            memory,
            source_file=source_file,
            force=force,
            include_disabled=include_disabled,
            processed=processed,
            interactive=interactive,
            reporter=reporter,
        )
        _apply_memory_import_result(summary, saved_count, skip_reason)

    return summary


def _apply_memory_import_result(
    summary: ImportSummary,
    saved_count: int,
    skip_reason: str | None,
) -> None:
    if skip_reason == "disabled":
        summary.skipped_disabled += 1
    elif skip_reason == "duplicate":
        summary.skipped_duplicate += 1
    elif skip_reason == "empty":
        summary.skipped_empty += 1
    elif saved_count:
        summary.imported += 1
        summary.saved_count += saved_count


def import_chatgpt_file(
    path: Path,
    *,
    force: bool = False,
    include_disabled: bool = False,
    reporter: ProgressReporter | None = None,
    interactive: bool = False,
) -> ImportSummary:
    summary = ImportSummary()
    if not path.exists():
        summary.errors.append(f"file not found: {path}")
        return summary
    if not path.is_file():
        summary.errors.append(f"not a file: {path}")
        return summary

    if reporter is not None:
        reporter.update(ProgressEvent(phase="load", message=f"读取 {path.name}"))

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        kind = detect_chatgpt_export_kind(raw, filename=path.name)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        summary.errors.append(f"{path.name}: {exc}")
        return summary

    if kind == "memories":
        return import_chatgpt_memories_file(
            path,
            force=force,
            include_disabled=include_disabled,
            reporter=reporter,
            interactive=interactive,
        )

    try:
        conversations = load_conversations_file(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        summary.errors.append(f"{path.name}: {exc}")
        return summary

    summary.files_processed = 1
    summary.conversations_total = len(conversations)
    processed = _load_index()
    source_file = path.name
    total = len(conversations)

    if reporter is not None:
        reporter.update(
            ProgressEvent(
                phase="import",
                message=f"处理 {path.name} 中的对话",
                current=0,
                total=total,
            )
        )

    for index, conversation in enumerate(conversations, start=1):
        if reporter is not None:
            title = conversation.title[:40] or conversation.conversation_id[:12]
            reporter.update(
                ProgressEvent(
                    phase="conversation",
                    message=f"提取记忆: {title}",
                    current=index,
                    total=total,
                )
            )
        saved_count, skip_reason = import_conversation(
            conversation,
            source_file=source_file,
            force=force,
            processed=processed,
            interactive=interactive,
            reporter=reporter,
        )
        _apply_import_result(summary, conversation, saved_count, skip_reason)

    return summary


def _apply_import_result(
    summary: ImportSummary,
    conversation: ChatGPTConversation,
    saved_count: int,
    skip_reason: str | None,
) -> tuple[int, str | None]:
    if skip_reason == "do_not_remember":
        summary.skipped_do_not_remember += 1
    elif skip_reason == "duplicate":
        summary.skipped_duplicate += 1
    elif skip_reason in ("empty", "no_facts"):
        summary.skipped_empty += 1
    elif skip_reason and skip_reason.startswith("failed:"):
        summary.failed += 1
        summary.errors.append(
            f"{conversation.title or conversation.conversation_id}: {skip_reason[7:]}"
        )
    elif saved_count:
        summary.imported += 1
        summary.saved_count += saved_count
    return saved_count, skip_reason


def _import_chatgpt_json_path(
    path: Path,
    *,
    force: bool = False,
    include_disabled: bool = False,
    reporter: ProgressReporter | None = None,
    interactive: bool = False,
    processed: dict[str, dict] | None = None,
) -> ImportSummary:
    """Import one JSON file, auto-detecting conversations vs saved memories."""
    summary = ImportSummary()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        kind = detect_chatgpt_export_kind(raw, filename=path.name)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        summary.errors.append(f"{path.name}: {exc}")
        return summary

    if kind == "memories":
        try:
            memories = load_memories_file(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            summary.errors.append(f"{path.name}: {exc}")
            return summary

        summary.files_processed = 1
        summary.memories_total = len(memories)
        if processed is None:
            processed = _load_index()
        source_file = path.name
        total = len(memories)

        for index, memory in enumerate(memories, start=1):
            if reporter is not None:
                preview = memory.content[:40] + ("…" if len(memory.content) > 40 else "")
                reporter.update(
                    ProgressEvent(
                        phase="memory",
                        message=f"写入记忆: {preview}",
                        current=index,
                        total=total,
                    )
                )
            saved_count, skip_reason = import_saved_memory(
                memory,
                source_file=source_file,
                force=force,
                include_disabled=include_disabled,
                processed=processed,
                interactive=interactive,
                reporter=reporter,
            )
            _apply_memory_import_result(summary, saved_count, skip_reason)
        return summary

    try:
        conversations = load_conversations_file(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        summary.errors.append(f"{path.name}: {exc}")
        return summary

    summary.files_processed = 1
    summary.conversations_total = len(conversations)
    if processed is None:
        processed = _load_index()
    source_file = path.name
    total = len(conversations)

    for index, conversation in enumerate(conversations, start=1):
        if reporter is not None:
            title = conversation.title[:40] or conversation.conversation_id[:12]
            reporter.update(
                ProgressEvent(
                    phase="conversation",
                    message=f"提取记忆: {title}",
                    current=index,
                    total=total,
                )
            )
        saved_count, skip_reason = import_conversation(
            conversation,
            source_file=source_file,
            force=force,
            processed=processed,
            interactive=interactive,
            reporter=reporter,
        )
        _apply_import_result(summary, conversation, saved_count, skip_reason)
    return summary


def _merge_import_summaries(target: ImportSummary, source: ImportSummary) -> None:
    target.files_processed += source.files_processed
    target.conversations_total += source.conversations_total
    target.memories_total += source.memories_total
    target.skipped_do_not_remember += source.skipped_do_not_remember
    target.skipped_empty += source.skipped_empty
    target.skipped_disabled += source.skipped_disabled
    target.skipped_duplicate += source.skipped_duplicate
    target.failed += source.failed
    target.imported += source.imported
    target.saved_count += source.saved_count
    target.errors.extend(source.errors)


def import_chatgpt_dir(
    directory: Path,
    *,
    force: bool = False,
    include_disabled: bool = False,
    reporter: ProgressReporter | None = None,
    interactive: bool = False,
) -> ImportSummary:
    summary = ImportSummary()
    if not directory.exists():
        summary.errors.append(f"directory not found: {directory}")
        return summary
    if not directory.is_dir():
        summary.errors.append(f"not a directory: {directory}")
        return summary

    files = sorted(
        path
        for path in directory.glob("*.json")
        if path.is_file()
    )
    if not files:
        summary.errors.append(f"no *.json files in {directory}")
        return summary

    memory_files = [path for path in files if is_memory_export_filename(path.name)]
    conversation_files = [path for path in files if path not in memory_files]

    if reporter is not None:
        reporter.update(
            ProgressEvent(
                phase="scan",
                message=(
                    f"发现 {len(conversation_files)} 个对话文件、"
                    f"{len(memory_files)} 个记忆文件"
                ),
                current=0,
                total=len(files),
            )
        )

    processed = _load_index()
    ordered_files = memory_files + conversation_files
    for file_index, path in enumerate(ordered_files, start=1):
        if reporter is not None:
            reporter.update(
                ProgressEvent(
                    phase="file",
                    message=f"读取 {path.name}",
                    current=file_index,
                    total=len(ordered_files),
                )
            )
        file_summary = _import_chatgpt_json_path(
            path,
            force=force,
            include_disabled=include_disabled,
            reporter=reporter,
            interactive=interactive,
            processed=processed,
        )
        _merge_import_summaries(summary, file_summary)

    return summary


def import_chatgpt_files(
    paths: list[Path],
    *,
    force: bool = False,
    include_disabled: bool = False,
    reporter: ProgressReporter | None = None,
    interactive: bool = False,
) -> ImportSummary:
    """Import one or more ChatGPT export JSON files."""
    summary = ImportSummary()
    if not paths:
        summary.errors.append("no files specified")
        return summary

    if reporter is not None:
        reporter.update(
            ProgressEvent(
                phase="scan",
                message=f"准备导入 {len(paths)} 个文件",
                current=0,
                total=len(paths),
            )
        )

    processed = _load_index()
    for file_index, path in enumerate(paths, start=1):
        if not path.exists():
            summary.errors.append(f"file not found: {path}")
            continue
        if not path.is_file():
            summary.errors.append(f"not a file: {path}")
            continue

        if reporter is not None:
            reporter.update(
                ProgressEvent(
                    phase="file",
                    message=f"读取 {path.name}",
                    current=file_index,
                    total=len(paths),
                )
            )
        file_summary = _import_chatgpt_json_path(
            path,
            force=force,
            include_disabled=include_disabled,
            reporter=reporter,
            interactive=interactive,
            processed=processed,
        )
        _merge_import_summaries(summary, file_summary)

    return summary


def reset_chatgpt_import_index() -> None:
    """Clear import dedupe index (tests)."""
    if config.CHATGPT_IMPORT_INDEX_FILE.exists():
        config.CHATGPT_IMPORT_INDEX_FILE.unlink()
