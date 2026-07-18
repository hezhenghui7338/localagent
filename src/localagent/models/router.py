"""Model service router — priority driven by LA_MODEL_SERVERS list order."""

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
from localagent.model_servers import ModelServer, openai_compatible_headers

logger = logging.getLogger(__name__)

_COMPLETION_CAPS = frozenset({"completion", "tools", "vision"})


@dataclass
class ChatMessage:
    role: str
    content: str


def _parse_profile_updates_reply(reply: str) -> list[dict]:
    """Parse LLM JSON for core_profile pin updates."""
    import re

    raw = (reply or "").strip()
    if not raw:
        return []
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to recover a JSON object embedded in prose.
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return []
    if isinstance(data, list):
        updates = data
    elif isinstance(data, dict):
        updates = data.get("updates") or []
    else:
        return []
    if not isinstance(updates, list):
        return []
    cleaned: list[dict] = []
    for item in updates:
        if isinstance(item, dict) and item.get("field") and item.get("value") is not None:
            cleaned.append(item)
    return cleaned


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
    """Unified LLM access with configurable fallback chain."""

    def __init__(self) -> None:
        self._ollama_available: bool | None = None
        self._resolved_ollama_model: str | None = None
        self._ollama_slow: bool = False
        self.last_provider: str | None = None
        self.last_model: str | None = None

    def _server(self, provider: str) -> ModelServer | None:
        return config.get_model_server(provider)

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
        ollama_skipped = False
        if auto_mode and self._ollama_slow:
            if "ollama" in providers:
                ollama_skipped = True
            providers = [p for p in providers if p != "ollama"]

        attempted: set[str] = set()
        last_error: Exception | None = None
        for provider in providers:
            attempted.add(provider)
            try:
                return self._chat_with_provider(
                    provider,
                    messages,
                    temperature=temperature,
                    on_token=on_token,
                    usage_command=usage_command,
                    session_id=session_id,
                    auto_mode=auto_mode,
                )
            except (httpx.TimeoutException, TimeoutError) as exc:
                if provider == "ollama" and auto_mode:
                    server = self._server("ollama")
                    timeout = server.chat_timeout if server else config.OLLAMA_CHAT_TIMEOUT
                    logger.warning("ollama chat timed out after %.0fs, falling back", timeout)
                    self._ollama_slow = True
                    last_error = exc
                    continue
                last_error = exc
                logger.warning("provider %s failed: %s", provider, exc)
            except Exception as exc:
                logger.warning("provider %s failed: %s", provider, exc)
                last_error = exc

        hint = self._failure_hint()
        if auto_mode and self._should_retry_ollama(attempted, ollama_skipped):
            try:
                logger.info("cloud providers failed, retrying ollama with full timeout")
                return self._chat_with_provider(
                    "ollama",
                    messages,
                    temperature=temperature,
                    on_token=on_token,
                    usage_command=usage_command,
                    session_id=session_id,
                    auto_mode=False,
                )
            except Exception as exc:
                logger.warning("ollama last-resort retry failed: %s", exc)
                last_error = exc

        raise RuntimeError(f"all model providers failed: {last_error}{hint}")

    def _should_retry_ollama(self, attempted: set[str], ollama_skipped: bool) -> bool:
        if not self.is_ollama_available():
            return False
        if ollama_skipped or self._ollama_slow:
            return True
        return "ollama" not in attempted

    def _chat_with_provider(
        self,
        provider: str,
        messages: list[ChatMessage],
        *,
        temperature: float,
        on_token: Callable[[str], None] | None,
        usage_command: str,
        session_id: str | None,
        auto_mode: bool,
    ) -> str:
        server = self._server(provider)
        if not server:
            raise RuntimeError(f"unknown provider: {provider}")

        if provider == "ollama":
            timeout = server.chat_timeout if auto_mode else server.timeout
            stream = on_token is not None and server.chat_stream
            text, usage = self._chat_ollama(
                server,
                messages,
                temperature=temperature,
                on_token=on_token if stream else None,
                timeout=timeout,
            )
            model = self.resolve_ollama_model()
            self.last_provider = provider
            self.last_model = model
            if auto_mode or timeout == server.timeout:
                self._ollama_slow = False
            logger.info(
                "chat provider=%s model=%s command=%s auto=%s",
                provider,
                model,
                usage_command,
                auto_mode,
            )
            self._record_usage(
                provider,
                model,
                usage=usage,
                messages=messages,
                response=text,
                command=usage_command,
                session_id=session_id,
            )
            return text

        if provider == "cursor":
            text = self._chat_cursor(server, messages, temperature=temperature)
            self.last_provider = provider
            self.last_model = server.model
            logger.info(
                "chat provider=%s model=%s command=%s auto=%s",
                provider,
                server.model,
                usage_command,
                auto_mode,
            )
            log_usage(
                provider,
                server.model,
                command=usage_command,
                prompt_tokens=sum(estimate_tokens(m.content) for m in messages),
                completion_tokens=estimate_tokens(text),
                session_id=session_id,
                per_call=True,
            )
            return text

        if not server.api_key:
            raise RuntimeError(f"{provider} api_key not set")
        stream = on_token is not None and server.chat_stream
        text, usage = self._chat_openai_compatible(
            server=server,
            messages=messages,
            temperature=temperature,
            on_token=on_token if stream else None,
        )
        self.last_provider = provider
        self.last_model = server.model
        logger.info(
            "chat provider=%s model=%s command=%s auto=%s",
            provider,
            server.model,
            usage_command,
            auto_mode,
        )
        self._record_usage(
            provider,
            server.model,
            usage=usage,
            messages=messages,
            response=text,
            command=usage_command,
            session_id=session_id,
        )
        return text

    def is_ollama_available(self) -> bool:
        if self._ollama_available is not None:
            return self._ollama_available
        server = self._server("ollama")
        if not server or not server.base_url:
            self._ollama_available = False
            return False
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(f"{server.base_url.rstrip('/')}/api/tags")
                self._ollama_available = resp.status_code == 200
        except Exception:
            self._ollama_available = False
        return self._ollama_available

    def is_ollama_model_loaded(self, model: str | None = None) -> bool:
        """True when the target chat model is already resident in Ollama VRAM."""
        target = (model or "").strip()
        if not target:
            try:
                target = self.resolve_ollama_model()
            except Exception:
                return False
        for item in self._list_running_ollama_models():
            if not _is_completion_model(item):
                continue
            name = item.get("name") or item.get("model") or ""
            if name == target:
                return True
        return False

    def should_hint_ollama_cold_start(self, prefer: str | None = None) -> bool:
        """True when the next chat will likely wait on first-time Ollama model load."""
        auto_mode = prefer is None or prefer == config.DEFAULT_MODEL_PROVIDER
        if auto_mode:
            if self._ollama_slow:
                return False
            providers = self._provider_order(None)
            if not providers or providers[0] != "ollama":
                return False
        elif prefer != "ollama":
            return False
        if not self.is_ollama_available():
            return False
        return not self.is_ollama_model_loaded()

    def resolve_ollama_model(self) -> str:
        """Pick an installed Ollama model, falling back from configured name."""
        if self._resolved_ollama_model:
            return self._resolved_ollama_model

        server = self._server("ollama")
        configured = server.model if server else config.OLLAMA_MODEL
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

            running_names = {
                m.get("name") or m.get("model") or ""
                for m in self._list_running_ollama_models()
                if _is_completion_model(m)
            }
            for model in completion_models:
                name = model.get("name", "")
                if name and name in running_names:
                    logger.info("ollama model %s not found, using loaded %s", configured, name)
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

    def resolve_effective_provider(self, choice: str) -> str:
        """Map ``auto`` to the first available provider in priority order."""
        choice = (choice or config.DEFAULT_MODEL_PROVIDER).strip().lower()
        if choice != config.DEFAULT_MODEL_PROVIDER:
            return choice
        status = self.provider_status()
        for name in config.MODEL_PROVIDER_PRIORITY:
            if status.get(name):
                return name
        if config.MODEL_PROVIDER_PRIORITY:
            return config.MODEL_PROVIDER_PRIORITY[0]
        return "ollama"

    def list_provider_models(self, provider: str) -> list[str]:
        """List model IDs supported by a concrete provider (not ``auto``)."""
        name = provider.strip().lower()
        if name == config.DEFAULT_MODEL_PROVIDER:
            name = self.resolve_effective_provider(name)
        if name == "ollama":
            return self.list_completion_models()
        if name == "cursor":
            return self._list_cursor_models()
        return self._list_openai_compatible_models(name)

    def clear_model_cache(self) -> None:
        """Drop cached model resolution after config changes."""
        self._resolved_ollama_model = None

    def _list_cursor_models(self) -> list[str]:
        server = self._server("cursor")
        api_key = server.api_key if server else ""
        if not api_key:
            return []
        try:
            from cursor_sdk import Cursor

            models = Cursor.models.list(api_key=api_key)
        except Exception as exc:
            logger.warning("cursor models.list failed: %s", exc)
            return []
        ids: list[str] = []
        for item in models or []:
            model_id = getattr(item, "id", None) or (item.get("id") if isinstance(item, dict) else None)
            if model_id:
                ids.append(str(model_id))
        return ids

    def _list_openai_compatible_models(self, provider: str) -> list[str]:
        server = self._server(provider)
        if not server or not server.base_url:
            return []
        headers: dict[str, str] = {}
        if server.api_key:
            headers["Authorization"] = f"Bearer {server.api_key}"
        headers.update(openai_compatible_headers(provider))
        try:
            with httpx.Client(timeout=min(15.0, server.timeout or 15.0)) as client:
                resp = client.get(f"{server.base_url.rstrip('/')}/models", headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning("%s /models failed: %s", provider, exc)
            return []
        raw = data.get("data", data) if isinstance(data, dict) else data
        if not isinstance(raw, list):
            return []
        ids: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                model_id = item.get("id") or item.get("name")
            else:
                model_id = getattr(item, "id", None) or getattr(item, "name", None)
            if model_id:
                ids.append(str(model_id))
        return ids

    def _failure_hint(self) -> str:
        models = self.list_completion_models()
        server = self._server("ollama")
        configured = server.model if server else config.OLLAMA_MODEL
        if not models:
            return (
                "\n提示: 未检测到可用的 Ollama 对话模型。"
                "请运行 `ollama pull qwen3.5:4b`，或先 `ollama pull` 任意对话模型，"
                "或在 model_servers.yaml 中配置 ollama.model。"
            )
        return (
            f"\n提示: 已检测到 Ollama 模型 {', '.join(models)}，当前配置为 {configured}。"
            " 将自动改用已安装模型；也可用 `/model` 手动切换。"
        )

    def _list_ollama_models(self) -> list[dict[str, Any]]:
        server = self._server("ollama")
        base_url = server.base_url if server else config.OLLAMA_BASE_URL
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{base_url.rstrip('/')}/api/tags")
            resp.raise_for_status()
            return resp.json().get("models", [])

    def _list_running_ollama_models(self) -> list[dict[str, Any]]:
        server = self._server("ollama")
        base_url = server.base_url if server else config.OLLAMA_BASE_URL
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(f"{base_url.rstrip('/')}/api/ps")
                resp.raise_for_status()
                return resp.json().get("models", []) or []
        except Exception:
            return []

    def provider_status(self) -> dict[str, bool]:
        status: dict[str, bool] = {}
        for server in config.MODEL_SERVERS:
            if server.provider == "ollama":
                status[server.provider] = self.is_ollama_available()
            else:
                status[server.provider] = server.is_configured
        return status

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

    def format_model_hint(self, provider: str) -> str:
        """Return the configured model name for a provider choice."""
        if provider == config.DEFAULT_MODEL_PROVIDER:
            provider = config.MODEL_PROVIDER_PRIORITY[0]
        server = self._server(provider)
        if provider == "ollama":
            return self.resolve_ollama_model() if self.is_ollama_available() else (server.model if server else config.OLLAMA_MODEL)
        return server.model if server else ""

    def _ollama_chat_payload(
        self,
        server: ModelServer,
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
            "keep_alive": server.keep_alive,
            "options": {
                "temperature": temperature,
                "num_predict": server.num_predict,
                "num_ctx": server.num_ctx,
            },
        }
        if not server.think:
            payload["think"] = False
        return payload

    def _chat_ollama(
        self,
        server: ModelServer,
        messages: list[ChatMessage],
        *,
        temperature: float,
        on_token: Callable[[str], None] | None = None,
        timeout: float | None = None,
    ) -> tuple[str, dict[str, int]]:
        model = self.resolve_ollama_model()
        stream = on_token is not None
        payload = self._ollama_chat_payload(server, messages, temperature=temperature, stream=stream)
        url = f"{server.base_url.rstrip('/')}/api/chat"
        request_timeout = timeout if timeout is not None else server.timeout
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
                        chunk = data.get("message", {}).get("content") or ""
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
        # Qwen3+ may return content=null; never propagate None into the agent loop.
        return data.get("message", {}).get("content") or "", usage

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

    def _chat_openai_compatible(
        self,
        *,
        server: ModelServer,
        messages: list[ChatMessage],
        temperature: float,
        on_token: Callable[[str], None] | None = None,
    ) -> tuple[str, dict[str, int]]:
        headers = {
            "Authorization": f"Bearer {server.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(openai_compatible_headers(server.provider))
        stream = on_token is not None
        payload: dict[str, Any] = {
            "model": server.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "stream": stream,
        }
        url = f"{server.base_url.rstrip('/')}/chat/completions"
        with httpx.Client(timeout=server.timeout) as client:
            if stream:
                parts: list[str] = []
                usage: dict[str, int] = {}
                with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = resp.read().decode(errors="replace")[:200]
                        detail = body
                        try:
                            detail = json.loads(body).get("error", {}).get("message", body)
                        except Exception:
                            pass
                        if resp.status_code == 404:
                            raise RuntimeError(
                                f"{server.provider} model {server.model!r} unavailable: {detail}"
                            )
                        resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data_str = line[6:].strip()
                        elif line.startswith("data:"):
                            data_str = line[5:].strip()
                        else:
                            continue
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        usage_raw = data.get("usage") or {}
                        if usage_raw:
                            usage = {
                                "prompt_tokens": int(usage_raw.get("prompt_tokens", 0)),
                                "completion_tokens": int(
                                    usage_raw.get("completion_tokens", 0)
                                ),
                            }
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        chunk = delta.get("content") or ""
                        if chunk:
                            parts.append(chunk)
                            on_token(chunk)
                return "".join(parts), usage

            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code == 404:
                detail = resp.text[:200]
                try:
                    detail = resp.json().get("error", {}).get("message", detail)
                except Exception:
                    pass
                raise RuntimeError(f"{server.provider} model {server.model!r} unavailable: {detail}")
            resp.raise_for_status()
            data = resp.json()
        usage_raw = data.get("usage") or {}
        usage = {
            "prompt_tokens": int(usage_raw.get("prompt_tokens", 0)),
            "completion_tokens": int(usage_raw.get("completion_tokens", 0)),
        }
        message = data["choices"][0]["message"]
        return message.get("content") or "", usage

    def _chat_cursor(self, server: ModelServer, messages: list[ChatMessage], *, temperature: float) -> str:
        del temperature  # Cursor SDK selects model behavior server-side.
        if not server.api_key:
            raise RuntimeError("cursor api_key not set")
        try:
            from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
        except ImportError as exc:
            raise RuntimeError("cursor-sdk not installed; run: pip install cursor-sdk") from exc

        prompt = _format_messages_for_cursor(messages)
        cwd = server.cwd or str(config.PROJECT_ROOT)
        max_retries = server.max_retries
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                result = Agent.prompt(
                    prompt,
                    AgentOptions(
                        api_key=server.api_key,
                        model=server.model,
                        local=LocalAgentOptions(cwd=cwd),
                    ),
                )
                if result.status != "finished":
                    raise RuntimeError(f"cursor agent run failed: status={result.status}")
                text = (result.result or "").strip()
                if not text:
                    raise RuntimeError("cursor agent returned empty response")
                return text
            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    delay = min(2**attempt, 5)
                    logger.warning(
                        "cursor attempt %d/%d failed: %s, retrying in %.0fs",
                        attempt + 1,
                        max_retries + 1,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
        assert last_error is not None
        raise last_error

    def extract_memories(self, text: str, *, context: str = "") -> list:
        """Extract structured conversation memories (narrative + slots)."""
        from localagent.memory.conversation_extract import (
            conversation_extract_prompt,
            parse_extracted_memories,
        )

        prompt = conversation_extract_prompt(context=context)
        prompt += f"\n\n对话:\n{text[:6000]}"
        reply = self.chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.1,
            usage_command="extract_memories",
        )
        return parse_extracted_memories(reply)

    def extract_facts(self, text: str, *, context: str = "") -> list[str]:
        """Backward-compatible: return narrative text lines from extract_memories."""
        memories = self.extract_memories(text, context=context)
        return [m.text for m in memories]

    def extract_profile_updates(
        self,
        facts: list[str],
        *,
        current_profile: str = "",
    ) -> list[dict]:
        """Decide which durable identity attributes to pin into core_profile.

        Returns a list of update dicts, e.g.
        ``{"field": "preference", "key": "居住地", "value": "深圳", "confidence": 0.9}``.
        """
        if not facts:
            return []
        joined = "\n".join(f"- {fact.strip()}" for fact in facts if fact.strip())
        if not joined:
            return []
        prompt = (
            "你是用户核心画像编辑器。根据下列事实，决定应写入 Hot 层 core_profile 的持久身份信息。\n"
            "只输出 JSON（不要 markdown、不要解释）：\n"
            '{"updates":[{"field":"name|preference|current_status|life_anchor",'
            '"key":"偏好键可选","value":"值","label":"锚点标签可选",'
            '"start":"YYYY或YYYY-MM可选","end":"结束或null","description":"锚点说明可选",'
            '"confidence":0.0}]}\n'
            "字段说明：\n"
            "- name: 用户姓名\n"
            "- preference: 写入 preferences；key 只用 居住地/职业/家庭/喜欢/偏好 短键\n"
            "- current_status: 仅限稳定身份/角色（如职业、长期角色），一句话\n"
            "- life_anchor: 有明确时间段的人生阶段（需 label+start）\n"
            "规则：\n"
            "- 只 pin 稳定身份/偏好/家庭/职业/居住地；跳过一次性琐事\n"
            "- 禁止把临时计划/找房/租房/看房/搜索意图写入 current_status\n"
            "- 临时居住需求（租金、户型、房源、看房条件）留在 Warm 记忆，不要 pin 到 Hot；"
            "居住相关 preference 只允许稳定短键「居住地」（城市/区域名），禁止「居住/偏好」等复合键\n"
            "- 来自旧导入或过时事实时更保守：不确定则跳过，confidence 提高门槛\n"
            "- 无更新时 "
            '{"updates":[]}。confidence 为 0~1。\n'
        )
        if current_profile.strip():
            prompt += f"\n当前画像:\n{current_profile[:1500]}\n"
        prompt += f"\n事实:\n{joined[:4000]}"
        reply = self.chat(
            [ChatMessage(role="user", content=prompt)],
            temperature=0.1,
            usage_command="extract_profile_updates",
        )
        return _parse_profile_updates_reply(reply)


_router: ModelRouter | None = None


def get_model_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def reset_model_router() -> None:
    global _router
    _router = None


def shutdown_cursor_sdk() -> None:
    """Close cursor-sdk resources before interpreter shutdown.

    cursor_sdk registers an atexit handler that joins HTTP server threads.
    After a double Ctrl+C, a pending KeyboardInterrupt can fire during that
    join and print a noisy traceback. Shut down explicitly while SIGINT is
    ignored, then unregister the atexit hook.
    """
    try:
        import atexit
        import signal

        from cursor_sdk import close_default_client
    except ImportError:
        return

    atexit.unregister(close_default_client)
    previous = signal.getsignal(signal.SIGINT)
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        close_default_client()
    except BaseException:
        pass
    finally:
        signal.signal(signal.SIGINT, previous)
