"""Interactive aware> REPL grounded on local sensing episodes."""

from __future__ import annotations

import sys

from localagent import config
from localagent.agent.runtime import run_agent_turn
from localagent.aware.digest import format_view
from localagent.aware.episode import retrieve_aware_context
from localagent.models.router import get_model_router, shutdown_cursor_sdk
from localagent.persist.conversations import append_message, new_session_id
from localagent.session_commands import (
    SessionCommandContext,
    dispatch_session_line,
    is_session_command,
    set_repl_provider,
)
from localagent.tools.approval import SessionApprovalGate, ToolRisk, prompt_tool_approval
from localagent.ui.console import (
    ActivityIndicator,
    prepare_for_input,
    read_repl_line,
    use_prompt_toolkit_repl,
)


def should_enter_aware_chat(*, no_chat: bool) -> bool:
    if no_chat:
        return False
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _print_help() -> None:
    print("当前是「感知对话」：围绕本机 Aware 行为深入聊；闲聊请另开 la chat。")
    print("命令：")
    print("  /overview, /o   重新显示智能概览")
    print("  /detail         显示分源明细")
    print("  /context, /c    显示当前注入的感知上下文")
    print("  /status         授权 / suggestion / session")
    print("  /help, /h       显示本帮助")
    print("  /provider, /p   切换模型路径")
    print("  /q, /quit, /exit 结束感知对话")
    print("直接输入问题即可，例如：我今天下午改了哪些文件？")


class AwareChatREPL:
    def __init__(
        self,
        *,
        mode: str = "now",
        since: str | None = None,
        source: str | None = None,
        provider: str = "auto",
        session_id: str | None = None,
    ) -> None:
        self.mode = mode
        self.since = since
        self.source = source
        self.provider = config.normalize_provider_choice(provider)
        self.session_id = session_id or new_session_id()
        self.session_approval = SessionApprovalGate()
        self.history: list[dict[str, str]] = []
        self._shown_fallback_hint = False
        set_repl_provider(self.provider)

    def _overview_text(self, *, detail: bool = False) -> str:
        return format_view(
            mode=self.mode,  # type: ignore[arg-type]
            since=self.since,
            source=self.source,
            detail=detail,
            use_llm=False,
        )

    def _aware_context(self, user_input: str = "") -> str:
        hours = 24.0
        if self.since:
            try:
                from localagent.aware.timewin import since_to_datetime
                from datetime import datetime, timezone

                start = since_to_datetime(self.since)
                hours = max(
                    1.0,
                    (datetime.now(timezone.utc) - start).total_seconds() / 3600.0,
                )
            except ValueError:
                hours = 24.0
        return retrieve_aware_context(user_input, since_hours=hours)

    def run(self) -> int:
        if not use_prompt_toolkit_repl():
            from localagent.completion import install_repl_readline_completer

            install_repl_readline_completer()

        print()
        print(f"[aware] 已进入感知对话（session={self.session_id}）")
        print("[aware] 可追问本机行为；/help 查看命令，/exit 结束。")
        interrupt_count = 0
        while True:
            try:
                prepare_for_input()
                line = read_repl_line("aware> ").strip()
                interrupt_count = 0
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                interrupt_count += 1
                if interrupt_count >= 2:
                    print()
                    break
                print("\n[aware] 已取消；再按一次 Ctrl+C 退出，或继续提问")
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

        print("[aware] 感知对话结束（可再运行 la aware 继续）")
        shutdown_cursor_sdk()
        return 0

    def _handle_local_command(self, line: str) -> bool:
        raw = line.strip()
        if not raw.startswith(("/", ":")):
            return False
        parts = raw[1:].strip().split(maxsplit=1)
        cmd = (parts[0] if parts else "").lower()
        if cmd in {"help", "h"}:
            _print_help()
            return True
        if cmd in {"overview", "o"}:
            print()
            print(self._overview_text(detail=False).rstrip())
            print()
            return True
        if cmd == "detail":
            print()
            print(self._overview_text(detail=True).rstrip())
            print()
            return True
        if cmd in {"context", "c"}:
            print()
            print(self._aware_context().rstrip())
            print()
            return True
        if cmd == "status":
            from localagent.aware.profile import load_profile
            from localagent.aware.store import events_count_today
            from localagent.aware.suggestion import suggestion_count

            profile = load_profile()
            print(f"[aware] session: {self.session_id}")
            print(f"[aware] 上次 tick · {profile.last_tick_at or '尚未运行'}")
            print(
                f"[aware] 今日事件 {events_count_today()} · "
                f"suggestion {suggestion_count()}"
            )
            return True
        return False

    def _handle_chat(self, user_input: str) -> None:
        streamed = False
        user_appended = False
        response: str | None = None
        provider_source: str | None = None
        ctx = self._aware_context(user_input)

        def on_token(chunk: str) -> None:
            nonlocal streamed
            if not streamed:
                activity.begin_streaming()
                streamed = True
            print(chunk, end="", flush=True)

        with ActivityIndicator("aware", "围绕感知上下文回答…") as activity:
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
                    document_context=ctx,
                )
                response = result.response
                provider_source = get_model_router().format_last_source()
            except KeyboardInterrupt:
                print("\n[aware] 请求已取消")
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
            print(f"[aware] 本地 Ollama 响应过慢，已自动切换 {router.last_provider}")
            self._shown_fallback_hint = True

        append_message(self.session_id, "user", user_input)
        append_message(self.session_id, "assistant", response)
        self.history.append({"role": "assistant", "content": response})


def run_aware_chat(
    *,
    mode: str = "now",
    since: str | None = None,
    source: str | None = None,
    provider: str = "auto",
    session_id: str | None = None,
) -> int:
    return AwareChatREPL(
        mode=mode,
        since=since,
        source=source,
        provider=provider,
        session_id=session_id,
    ).run()
