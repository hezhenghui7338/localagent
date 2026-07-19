"""Chat REPL with slash commands (/…), conversation persistence, and agent turns."""

from __future__ import annotations

from localagent import config
from localagent.i18n import t
from localagent.agent.runtime import run_agent_turn
from localagent.memory.core_profile import default_core_profile
from localagent.memory.exit_extract import schedule_session_memory_extract
from localagent.memory.backend import shutdown_memory_backend
from localagent.models.router import get_model_router, shutdown_cursor_sdk
from localagent.persist.conversations import append_message, new_session_id
from localagent.session_commands import (
    SessionCommandContext,
    dispatch_session_line,
    is_session_command,
    set_repl_provider,
)
from localagent.tools.approval import SessionApprovalGate, ToolRisk, prompt_tool_approval
from localagent.ui.banner import print_welcome
from localagent.ui.console import (
    ActivityIndicator,
    prepare_for_input,
    read_repl_line,
    use_prompt_toolkit_repl,
)


class ChatREPL:
    def __init__(self, *, session_id: str | None = None, provider: str = "auto") -> None:
        self.session_id = session_id or new_session_id()
        self.history: list[dict[str, str]] = []
        self.provider = config.normalize_provider_choice(provider)
        self.session_approval = SessionApprovalGate()
        set_repl_provider(self.provider)
        default_core_profile()

    def run(self) -> int:
        import logging

        # readline Tab only for non-TTY / input() fallback; TTY uses prompt_toolkit.
        if not use_prompt_toolkit_repl():
            from localagent.completion import install_repl_readline_completer

            install_repl_readline_completer()
        print_welcome(provider=self.provider, session_id=self.session_id)
        try:
            from localagent.news.notify import maybe_print_news_ready

            maybe_print_news_ready()
        except Exception:
            pass
        logging.getLogger(__name__).info(
            "chat session start session=%s provider=%s",
            self.session_id,
            self.provider,
        )
        router = get_model_router()
        status = router.provider_status()
        if self.provider == "openai" and not status.get("openai"):
            print(t("chat.warn_openai_key"))
        cloud_ready = any(
            name != "ollama" and name != "cursor" and status.get(name)
            for name in config.MODEL_PROVIDER_PRIORITY
        )
        if self.provider in ("auto", "ollama") and cloud_ready:
            alt = next(
                (n for n in config.MODEL_PROVIDER_PRIORITY if n not in ("ollama", "cursor") and status.get(n)),
                "cloud",
            )
            print(t("chat.hint_ollama_slow", alt=alt))
        self._shown_fallback_hint = False
        interrupt_count = 0
        while True:
            try:
                prepare_for_input()
                line = read_repl_line("> ").strip()
                interrupt_count = 0
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                interrupt_count += 1
                if interrupt_count >= 2:
                    print()
                    break
                print(t("chat.cancel_once"))
                continue
            if not line:
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

        self._on_exit()
        return 0

    def _handle_chat(self, user_input: str) -> None:
        streamed = False
        user_appended = False
        provider_source: str | None = None
        response: str | None = None

        def on_token(chunk: str) -> None:
            nonlocal streamed
            if not streamed:
                activity.begin_streaming()
                streamed = True
            print(chunk, end="", flush=True)

        with ActivityIndicator("chat", t("chat.processing")) as activity:
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
                )
                response = result.response
                provider_source = get_model_router().format_last_source()
            except KeyboardInterrupt:
                print(t("chat.request_cancelled"))
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
            print(t("chat.ollama_failover", provider=router.last_provider))
            self._shown_fallback_hint = True
        append_message(self.session_id, "user", user_input)
        append_message(self.session_id, "assistant", response)
        self.history.append({"role": "assistant", "content": response})

    def _on_exit(self) -> None:
        schedule_session_memory_extract(self.session_id)
        shutdown_memory_backend()
        shutdown_cursor_sdk()


def run_chat(*, session_id: str | None = None, provider: str = "auto") -> int:
    return ChatREPL(session_id=session_id, provider=provider).run()
