"""Interactive follow-up chat scoped to a summarized document (sum> REPL)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from localagent import config
from localagent.agent.runtime import run_agent_turn
from localagent.i18n import t
from localagent.models.router import get_model_router, shutdown_cursor_sdk
from localagent.persist.conversations import append_message, load_conversation, new_session_id
from localagent.session_commands import (
    SessionCommandContext,
    dispatch_session_line,
    is_session_command,
    set_repl_provider,
)
from localagent.summarize.document import (
    SummarizeResult,
    format_document_context,
)
from localagent.summarize.model_choice import SummarizeModelChoice, format_source_label
from localagent.summarize.segment_reader import (
    advance_segment,
    build_book_context,
    format_book_context,
    format_segment_context,
    goto_segment,
    needs_cross_segment_rag,
    prev_segment,
)
from localagent.summarize.sessions import (
    mark_book_chat_entered,
    record_from_result,
    upsert_session,
)
from localagent.summarize.segment_cache import ThrottledSegmentCacheWriter
from localagent.tools.approval import SessionApprovalGate, ToolRisk, prompt_tool_approval
from localagent.ui.console import (
    ActivityIndicator,
    prepare_for_input,
    read_repl_line,
    use_prompt_toolkit_repl,
)


def _print_doc_help(*, kept: bool, segment_mode: bool = False, book_mode: bool = False) -> None:
    print(t("summarize.help_intro"))
    print(t("summarize.help_commands"))
    print(t("summarize.help_summary"))
    if book_mode:
        print(t("summarize.help_book"))
        print(t("summarize.help_segment_mode"))
    elif segment_mode:
        print(t("summarize.help_segment"))
        print(t("summarize.help_next"))
        print(t("summarize.help_prev"))
        print(t("summarize.help_goto"))
        print(t("summarize.help_progress"))
        print(t("summarize.help_book_enter"))
    print(t("summarize.help_keep"))
    if kept:
        print(t("summarize.help_keep_again"))
    print(t("summarize.help_status"))
    print(t("summarize.help_help"))
    print(t("summarize.help_provider"))
    print(t("summarize.help_quit"))
    print(t("summarize.help_ask"))


def _history_from_conversation(session_id: str) -> list[dict[str, str]]:
    rows = load_conversation(session_id)
    out: list[dict[str, str]] = []
    for row in rows:
        role = str(row.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        content = str(row.get("content") or "")
        if not content.strip():
            continue
        out.append({"role": role, "content": content})
    return out


class DocumentChatREPL:
    """REPL after ``la summarize``: multi-turn Q&A grounded on one document."""

    def __init__(
        self,
        result: SummarizeResult,
        *,
        provider: str = "auto",
        model_choice: SummarizeModelChoice | None = None,
        session_id: str | None = None,
        conversation_session_id: str | None = None,
        history: list[dict[str, str]] | None = None,
        summarize_session_id: str | None = None,
        deep_segment_only: bool = False,
        no_prefetch: bool = False,
        use_llm: bool = True,
        chat_scope: Literal["segment", "book"] = "segment",
    ) -> None:
        self.result = result
        self.summarize_session_id = summarize_session_id or session_id or new_session_id()
        self.session_id = conversation_session_id or self.summarize_session_id
        self.provider = config.normalize_provider_choice(provider)
        self.model_choice = model_choice or getattr(result, "model_choice", None)
        if self.model_choice is None:
            self.model_choice = SummarizeModelChoice.from_cli(provider=self.provider)
        else:
            self.model_choice = self.model_choice.with_provider(self.provider)
        self.result.model_choice = self.model_choice
        self.session_approval = SessionApprovalGate()
        self.deep_segment_only = deep_segment_only
        self.chat_scope = chat_scope
        self.no_prefetch = no_prefetch
        set_repl_provider(self.provider)
        if history is not None:
            self.history = list(history)
        elif chat_scope == "book" and result.segment_mode and result.reading_progress is not None:
            progress = result.reading_progress
            preview = build_book_context(
                progress,
                filename=result.filename,
                provider=self.provider,
            )
            self.history = [
                {
                    "role": "user",
                    "content": (
                        f"请基于全书各段摘要，围绕《{result.filename}》回答我的问题。"
                    ),
                },
                {"role": "assistant", "content": preview or result.markdown},
            ]
        elif result.segment_mode and result.reading_progress is not None:
            progress = result.reading_progress
            seg = progress.current
            self.history = [
                {
                    "role": "user",
                    "content": (
                        f"请总结文档第 {progress.current_index + 1}/{progress.total} 段"
                        f"（{seg.heading}）：{result.filename}"
                    ),
                },
                {"role": "assistant", "content": progress.current_summary() or result.markdown},
            ]
        else:
            self.history = [
                {
                    "role": "user",
                    "content": f"请总结这份文档并给出结构化要点：{result.filename}",
                },
                {"role": "assistant", "content": result.markdown},
            ]
        self._segment_use_llm = use_llm
        self._shown_fallback_hint = False
        self._prefetch_worker = None
        self._cache_writer = ThrottledSegmentCacheWriter()
        if (
            self._segment_active()
            and not deep_segment_only
            and chat_scope != "book"
            and config.SUMMARIZE_SEGMENT_PREFETCH
            and not no_prefetch
        ):
            from localagent.summarize.segment_prefetch import attach_prefetch_worker

            self._prefetch_worker = attach_prefetch_worker(
                self.result,
                model_choice=self.model_choice,
                use_llm=self._segment_use_llm,
                enabled=True,
                on_update=None,
                on_persist=self._persist_cache,
            )
        self._persist()
        self._persist_cache()

    def _persist_cache(self) -> None:
        from localagent.summarize.segment_cache import schedule_segment_cache_save

        schedule_segment_cache_save(self._cache_writer, self.result, provider=self.provider)

    def _segment_active(self) -> bool:
        return bool(self.result.segment_mode and self.result.reading_progress is not None)

    def _segment_nav_enabled(self) -> bool:
        return (
            self._segment_active()
            and not self.deep_segment_only
            and self.chat_scope != "book"
        )

    def _book_mode_active(self) -> bool:
        return self._segment_active() and self.chat_scope == "book"

    def _document_context(self, user_input: str = "") -> str:
        if self._book_mode_active():
            retrieval_block = ""
            if self.result.session_source_key:
                from localagent.summarize.session_index import (
                    format_retrieval_block,
                    retrieve_document_chunks,
                )

                hits = retrieve_document_chunks(
                    user_input or self.result.filename,
                    source_key=self.result.session_source_key,
                )
                retrieval_block = format_retrieval_block(
                    hits, source_key=self.result.session_source_key
                )
            return format_book_context(
                self.result,
                self.result.reading_progress,  # type: ignore[arg-type]
                retrieval_block=retrieval_block,
                provider=self.provider,
            )

        if self._segment_active():
            retrieval_block = ""
            if self.result.session_source_key and needs_cross_segment_rag(user_input):
                from localagent.summarize.session_index import (
                    format_retrieval_block,
                    retrieve_document_chunks,
                )

                hits = retrieve_document_chunks(
                    user_input or self.result.filename,
                    source_key=self.result.session_source_key,
                )
                retrieval_block = format_retrieval_block(
                    hits, source_key=self.result.session_source_key
                )
            return format_segment_context(
                self.result,
                self.result.reading_progress,  # type: ignore[arg-type]
                retrieval_block=retrieval_block,
            )

        retrieval_block = ""
        if self.result.uses_retrieval and self.result.session_source_key:
            from localagent.summarize.session_index import (
                format_retrieval_block,
                retrieve_document_chunks,
            )

            hits = retrieve_document_chunks(
                user_input or self.result.filename,
                source_key=self.result.session_source_key,
            )
            retrieval_block = format_retrieval_block(
                hits, source_key=self.result.session_source_key
            )
        return format_document_context(
            self.result,
            retrieval_block=retrieval_block,
        )

    def _persist(self) -> None:
        upsert_session(
            record_from_result(
                self.result,
                session_id=self.summarize_session_id,
                conversation_session_id=self.session_id,
            )
        )

    def run(self) -> int:
        if not use_prompt_toolkit_repl():
            from localagent.completion import install_repl_readline_completer

            install_repl_readline_completer()

        pages = (
            t("summarize.pages_suffix", n=self.result.page_count)
            if self.result.page_count
            else ""
        )
        print()
        print(
            t(
                "summarize.entered",
                filename=self.result.filename,
                pages=pages,
                session=self.summarize_session_id,
            )
        )
        print(t("summarize.enter_hint"))
        if self._book_mode_active():
            progress = self.result.reading_progress
            assert progress is not None
            print(
                t(
                    "summarize.book_mode_on",
                    done=progress.done_count(),
                    total=progress.total,
                )
            )
            if progress.done_count() < progress.total:
                print(t("summarize.book_partial_hint"))
        elif self._segment_active():
            progress = self.result.reading_progress
            assert progress is not None
            seg = progress.current
            print(
                t(
                    "summarize.segment_mode_on",
                    current=progress.current_index + 1,
                    total=progress.total,
                    heading=seg.heading,
                    chars=seg.char_count,
                )
            )
            print(t("summarize.segment_next_hint"))
        elif self.result.uses_retrieval:
            print(
                t(
                    "summarize.retrieval_mode",
                    index=self.result.session_source_key,
                )
            )
        if not self.result.kept:
            print(t("summarize.not_kept_repl"))
        else:
            print(t("summarize.kept_path", target=self.result.keep_target))
        prompt_label = "book> " if self._book_mode_active() else "sum> "
        interrupt_count = 0
        while True:
            try:
                prepare_for_input()
                line = read_repl_line(prompt_label).strip()
                interrupt_count = 0
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                interrupt_count += 1
                if interrupt_count >= 2:
                    print()
                    break
                print(t("summarize.cancel_once"))
                continue
            if not line:
                continue
            if self._handle_continue_phrase(line):
                continue
            if self._handle_local_command(line):
                continue
            if is_session_command(line):
                if self._handle_session_model(line):
                    continue
                ctx = SessionCommandContext(
                    session_id=self.session_id,
                    provider=self.provider,
                    history=self.history,
                )
                result = dispatch_session_line(line, ctx)
                if result.provider is not None:
                    self.provider = result.provider
                    self.model_choice = self.model_choice.with_provider(self.provider)
                    self.result.model_choice = self.model_choice
                    set_repl_provider(self.provider)
                if result.should_exit:
                    break
                continue
            self._handle_chat(line)

        self._cache_writer.flush(full_md=True)
        self._persist()
        print(t("summarize.ended"))
        if self._prefetch_worker is not None:
            self._prefetch_worker.stop()
        shutdown_cursor_sdk()
        return 0

    def _handle_continue_phrase(self, line: str) -> bool:
        if not self._segment_nav_enabled():
            return False
        text = line.strip()
        if text in {"继续", "继续读", "下一段", "下一段落"}:
            self._advance_segment()
            return True
        return False

    def _handle_local_command(self, line: str) -> bool:
        raw = line.strip()
        if not raw.startswith(("/", ":")):
            return False
        cmd_parts = raw[1:].strip().split(maxsplit=1)
        cmd = cmd_parts[0].lower()
        arg = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""
        if cmd in {"help", "h"}:
            _print_doc_help(
                kept=self.result.kept,
                segment_mode=self._segment_nav_enabled(),
                book_mode=self._book_mode_active(),
            )
            return True
        if cmd in {"summary", "s"}:
            print()
            print(self.result.markdown.rstrip())
            print()
            return True
        if cmd == "book" and self._segment_active():
            self._enter_book_mode()
            return True
        if cmd == "segment" and self._segment_active():
            if self.chat_scope == "book":
                self._enter_segment_mode()
                return True
            print()
            print(self.result.markdown.rstrip())
            print()
            return True
        if cmd in {"next", "n"} and self._segment_nav_enabled():
            self._advance_segment()
            return True
        if cmd in {"prev", "p"} and self._segment_nav_enabled():
            self._prev_segment()
            return True
        if cmd in {"goto", "g"} and self._segment_nav_enabled():
            if not arg:
                print(t("summarize.segment_goto_usage"))
                return True
            try:
                target = int(arg) - 1
            except ValueError:
                print(t("summarize.segment_goto_usage"))
                return True
            self._goto_segment(target)
            return True
        if cmd == "progress" and self._segment_nav_enabled():
            self._print_segment_progress()
            return True
        if cmd == "status":
            self._print_status()
            return True
        if cmd == "keep":
            self._do_keep()
            return True
        return False

    def _handle_session_model(self, line: str) -> bool:
        """Session-scoped /model for summarize (does not write YAML)."""
        raw = line.strip()
        if not raw.lower().startswith(("/model", ":model")):
            return False
        parts = raw[1:].strip().split(maxsplit=1)
        if parts[0].lower() != "model":
            return False
        router = get_model_router()
        effective = router.resolve_effective_provider(self.provider)
        if len(parts) < 2 or not parts[1].strip():
            current = self.model_choice.model or router.format_model_hint(effective) or ""
            print(t("summarize.model_session_current", model=current or t("session.model_unset")))
            print(t("summarize.model_session_hint"))
            return True
        selected = parts[1].strip()
        self.model_choice = self.model_choice.with_model(selected)
        self.result.model_choice = self.model_choice
        print(t("summarize.model_session_set", model=selected))
        return True

    def _reset_history_for_segment(self) -> None:
        progress = self.result.reading_progress
        assert progress is not None
        seg = progress.current
        self.history = [
            {
                "role": "user",
                "content": (
                    f"请总结文档第 {progress.current_index + 1}/{progress.total} 段"
                    f"（{seg.heading}）：{self.result.filename}"
                ),
            },
            {
                "role": "assistant",
                "content": progress.current_summary() or self.result.markdown,
            },
        ]

    def _print_segment_header(self) -> None:
        progress = self.result.reading_progress
        assert progress is not None
        seg = progress.current
        print()
        print(
            t(
                "summarize.segment_header",
                current=progress.current_index + 1,
                total=progress.total,
                heading=seg.heading,
                chars=seg.char_count,
            )
        )
        print()
        print((progress.current_summary() or self.result.markdown).rstrip())
        print()
        if progress.compressed_prior.strip():
            print(t("summarize.segment_compressed"))
        print(t("summarize.segment_next_hint"))

    def _advance_segment(self) -> None:
        progress = self.result.reading_progress
        assert progress is not None
        next_idx = progress.next_ready_index()
        if next_idx is None:
            if progress.current_index >= progress.total - 1:
                print(t("summarize.segment_at_end"))
            else:
                print(t("summarize.segment_not_ready"))
            return
        progress.select_segment(next_idx, provider=self.provider)
        self.result.markdown = progress.current_summary()
        self._reset_history_for_segment()
        self._persist()
        self._print_segment_header()

    def _prev_segment(self) -> None:
        progress = self.result.reading_progress
        assert progress is not None
        seg = prev_segment(progress, provider=self.provider)
        if seg is None:
            print(t("summarize.segment_at_start"))
            return
        self.result.markdown = progress.current_summary()
        self._reset_history_for_segment()
        self._persist()
        self._print_segment_header()

    def _goto_segment(self, index: int) -> None:
        progress = self.result.reading_progress
        assert progress is not None
        if index < 0 or index >= progress.total:
            print(t("summarize.segment_goto_usage"))
            return
        if not progress.summary_ready(index):
            print(t("summarize.segment_not_ready"))
            return
        if self.no_prefetch or not config.SUMMARIZE_SEGMENT_PREFETCH:
            seg = goto_segment(
                progress,
                index,
                filename=self.result.filename,
                model_choice=self.model_choice,
                use_llm=self._segment_use_llm,
                sync_if_missing=True,
                translate=getattr(self.result, "translate", None),
            )
            if seg is None:
                print(t("summarize.segment_not_ready"))
                return
        else:
            progress.select_segment(index, provider=self.provider)
        self.result.markdown = progress.current_summary()
        self._reset_history_for_segment()
        self._persist()
        self._print_segment_header()

    def _print_segment_progress(self) -> None:
        progress = self.result.reading_progress
        assert progress is not None
        seg = progress.current
        print(
            t(
                "summarize.segment_progress",
                current=progress.current_index + 1,
                total=progress.total,
                heading=seg.heading,
                cite=seg.cite_range,
            )
        )
        read_count = progress.current_index
        if read_count > 0:
            print(t("summarize.segment_read_count", n=read_count))
        remaining = progress.total - progress.current_index - 1
        if remaining > 0:
            print(t("summarize.segment_remaining", n=remaining))

    def _print_status(self) -> None:
        kept = (
            t("summarize.status_kept", target=self.result.keep_target)
            if self.result.kept and self.result.keep_target
            else t("summarize.status_not_kept")
        )
        print(t("summarize.status_file", path=self.result.path))
        print(t("summarize.status_kept_label", kept=kept))
        print(t("summarize.status_session", session=self.summarize_session_id))
        print(t("summarize.status_archive", session=self.session_id))
        print(t("summarize.status_chars", n=self.result.char_count))
        if self.result.page_count is not None:
            print(t("summarize.status_pages", n=self.result.page_count))
        if self._segment_active():
            scope = t("summarize.status_scope_book") if self._book_mode_active() else t(
                "summarize.status_scope_segment"
            )
            print(scope)
            self._print_segment_progress()

    def _enter_book_mode(self) -> None:
        progress = self.result.reading_progress
        assert progress is not None
        if progress.done_count() <= 0:
            print(t("summarize.book_no_summaries"))
            return
        self.chat_scope = "book"
        preview = build_book_context(
            progress,
            filename=self.result.filename,
            provider=self.provider,
        )
        self.history = [
            {
                "role": "user",
                "content": f"请基于全书各段摘要，围绕《{self.result.filename}》回答我的问题。",
            },
            {"role": "assistant", "content": preview or self.result.markdown},
        ]
        mark_book_chat_entered(self.summarize_session_id)
        self._persist()
        print()
        print(t("summarize.book_mode_entered"))
        if progress.done_count() < progress.total:
            print(t("summarize.book_partial_hint"))
        print()

    def _enter_segment_mode(self) -> None:
        progress = self.result.reading_progress
        assert progress is not None
        self.chat_scope = "segment"
        self._reset_history_for_segment()
        self._persist()
        print(t("summarize.segment_mode_entered"))
        self._print_segment_header()

    def _do_keep(self) -> None:
        if self.result.kept and self.result.keep_target is not None:
            print(t("summarize.kept", target=self.result.keep_target))
            return
        try:
            from localagent.ingest.add_file import add_file

            target, _ingest = add_file(self.result.path)
        except Exception as exc:
            print(t("summarize.keep_fail", exc=exc))
            return
        self.result.kept = True
        self.result.keep_target = target
        self._persist()
        print(t("summarize.kept", target=target))

    def _handle_chat(self, user_input: str) -> None:
        streamed = False
        user_appended = False
        response: str | None = None
        provider_source: str | None = None

        def on_token(chunk: str) -> None:
            nonlocal streamed
            if not streamed:
                activity.begin_streaming()
                streamed = True
            print(chunk, end="", flush=True)

        with ActivityIndicator("summarize", t("summarize.answering")) as activity:
            try:
                self.history.append({"role": "user", "content": user_input})
                user_appended = True

                def on_tool_approve(
                    tool_name: str,
                    arguments: dict,
                    risk: ToolRisk,
                ) -> bool:
                    return prompt_tool_approval(
                        tool_name,
                        arguments,
                        risk,
                        session_gate=self.session_approval,
                    )

                result = run_agent_turn(
                    user_input,
                    self.history[:-1],
                    provider=self.provider,
                    session_id=self.session_id,
                    on_status=activity.update,
                    on_token=on_token,
                    on_tool_approve=on_tool_approve,
                    session_approval=self.session_approval,
                    document_context=self._document_context(user_input),
                )
                response = result.response
                provider_source = get_model_router().format_last_source()
            except KeyboardInterrupt:
                print(t("summarize.request_cancelled"))
                if user_appended:
                    self.history.pop()
                activity.begin_streaming()
                return
            except Exception as exc:
                response = t("chat.error", exc=exc)

        if response is None:
            return
        if not str(response).strip():
            response = t("chat.empty_response")
        if streamed:
            print()
        else:
            print(response)
        if provider_source:
            print(f"[via {provider_source}]")

        router = get_model_router()
        if (
            router._ollama_slow
            and router.last_provider != "ollama"
            and not self._shown_fallback_hint
        ):
            print(t("summarize.ollama_failover", provider=router.last_provider))
            self._shown_fallback_hint = True

        append_message(self.session_id, "user", user_input)
        append_message(self.session_id, "assistant", response)
        self.history.append({"role": "assistant", "content": response})
        self._persist()


def should_enter_document_chat(*, no_chat: bool) -> bool:
    """Enter doc REPL unless --no-chat or non-interactive stdin."""
    if no_chat:
        return False
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def run_document_chat(
    result: SummarizeResult,
    *,
    provider: str = "auto",
    model_choice: SummarizeModelChoice | None = None,
    session_id: str | None = None,
    conversation_session_id: str | None = None,
    history: list[dict[str, str]] | None = None,
    summarize_session_id: str | None = None,
    no_prefetch: bool = False,
    use_llm: bool = True,
) -> int:
    return DocumentChatREPL(
        result,
        provider=provider,
        model_choice=model_choice,
        session_id=session_id,
        conversation_session_id=conversation_session_id,
        history=history,
        summarize_session_id=summarize_session_id,
        no_prefetch=no_prefetch,
        use_llm=use_llm,
    ).run()


def enter_summarize_interactive(
    result: SummarizeResult,
    *,
    provider: str = "auto",
    model_choice: SummarizeModelChoice | None = None,
    summarize_session_id: str | None = None,
    conversation_session_id: str | None = None,
    history: list[dict[str, str]] | None = None,
    no_ui: bool = False,
    no_prefetch: bool = False,
    use_llm: bool = True,
    book_chat_entered: bool = False,
) -> int:
    """Route segment-mode docs to TUI browser; others to classic sum> REPL."""
    if (
        result.segment_mode
        and result.reading_progress is not None
        and not no_ui
    ):
        progress = result.reading_progress
        if (
            progress.done_count() >= progress.total
            and progress.total > 0
            and not book_chat_entered
        ):
            from localagent.summarize.chat_bridge import run_book_chat

            return run_book_chat(
                result,
                provider=provider,
                summarize_session_id=summarize_session_id,
                conversation_session_id=conversation_session_id,
                history=history,
            )
        from localagent.summarize.browser import run_segment_browser

        return run_segment_browser(
            result,
            provider=provider,
            model_choice=model_choice,
            summarize_session_id=summarize_session_id,
            conversation_session_id=conversation_session_id,
            no_prefetch=no_prefetch,
            use_llm=use_llm,
            book_chat_entered=book_chat_entered,
        )
    return run_document_chat(
        result,
        provider=provider,
        model_choice=model_choice,
        summarize_session_id=summarize_session_id,
        conversation_session_id=conversation_session_id,
        history=history,
        no_prefetch=no_prefetch,
        use_llm=use_llm,
    )


def rebuild_result_from_disk(
    path: Path,
    *,
    summary_md: str,
    kept: bool = False,
    keep_target: str | None = None,
    page_count: int | None = None,
    char_count: int = 0,
    segment_mode: bool = False,
    current_segment_index: int = 0,
    segment_summaries: list[str] | None = None,
    compressed_prior: str = "",
    segment_statuses: list[str] | None = None,
    prefetch_enabled: bool = True,
    provider: str = "auto",
    model_choice: SummarizeModelChoice | None = None,
) -> SummarizeResult:
    """Reload annotated text from disk; reuse cached summary markdown."""
    from localagent.ingest.loader import load_file as load_doc
    from localagent.summarize.document import _annotate_for_cite
    from localagent.summarize.model_choice import SummarizeModelChoice
    from localagent.summarize.segment_reader import ReadingProgress
    from localagent.summarize.session_index import (
        index_document_session,
        summarize_source_key,
    )

    doc = load_doc(path)
    if doc is None:
        raise FileNotFoundError(t("summarize.read_fail", path=path))
    annotated = _annotate_for_cite(doc)
    pages = page_count
    if pages is None:
        raw_pages = doc.metadata.get("page_count")
        pages = raw_pages if isinstance(raw_pages, int) else None
    key = summarize_source_key(path)
    try:
        index_document_session(key, annotated, title=path.name)
    except Exception:
        key = ""

    reading_progress = None
    active_segment_mode = segment_mode
    markdown = summary_md or "## 总结（最多三句话）\n（无缓存速读卡）\n"
    if segment_mode:
        progress_data = {
            "current_index": current_segment_index,
            "segment_summaries": segment_summaries or [],
            "compressed_prior": compressed_prior,
            "segment_statuses": segment_statuses or [],
            "prefetch_enabled": prefetch_enabled,
        }
        reading_progress = ReadingProgress.from_session_dict(
            progress_data,
            annotated_text=annotated,
            filename=path.name,
            provider=provider,
        )
        saved_index = reading_progress.current_index
        from localagent.summarize.segment_cache import (
            apply_cache_to_progress,
            load_segment_cache,
        )
        from localagent.summarize.segment_reader import resolve_reading_budget

        choice = model_choice or SummarizeModelChoice.from_cli(provider=provider)
        budget = resolve_reading_budget(choice.provider)
        cached = load_segment_cache(
            path,
            total_segments=reading_progress.total,
            char_count=char_count or len(annotated),
            budget=budget,
            model_choice=choice,
        )
        if cached is not None:
            apply_cache_to_progress(reading_progress, cached)
            reading_progress.current_index = max(
                0,
                min(saved_index, max(reading_progress.total - 1, 0)),
            )
        if reading_progress.segment_summaries:
            idx = reading_progress.current_index
            if 0 <= idx < len(reading_progress.segment_summaries):
                cached = reading_progress.segment_summaries[idx]
                if cached.strip():
                    markdown = cached
        reading_progress.compressed_prior = compressed_prior

    choice = model_choice or SummarizeModelChoice.from_cli(provider=provider)
    return SummarizeResult(
        markdown=markdown,
        path=path.resolve(),
        filename=path.name,
        char_count=char_count or len(annotated),
        page_count=pages,
        kept=kept,
        keep_target=Path(keep_target) if keep_target else None,
        used_llm=True,
        annotated_text=annotated,
        session_source_key=key,
        segment_mode=active_segment_mode,
        reading_progress=reading_progress,
        model_choice=choice,
    )
