"""Interactive follow-up chat scoped to a summarized document (sum> REPL)."""

from __future__ import annotations

import sys
from pathlib import Path

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
from localagent.summarize.sessions import (
    record_from_result,
    upsert_session,
)
from localagent.tools.approval import SessionApprovalGate, ToolRisk, prompt_tool_approval
from localagent.ui.console import (
    ActivityIndicator,
    prepare_for_input,
    read_repl_line,
    use_prompt_toolkit_repl,
)


def _print_doc_help(*, kept: bool) -> None:
    print(t("summarize.help_intro"))
    print(t("summarize.help_commands"))
    print(t("summarize.help_summary"))
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
        session_id: str | None = None,
        conversation_session_id: str | None = None,
        history: list[dict[str, str]] | None = None,
        summarize_session_id: str | None = None,
    ) -> None:
        self.result = result
        self.summarize_session_id = summarize_session_id or session_id or new_session_id()
        self.session_id = conversation_session_id or self.summarize_session_id
        self.provider = config.normalize_provider_choice(provider)
        self.session_approval = SessionApprovalGate()
        set_repl_provider(self.provider)
        if history is not None:
            self.history = list(history)
        else:
            self.history = [
                {
                    "role": "user",
                    "content": f"请总结这份文档并给出结构化要点：{result.filename}",
                },
                {"role": "assistant", "content": result.markdown},
            ]
        self._shown_fallback_hint = False
        self._persist()

    def _document_context(self, user_input: str = "") -> str:
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
        if self.result.uses_retrieval:
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
        interrupt_count = 0
        while True:
            try:
                prepare_for_input()
                line = read_repl_line("sum> ").strip()
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
            if self._handle_local_command(line):
                continue
            if is_session_command(line):
                ctx = SessionCommandContext(
                    session_id=self.session_id,
                    provider=self.provider,
                    history=self.history,
                )
                result = dispatch_session_line(line, ctx)
                if result.provider is not None:
                    self.provider = result.provider
                    set_repl_provider(self.provider)
                if result.should_exit:
                    break
                continue
            self._handle_chat(line)

        self._persist()
        print(t("summarize.ended"))
        shutdown_cursor_sdk()
        return 0

    def _handle_local_command(self, line: str) -> bool:
        raw = line.strip()
        if not raw.startswith(("/", ":")):
            return False
        cmd = raw[1:].strip().split(maxsplit=1)[0].lower()
        if cmd in {"help", "h"}:
            _print_doc_help(kept=self.result.kept)
            return True
        if cmd in {"summary", "s"}:
            print()
            print(self.result.markdown.rstrip())
            print()
            return True
        if cmd == "status":
            self._print_status()
            return True
        if cmd == "keep":
            self._do_keep()
            return True
        return False

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
    session_id: str | None = None,
    conversation_session_id: str | None = None,
    history: list[dict[str, str]] | None = None,
    summarize_session_id: str | None = None,
) -> int:
    return DocumentChatREPL(
        result,
        provider=provider,
        session_id=session_id,
        conversation_session_id=conversation_session_id,
        history=history,
        summarize_session_id=summarize_session_id,
    ).run()


def rebuild_result_from_disk(
    path: Path,
    *,
    summary_md: str,
    kept: bool = False,
    keep_target: str | None = None,
    page_count: int | None = None,
    char_count: int = 0,
) -> SummarizeResult:
    """Reload annotated text from disk; reuse cached summary markdown."""
    from localagent.ingest.loader import load_file as load_doc
    from localagent.summarize.document import _annotate_for_cite
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
    return SummarizeResult(
        markdown=summary_md or "## 总结（最多三句话）\n（无缓存速读卡）\n",
        path=path.resolve(),
        filename=path.name,
        char_count=char_count or len(annotated),
        page_count=pages,
        kept=kept,
        keep_target=Path(keep_target) if keep_target else None,
        used_llm=True,
        annotated_text=annotated,
        session_source_key=key,
    )
