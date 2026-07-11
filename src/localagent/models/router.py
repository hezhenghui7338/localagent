"""Model service router: Ollama → OpenRouter → Cursor fallback."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from localagent import config
from localagent.audit.usage import estimate_tokens, log_usage

logger = logging.getLogger(__name__)

_COMPLETION_CAPS = frozenset({"completion", "tools", "vision"})


@dataclass
class ChatMessage:
    role: str
    content: str


def _model_capabilities(model: dict[str, Any]) -> set[str]:
    caps = model.get("capabilities")
    if isinstance(caps, list):
        return {str(c) for c in caps}
    details = model.get("details") or {}
    detail_caps = details.get("capabilities")
    if isinstance(detail_caps, list):
        return {str(c) for c in detail_caps}
    return set()


def _format_messages_for_cursor(messages: list[ChatMessage]) -> str:
    """Render chat history into a single prompt for Cursor Agent."""
    role_labels = {"system": "System", "user": "User", "assistant": "Assistant"}
    parts: list[str] = [
        "You are answering in a chat REPL. Reply directly to the latest user message.",
        "Do not edit files or run tools unless explicitly asked.",
    ]
    for message in messages:
        label = role_labels.get(message.role, message.role.title())
        parts.append(f"{label}:\n{message.content.strip()}")
    parts.append("Assistant:")
    return "\n\n".join(parts)


def _is_completion_model(model: dict[str, Any]) -> bool:
    caps = _model_capabilities(model)
    if not caps:
        return True
    if caps == {"embedding"}:
        return False
    return bool(caps & _COMPLETION_CAPS) or "embedding" not in caps


class ModelRouter:
    """Unified LLM access with three-tier fallback."""

    def __init__(self) -> None:
        self._ollama_available: bool | None = None
        self._resolved_ollama_model: str | None = None
        self._ollama_slow: bool = False
        self.last_provider: str | None = None
        self.last_model: str | None = None

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        prefer: str | None = None,
        on_token: Callable[[str], None] | None = None,
        usage_command: str = "chat",
        session_id: str | None = None,
    ) -> str:
        providers = self._provider_order(prefer)
        auto_mode = prefer is None or prefer == config.DEFAULT_MODEL_PROVIDER
        if auto_mode and self._ollama_slow:
            providers = [p for p in providers if p != "ollama"]
        last_error: Exception | None = None
        for provider in providers:
            try:
                if provider == "ollama":
                    timeout = config.OLLAMA_CHAT_TIMEOUT if auto_mode else config.OLLAMA_TIMEOUT
                    text, usage = self._chat_ollama(
                        messages,
                        temperature=temperature,
                        on_token=on_token if config.OLLAMA_CHAT_STREAM else None,
                        timeout=timeout,
                    )
                    model = self.resolve_ollama_model()
                    self.last_provider = "ollama"
                    self.last_model = model
                    self._record_usage(
                        "ollama",
                        model,
                        usage=usage,
                        messages=messages,
                        response=text,
                        command=usage_command,
                        session_id=session_id,
                    )
                    return text
                if provider == "openrouter":
                    text, usage = self._chat_openrouter(messages, temperature=temperature)
                    self.last_provider = "openrouter"
                    self.last_model = config.OPENROUTER_MODEL
                    self._record_usage(
                        "openrouter",
                        config.OPENROUTER_MODEL,
                        usage=usage,
                        messages=messages,
                        response=text,
                        command=usage_command,
                        session_id=session_id,
                    )
                    return text
                if provider == "cursor":
                    text = self._chat_cursor(messages, temperature=temperature)
                    self.last_provider = "cursor"
                    self.last_model = config.CURSOR_MODEL
                    log_usage(
                        "cursor",
                        config.CURSOR_MODEL,
                        command=usage_command,
                        prompt_tokens=sum(estimate_tokens(m.content) for m in messages),
                        completion_tokens=estimate_tokens(text),
                        session_id=session_id,
                        per_call=True,
                    )
                    return text
            except (httpx.TimeoutException, TimeoutError) as exc:
                if provider == "ollama" and auto_mode:
                    logger.warning("ollama chat timed out after %.0fs, falling back", timeout)
                    self._ollama_slow = True
                    last_error = exc
                    continue
                raise
            except Exception as exc:
                logger.warning("provider %s failed: %s", provider, exc)
                last_error = exc
        hint = self._failure_hint()
        raise RuntimeError(f"all model providers failed: {last_error}{hint}")

    def is_ollama_available(self) -> bool:
        if self._ollama_available is not None:
            return self._ollama_available
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(f"{config.OLLAMA_BASE_URL}/api/tags")
                self._ollama_available = resp.status_code == 200
        except Exception:
            self._ollama_available = False
        return self._ollama_available

    def resolve_ollama_model(self) -> str:
        """Pick an installed Ollama model, falling back from configured name."""
        if self._resolved_ollama_model:
            return self._resolved_ollama_model

        configured = config.OLLAMA_MODEL
        try:
            models = self._list_ollama_models()
            names = [m.get("name", "") for m in models if m.get("name")]

            if configured in names:
                self._resolved_ollama_model = configured
                return configured

            configured_tag = configured.split(":", 1)[-1] if ":" in configured else ""
            completion_models = [m for m in models if _is_completion_model(m)]
            for model in completion_models:
                name = model.get("name", "")
                if configured_tag and name.endswith(f":{configured_tag}"):
                    logger.info("ollama model %s not found, using %s", configured, name)
                    self._resolved_ollama_model = name
                    return name

            if completion_models:
                name = completion_models[0].get("name", "")
                logger.info("ollama model %s not found, using %s", configured, name)
                self._resolved_ollama_model = name
                return name
        except Exception as exc:
            logger.warning("could not resolve ollama model: %s", exc)

        self._resolved_ollama_model = configured
        return configured

    def list_completion_models(self) -> list[str]:
        try:
            return [
                m.get("name", "")
                for m in self._list_ollama_models()
                if _is_completion_model(m) and m.get("name")
            ]
        except Exception:
            return []

    def _failure_hint(self) -> str:
        models = self.list_completion_models()
        if not models:
            return (
                "\n提示: 未检测到可用的 Ollama 对话模型。请运行 `ollama pull qwen3.5:4b`"
                " 或在 .env 中设置 OLLAMA_MODEL。"
            )
        return (
            f"\n提示: 已检测到 Ollama 模型 {', '.join(models)}，"
            f"当前配置为 {config.OLLAMA_MODEL}。"
        )

    def _list_ollama_models(self) -> list[dict[str, Any]]:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{config.OLLAMA_BASE_URL}/api/tags")
            resp.raise_for_status()
            return resp.json().get("models", [])

    def provider_status(self) -> dict[str, bool]:
        return {
            "ollama": self.is_ollama_available(),
            "openrouter": bool(config.OPENROUTER_API_KEY),
            "cursor": bool(config.CURSOR_API_KEY),
        }

    def format_provider_hint(self, choice: str = config.DEFAULT_MODEL_PROVIDER) -> str:
        priority = config.MODEL_PROVIDER_PRIORITY
        if choice == config.DEFAULT_MODEL_PROVIDER:
            return f"auto({'→'.join(priority)})"
        rest = [p for p in priority if p != choice]
        return f"{choice}({'→'.join(rest)})"

    def format_last_source(self) -> str | None:
        """Return provider/model used for the most recent successful chat call."""
        if not self.last_provider:
            return None
        if self.last_model:
            return f"{self.last_provider}/{self.last_model}"
        return self.last_provider

    def _record_usage(
        self,
        provider: str,
        model: str,
        *,
        usage: dict[str, int] | None,
        messages: list[ChatMessage],
        response: str,
        command: str,
        session_id: str | None,
    ) -> None:
        prompt_tokens = usage.get("prompt_tokens", 0) if usage else 0
        completion_tokens = usage.get("completion_tokens", 0) if usage else 0
        if not prompt_tokens:
            prompt_tokens = sum(estimate_tokens(m.content) for m in messages)
        if not completion_tokens:
            completion_tokens = estimate_tokens(response)
        try:
            log_usage(
                provider,
                model,
                command=command,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                session_id=session_id,
            )
        except Exception as exc:
            logger.warning("usage log failed: %s", exc)

    def _provider_order(self, prefer: str | None) -> list[str]:
        priority = config.MODEL_PROVIDER_PRIORITY
        if prefer and prefer != config.DEFAULT_MODEL_PROVIDER:
            rest = [p for p in priority if p != prefer]
            return [prefer, *rest]
        return list(priority)

    def _ollama_chat_payload(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        stream: bool,
    ) -> dict[str, Any]:
        model = self.resolve_ollama_model()
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": stream,
            "keep_alive": config.OLLAMA_KEEP_ALIVE,
            "options": {
                "temperature": temperature,
                "num_predict": config.OLLAMA_NUM_PREDICT,
                "num_ctx": config.OLLAMA_NUM_CTX,
            },
        }
        if not config.OLLAMA_THINK:
            payload["think"] = False
        return payload

    def _chat_ollama(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float,
        on_token: Callable[[str], None] | None = None,
        timeout: float | None = None,
    ) -> tuple[str, dict[str, int]]:
        model = self.resolve_ollama_model()
        stream = on_token is not None
        payload = self._ollama_chat_payload(messages, temperature=temperature, stream=stream)
        url = f"{config.OLLAMA_BASE_URL}/api/chat"
        request_timeout = timeout if timeout is not None else config.OLLAMA_TIMEOUT
        usage: dict[str, int] = {}

        with httpx.Client(timeout=request_timeout) as client:
            if stream:
                parts: list[str] = []
                started = time.monotonic()
                with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code == 404:
                        self._raise_ollama_model_error(resp, model)
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not parts and time.monotonic() - started > request_timeout:
                            raise TimeoutError(f"ollama first token timeout ({request_timeout:.0f}s)")
                        if not line:
                            continue
                        data = json.loads(line)
                        chunk = data.get("message", {}).get("content", "")
                        if chunk:
                            parts.append(chunk)
                            on_token(chunk)
                        if data.get("done"):
                            usage = {
                                "prompt_tokens": int(data.get("prompt_eval_count", 0)),
                                "completion_tokens": int(data.get("eval_count", 0)),
                            }
                            break
                return "".join(parts), usage

            resp = client.post(url, json=payload)
            self._raise_ollama_model_error(resp, model)
            resp.raise_for_status()
            data = resp.json()
        usage = {
            "prompt_tokens": int(data.get("prompt_eval_count", 0)),
            "completion_tokens": int(data.get("eval_count", 0)),
        }
        return data["message"]["content"], usage

    def _raise_ollama_model_error(self, resp: httpx.Response, model: str) -> None:
        if resp.status_code != 404:
            return
        try:
            data = resp.json()
        except Exception:
            try:
                data = json.loads(resp.read().decode())
            except Exception:
                return
        err = data.get("error", "")
        if "not found" in err.lower():
            self._resolved_ollama_model = None
            raise RuntimeError(
                f"ollama model '{model}' not found; available: {', '.join(self.list_completion_models())}"
            )

    def _chat_openrouter(self, messages: list[ChatMessage], *, temperature: float) -> tuple[str, dict[str, int]]:
        if not config.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        headers = {
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/localagent",
            "X-Title": "LocalAgent",
        }
        payload = {
            "model": config.OPENROUTER_MODEL,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{config.OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )
            if resp.status_code == 404:
                detail = resp.text[:200]
                try:
                    detail = resp.json().get("error", {}).get("message", detail)
                except Exception:
                    pass
                raise RuntimeError(
                    f"openrouter model {config.OPENROUTER_MODEL!r} unavailable: {detail}"
                )
            resp.raise_for_status()
            data = resp.json()
        usage_raw = data.get("usage") or {}
        usage = {
            "prompt_tokens": int(usage_raw.get("prompt_tokens", 0)),
            "completion_tokens": int(usage_raw.get("completion_tokens", 0)),
        }
        return data["choices"][0]["message"]["content"], usage

    def _chat_cursor(self, messages: list[ChatMessage], *, temperature: float) -> str:
        del temperature  # Cursor SDK selects model behavior server-side.
        if not config.CURSOR_API_KEY:
            raise RuntimeError("CURSOR_API_KEY not set")
        try:
            from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
        except ImportError as exc:
            raise RuntimeError("cursor-sdk not installed; run: pip install cursor-sdk") from exc

        prompt = _format_messages_for_cursor(messages)
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=config.CURSOR_API_KEY,
                model=config.CURSOR_MODEL,
                local=LocalAgentOptions(cwd=config.CURSOR_CWD),
            ),
        )
        if result.status != "finished":
            raise RuntimeError(f"cursor agent run failed: status={result.status}")
        text = (result.result or "").strip()
        if not text:
            raise RuntimeError("cursor agent returned empty response")
        return text

    def extract_facts(self, text: str, *, context: str = "") -> list[str]:
        """Use LLM to extract high-value facts from text."""
        prompt = (
            "从以下文本提取可长期记住的个人事实（每条一行，不要编号，不要废话）。"
            "若无有价值事实，只回复 NONE。\n"
        )
        if context:
            prompt += f"上下文: {context}\n"
        prompt += f"\n文本:\n{text[:4000]}"
        reply = self.chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.1,
            usage_command="extract_facts",
        )
        if "NONE" in reply.upper() and len(reply.strip()) < 20:
            return []
        lines = [line.strip().lstrip("-• ").strip() for line in reply.splitlines()]
        return [line for line in lines if line and len(line) > 4]


_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def reset_model_router() -> None:
    global _router
    _router = None
