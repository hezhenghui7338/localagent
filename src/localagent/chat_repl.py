"""Chat REPL with :deepsearch, :provider, and conversation persistence."""

from __future__ import annotations

try:
    import readline  # noqa: F401
except ImportError:
    pass

from localagent import config
from localagent.agent.runtime import run_agent_turn
from localagent.memory.core_profile import default_core_profile
from localagent.memory.exit_extract import schedule_session_memory_extract
from localagent.models.router import get_model_router
from localagent.persist.conversations import append_message, new_session_id
from localagent.tools import deep_search
from localagent.ui.console import ActivityIndicator, prepare_for_input


class ChatREPL:
    def __init__(self, *, session_id: str | None = None, provider: str = "auto") -> None:
        self.session_id = session_id or new_session_id()
        self.history: list[dict[str, str]] = []
        self.provider = config.normalize_provider_choice(provider)
        default_core_profile()

    def run(self) -> int:
        router = get_model_router()
        provider_hint = router.format_provider_hint(self.provider)
        model_hint = ""
        if router.is_ollama_available():
            model_hint = f"  model={router.resolve_ollama_model()}"
        speed_hint = ""
        if self.provider in ("auto", "ollama") and router.provider_status()["openrouter"]:
            speed_hint = "\n  提示: Ollama 本地模型较慢时可 :provider openrouter 加速"
        print(
            f"[chat] session={self.session_id}  provider={provider_hint}{model_hint}\n"
            "  输入 :q 退出, :provider 切换路径, :deepsearch <主题> 深度研究\n"
            "  Ctrl+C 取消当前输入/请求，连按两次退出"
            f"{speed_hint}"
        )
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
            if line in (":q", ":quit", ":exit"):
                break
            if line.startswith(":provider") or line.startswith(":p "):
                self._handle_provider(line)
                continue
            if line == ":p":
                self._handle_provider(":provider")
                continue
            if line.startswith(":deepsearch"):
                topic = line[len(":deepsearch"):].strip()
                if not topic:
                    print("用法: :deepsearch <主题>")
                    continue
                self._handle_deepsearch(topic)
                continue

            self._handle_chat(line)

        self._on_exit()
        return 0

    def _handle_chat(self, user_input: str) -> None:
        self.history.append({"role": "user", "content": user_input})
        streamed = False

        def on_token(chunk: str) -> None:
            nonlocal streamed
            if not streamed:
                activity.begin_streaming()
                streamed = True
            print(chunk, end="", flush=True)

        provider_source: str | None = None
        with ActivityIndicator("chat", "思考中…") as activity:
            try:
                result = run_agent_turn(
                    user_input,
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
                self.history.pop()
                return
            except Exception as exc:
                response = f"[错误] {exc}"

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

    def _handle_provider(self, line: str) -> None:
        router = get_model_router()
        parts = line.split(maxsplit=1)
        if len(parts) < 2:
            status = router.provider_status()
            labels = {
                "ollama": f"ollama      {'✓' if status['ollama'] else '✗'}  {config.OLLAMA_MODEL}",
                "openrouter": (
                    f"openrouter  {'✓' if status['openrouter'] else '✗'}  {config.OPENROUTER_MODEL}"
                ),
                "cursor": f"cursor     {'✓' if status['cursor'] else '✗'}  {config.CURSOR_MODEL}",
            }
            print(f"当前路径: {router.format_provider_hint(self.provider)}")
            for name in config.MODEL_PROVIDER_PRIORITY:
                print(f"  {labels[name]}")
            print("用法: :provider auto|ollama|openrouter|cursor")
            return

        try:
            self.provider = config.normalize_provider_choice(parts[1])
        except ValueError as exc:
            print(f"[provider] {exc}")
            return

        print(f"[provider] 已切换为 {router.format_provider_hint(self.provider)}")

    def _handle_deepsearch(self, topic: str) -> None:
        append_message(self.session_id, "user", f":deepsearch {topic}")
        with ActivityIndicator("deepsearch", f"研究中: {topic}") as activity:
            try:
                report = deep_search(topic, on_status=activity.update)
            except KeyboardInterrupt:
                print("\n[chat] deepsearch 已取消")
                return
            except Exception as exc:
                report = f"[deepsearch 失败] {exc}"
        print(report)
        append_message(self.session_id, "assistant", report, tool="deepsearch")
        self.history.append({"role": "user", "content": f":deepsearch {topic}"})
        self.history.append({"role": "assistant", "content": report})

    def _on_exit(self) -> None:
        schedule_session_memory_extract(self.session_id)


def run_chat(*, session_id: str | None = None, provider: str = "auto") -> int:
    return ChatREPL(session_id=session_id, provider=provider).run()
