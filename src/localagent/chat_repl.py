"""Chat REPL with slash commands (/…), conversation persistence, and agent turns."""

from __future__ import annotations

from localagent import config
from localagent.agent.intent_clarification import (
    PendingClarification,
    assess_intent,
    format_clarification_response,
    merge_clarified_intent,
)
from localagent.agent.runtime import run_agent_turn
from localagent.completion import install_repl_readline_completer
from localagent.memory.core_profile import default_core_profile
from localagent.memory.exit_extract import schedule_session_memory_extract
from localagent.models.router import get_model_router, shutdown_cursor_sdk
from localagent.persist.conversations import append_message, new_session_id
from localagent.session_commands import (
    SessionCommandContext,
    dispatch_session_line,
    is_session_command,
    set_repl_provider,
)
from localagent.ui.banner import print_welcome
from localagent.ui.console import ActivityIndicator, prepare_for_input


class ChatREPL:
    def __init__(self, *, session_id: str | None = None, provider: str = "auto") -> None:
        self.session_id = session_id or new_session_id()
        self.history: list[dict[str, str]] = []
        self.provider = config.normalize_provider_choice(provider)
        set_repl_provider(self.provider)
        self.pending_clarification: PendingClarification | None = None
        default_core_profile()

    def run(self) -> int:
        install_repl_readline_completer()
        print_welcome(provider=self.provider, session_id=self.session_id)
        router = get_model_router()
        status = router.provider_status()
        if self.provider == "minimax" and not status.get("minimax"):
            print(
                "[chat] 警告: minimax 未配置 api_key。"
                " 请 LA config set-key minimax <key> 或在 LA 会话中 /config set-key minimax <key>。"
            )
        cloud_ready = any(
            name != "ollama" and name != "cursor" and status.get(name)
            for name in config.MODEL_PROVIDER_PRIORITY
        )
        if self.provider in ("auto", "ollama") and cloud_ready:
            alt = next(
                (n for n in config.MODEL_PROVIDER_PRIORITY if n not in ("ollama", "cursor") and status.get(n)),
                "cloud",
            )
            print(f"[chat] 提示: Ollama 本地模型较慢时可 /provider {alt} 加速")
        self._shown_fallback_hint = False
        interrupt_count = 0
        while True:
            try:
                prepare_for_input()
                line = input("> ").strip()
                interrupt_count = 0
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                interrupt_count += 1
                if interrupt_count >= 2:
                    print()
                    break
                print("\n[chat] 已取消；再按一次 Ctrl+C 退出，或继续输入")
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

        # Start status immediately so intent assessment never looks like a hang.
        with ActivityIndicator("chat", "处理中…") as activity:
            try:
                agent_input = user_input
                if self.pending_clarification is not None:
                    agent_input = merge_clarified_intent(
                        self.pending_clarification.original_message,
                        user_input,
                    )
                    self.pending_clarification = None
                elif config.INTENT_CLARIFY_ENABLED:
                    assessment = assess_intent(
                        user_input,
                        self.history,
                        provider=self.provider,
                        session_id=self.session_id,
                        on_status=activity.update,
                    )
                    if assessment.needs_clarification:
                        self.history.append({"role": "user", "content": user_input})
                        response = format_clarification_response(assessment)
                        self.pending_clarification = PendingClarification(
                            original_message=user_input
                        )
                        append_message(self.session_id, "user", user_input)
                        append_message(self.session_id, "assistant", response)
                        self.history.append({"role": "assistant", "content": response})
                        activity.begin_streaming()
                        print(response)
                        return

                self.history.append({"role": "user", "content": user_input})
                user_appended = True
                result = run_agent_turn(
                    agent_input,
                    self.history[:-1],
                    provider=self.provider,
                    session_id=self.session_id,
                    on_status=activity.update,
                    on_token=on_token,
                )
                response = result.response
                provider_source = get_model_router().format_last_source()
            except KeyboardInterrupt:
                print("\n[chat] 请求已取消")
                if user_appended:
                    self.history.pop()
                activity.begin_streaming()
                return
            except Exception as exc:
                response = f"[错误] {exc}"

        if response is None:
            return
        if not str(response).strip():
            response = "[错误] 模型返回了空内容，请重试。"
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
            print(f"[chat] 本地 Ollama 响应过慢，已自动切换 {router.last_provider}")
            self._shown_fallback_hint = True
        append_message(self.session_id, "user", user_input)
        append_message(self.session_id, "assistant", response)
        self.history.append({"role": "assistant", "content": response})

    def _on_exit(self) -> None:
        schedule_session_memory_extract(self.session_id)
        shutdown_cursor_sdk()


def run_chat(*, session_id: str | None = None, provider: str = "auto") -> int:
    return ChatREPL(session_id=session_id, provider=provider).run()
