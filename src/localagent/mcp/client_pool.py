"""Persistent MCP client connections with asyncio bridge."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Any

import httpx

from localagent.mcp.config import mcp_available
from localagent.mcp.errors import McpConnectionError, McpNotAvailableError, McpToolError
from localagent.mcp.schema_adapter import format_tool_result_content, mcp_tool_to_la_definition
from localagent.mcp.types import McpServerConfig, McpServerStatus, McpToolSpec

logger = logging.getLogger(__name__)


@dataclass
class _Request:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    future: Future[Any] | None = None


class _AsyncLoopThread:
    """Dedicated background event loop for MCP I/O."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="la-mcp-loop", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Any, *, timeout: float) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=max(1.0, timeout))

    def shutdown(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3)


class _ServerWorker:
    """One long-lived MCP session per server."""

    def __init__(self, config: McpServerConfig, loop_thread: _AsyncLoopThread) -> None:
        self.config = config
        self._loop_thread = loop_thread
        self.connected = False
        self.error = ""
        self.tools: list[McpToolSpec] = []
        self._queue: asyncio.Queue[_Request | None] | None = None
        self._worker_future: Future[None] | None = None

    def start(self) -> None:
        self._worker_future = asyncio.run_coroutine_threadsafe(
            self._worker(),
            self._loop_thread._loop,
        )

    async def _worker(self) -> None:
        self._queue = asyncio.Queue()
        try:
            if self.config.transport == "stdio":
                await self._run_stdio()
            else:
                await self._run_http()
        except Exception as exc:
            self.connected = False
            self.error = str(exc)
            logger.warning("mcp server %s worker failed: %s", self.config.server_id, exc)
        finally:
            if self._queue is not None:
                while not self._queue.empty():
                    req = self._queue.get_nowait()
                    if req and req.future and not req.future.done():
                        req.future.set_exception(McpConnectionError(self.error or "disconnected"))

    async def _run_stdio(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = {**os.environ, **self.config.env}
        params = StdioServerParameters(
            command=self.config.command,
            args=list(self.config.args),
            env=env,
            cwd=self.config.cwd or None,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await self._serve_session(session)

    async def _run_http(self) -> None:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        timeout = httpx.Timeout(self.config.timeout_seconds, read=self.config.timeout_seconds * 2)
        async with httpx.AsyncClient(headers=self.config.headers, timeout=timeout) as client:
            async with streamable_http_client(self.config.url, http_client=client) as streams:
                read, write, _get_sid = streams
                async with ClientSession(read, write) as session:
                    await self._serve_session(session)

    async def _serve_session(self, session: Any) -> None:
        from mcp import ClientSession

        assert isinstance(session, ClientSession)
        await session.initialize()
        self.connected = True
        self.error = ""
        assert self._queue is not None

        list_result = await session.list_tools()
        self.tools = [
            mcp_tool_to_la_definition(
                server_id=self.config.server_id,
                name=t.name,
                description=str(t.description or ""),
                input_schema=t.inputSchema if isinstance(t.inputSchema, dict) else {},
            )
            for t in list_result.tools
        ]

        while True:
            req = await self._queue.get()
            if req is None:
                break
            assert req.future is not None
            try:
                if req.kind == "list_tools":
                    req.future.set_result(list(self.tools))
                elif req.kind == "call_tool":
                    tool_name = str(req.payload.get("tool_name") or "")
                    arguments = req.payload.get("arguments") or {}
                    if not isinstance(arguments, dict):
                        arguments = {}
                    result = await session.call_tool(tool_name, arguments)
                    req.future.set_result(format_tool_result_content(result))
                else:
                    req.future.set_exception(McpToolError(f"unknown request: {req.kind}"))
            except Exception as exc:
                req.future.set_exception(exc)

    def _submit(self, kind: str, payload: dict[str, Any] | None = None, *, timeout: float) -> Any:
        if self._queue is None:
            raise McpConnectionError(self.error or "worker not started")
        future: Future[Any] = Future()
        req = _Request(kind=kind, payload=payload or {}, future=future)
        self._loop_thread._loop.call_soon_threadsafe(self._queue.put_nowait, req)
        return future.result(timeout=max(1.0, timeout))

    def list_tools_sync(self) -> list[McpToolSpec]:
        if self.tools and self.connected:
            return list(self.tools)
        return self._submit("list_tools", timeout=float(self.config.timeout_seconds))

    def call_tool_sync(self, tool_name: str, arguments: dict[str, Any]) -> str:
        return self._submit(
            "call_tool",
            {"tool_name": tool_name, "arguments": arguments},
            timeout=float(self.config.timeout_seconds),
        )

    def shutdown(self) -> None:
        if self._queue is not None:
            self._loop_thread._loop.call_soon_threadsafe(self._queue.put_nowait, None)


class McpClientPool:
    """Process-level pool of MCP server connections."""

    _loop_thread: _AsyncLoopThread | None = None
    _workers: dict[str, _ServerWorker] = {}
    _status: dict[str, McpServerStatus] = {}

    @classmethod
    def _ensure_loop(cls) -> _AsyncLoopThread:
        if cls._loop_thread is None:
            cls._loop_thread = _AsyncLoopThread()
        return cls._loop_thread

    @classmethod
    def refresh(cls, servers: dict[str, McpServerConfig]) -> None:
        if not mcp_available():
            cls._workers.clear()
            cls._status = {
                sid: McpServerStatus(config=cfg, connected=False, error="mcp 包未安装")
                for sid, cfg in servers.items()
            }
            return

        cls.shutdown()
        loop = cls._ensure_loop()
        cls._workers = {}
        cls._status = {}

        for server_id, cfg in servers.items():
            worker = _ServerWorker(cfg, loop)
            cls._workers[server_id] = worker
            status = McpServerStatus(config=cfg)
            try:
                worker.start()
                # Wait briefly for initialize + list_tools
                deadline = cfg.timeout_seconds + 5
                import time

                start = time.monotonic()
                while time.monotonic() - start < deadline:
                    if worker.error:
                        break
                    if worker.connected and worker.tools:
                        break
                    time.sleep(0.05)
                if worker.connected and worker.tools:
                    status.connected = True
                    status.tools = [t.la_name for t in worker.tools]
                    status.tool_count = len(worker.tools)
                else:
                    status.error = worker.error or "连接超时"
            except Exception as exc:
                status.error = str(exc)
            cls._status[server_id] = status

    @classmethod
    def statuses(cls) -> dict[str, McpServerStatus]:
        return dict(cls._status)

    @classmethod
    def all_tools(cls) -> list[McpToolSpec]:
        specs: list[McpToolSpec] = []
        for worker in cls._workers.values():
            if worker.connected:
                specs.extend(worker.tools)
        return specs

    @classmethod
    def get_server_status(cls, server_id: str) -> McpServerStatus | None:
        return cls._status.get(normalize_id(server_id))

    @classmethod
    def call_tool(cls, server_id: str, tool_name: str, arguments: dict[str, Any]) -> str:
        if not mcp_available():
            raise McpNotAvailableError("未安装 mcp 包，请运行: pip install 'la-localagent[mcp]'")
        sid = normalize_id(server_id)
        worker = cls._workers.get(sid)
        if worker is None or not worker.connected:
            raise McpConnectionError(f"MCP server 未连接: {sid}")
        try:
            return worker.call_tool_sync(tool_name, arguments)
        except Exception as exc:
            raise McpToolError(str(exc)) from exc

    @classmethod
    def test_server(cls, server_id: str) -> McpServerStatus:
        sid = normalize_id(server_id)
        status = cls._status.get(sid)
        if status is None:
            raise McpConnectionError(f"未知 MCP server: {server_id}")
        return status

    @classmethod
    def shutdown(cls) -> None:
        for worker in cls._workers.values():
            worker.shutdown()
        cls._workers.clear()
        if cls._loop_thread is not None:
            cls._loop_thread.shutdown()
            cls._loop_thread = None


def normalize_id(server_id: str) -> str:
    from localagent.mcp.schema_adapter import normalize_server_id

    return normalize_server_id(server_id)
