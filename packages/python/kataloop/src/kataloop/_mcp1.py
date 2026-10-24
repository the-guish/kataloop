# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""`McpToolbox` on mcp 1, whose HTTP stack is httpx (docs/specs/tools.md)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import McpError
from mcp.types import INTERNAL_ERROR, CallToolResult, ErrorData, ListToolsResult

from kataloop._mcp_shared import Page, SdkToolbox, Session, text
from kataloop_core import ToolOutput, ToolServer, ToolSpec

McpHttpClient = httpx.AsyncClient
"""The HTTP client the SDK sends with: httpx's, on mcp 1."""

McpHttpTimeout = httpx.Timeout
"""The timeouts of that client."""

HttpClientFactory = Callable[[dict[str, str], McpHttpTimeout], McpHttpClient]
"""Makes the HTTP client of one MCP session from the server's headers and
timeout. The toolbox closes the client when the session ends."""


class MCPError(McpError):
    """An error response of the server: the SDK's `McpError`, under the name mcp
    2 gives it, so that a failed call reads the same to the model on either
    major (TOOLS-6, TOOLS-10)."""


def _http_client(headers: dict[str, str], timeout: McpHttpTimeout) -> McpHttpClient:
    return McpHttpClient(headers=headers, timeout=timeout)


class McpToolbox(SdkToolbox):
    """The tools of MCP servers, reached over streamable HTTP (docs/specs/tools.md).

    Each listing and each call opens a session of its own to the server, and
    closes it before it returns (TOOLS-3): nothing stays open between calls, so
    the toolbox needs no closing and a cancelled turn leaves no session behind
    (ENG-5). Every request carries the server's `headers` and waits at most its
    `timeout` (TOOLS-4). This is the toolbox on mcp 1 (TOOLS-8).

    Args:
        http_client_factory: Makes the HTTP client of each session, from the
            server's headers and timeout, which the client must send and keep.
            By default an `McpHttpClient`, here an `httpx.AsyncClient`, with
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
        waits = timedelta(seconds=server.timeout)
        async with (
            http,
            streamable_http_client(server.url, http_client=http) as (read, write, _),
            Session(read, write, read_timeout_seconds=waits) as session,
        ):
            await session.initialize()
            yield session

    def _page(self, listing: ListToolsResult) -> Page:
        tools = [
            ToolSpec(tool.name, tool.description or "", tool.inputSchema)
            for tool in listing.tools
        ]
        return Page(tools, listing.nextCursor)

    def _output(self, result: CallToolResult) -> ToolOutput:
        return ToolOutput(text(result.content), is_error=result.isError)

    def _timed_out(self, error: Exception) -> bool:
        if isinstance(error, McpError):
            # The SDK's own wait for a response gives up with HTTP's status.
            return error.error.code == httpx.codes.REQUEST_TIMEOUT
        return isinstance(error, httpx.TimeoutException)

    def _server_error(self, error: Exception) -> Exception | None:
        if isinstance(error, McpError):
            return MCPError(error.error)
        if isinstance(error, httpx.HTTPStatusError):
            # An HTTP error status, or a redirect the SDK does not follow, which
            # mcp 2 reads as an error response of the server.
            return MCPError(ErrorData(code=INTERNAL_ERROR, message=str(error)))
        return None
