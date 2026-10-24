# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""`McpToolbox` on mcp 2, whose HTTP stack is httpx2 (docs/specs/tools.md)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx2
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp.types import REQUEST_TIMEOUT, CallToolResult, ListToolsResult

from kataloop._mcp_shared import Page, SdkToolbox, Session, text
from kataloop_core import ToolOutput, ToolServer, ToolSpec

McpHttpClient = httpx2.AsyncClient
"""The HTTP client the SDK sends with: httpx2's, on mcp 2."""

McpHttpTimeout = httpx2.Timeout
"""The timeouts of that client."""

HttpClientFactory = Callable[[dict[str, str], McpHttpTimeout], McpHttpClient]
"""Makes the HTTP client of one MCP session from the server's headers and
timeout. The toolbox closes the client when the session ends."""


def _http_client(headers: dict[str, str], timeout: McpHttpTimeout) -> McpHttpClient:
    return McpHttpClient(headers=headers, timeout=timeout)


class McpToolbox(SdkToolbox):
    """The tools of MCP servers, reached over streamable HTTP (docs/specs/tools.md).

    Each listing and each call opens a session of its own to the server, and
    closes it before it returns (TOOLS-3): nothing stays open between calls, so
    the toolbox needs no closing and a cancelled turn leaves no session behind
    (ENG-5). Every request carries the server's `headers` and waits at most its
    `timeout` (TOOLS-4). This is the toolbox on mcp 2 (TOOLS-8).

    Args:
        http_client_factory: Makes the HTTP client of each session, from the
            server's headers and timeout, which the client must send and keep.
            By default an `McpHttpClient`, here an `httpx2.AsyncClient`, with
            them and nothing else. A test redirects the requests through it,
            and a caller can add a proxy or certificates.
    """

    def __init__(
        self, *, http_client_factory: HttpClientFactory = _http_client
    ) -> None:
        self._http_client_factory = http_client_factory

    @asynccontextmanager
    async def _session(self, server: ToolServer) -> AsyncIterator[Session]:
        timeout = McpHttpTimeout(server.timeout)
        http = self._http_client_factory(dict(server.headers), timeout)
        async with (
            http,
            streamable_http_client(server.url, http_client=http) as (read, write),
            Session(read, write, read_timeout_seconds=server.timeout) as session,
        ):
            await session.initialize()
            yield session

    def _page(self, listing: ListToolsResult) -> Page:
        tools = [
            ToolSpec(tool.name, tool.description or "", tool.input_schema)
            for tool in listing.tools
        ]
        return Page(tools, listing.next_cursor)

    def _output(self, result: CallToolResult) -> ToolOutput:
        return ToolOutput(text(result.content), is_error=result.is_error)

    def _timed_out(self, error: Exception) -> bool:
        if isinstance(error, MCPError):
            return error.code == REQUEST_TIMEOUT
        return isinstance(error, httpx2.TimeoutException)

    def _server_error(self, error: Exception) -> Exception | None:
        return error if isinstance(error, MCPError) else None
