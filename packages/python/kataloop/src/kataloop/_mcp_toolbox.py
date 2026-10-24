# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""The `Toolbox` over MCP servers, through the MCP SDK's streamable HTTP client
(docs/specs/tools.md)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from mcp.types import (
    REQUEST_TIMEOUT,
    CallToolResult,
    PaginatedRequestParams,
    TextContent,
)

from kataloop_core import Toolbox, ToolOutput, ToolServer, ToolSpec

HttpClientFactory = Callable[[dict[str, str], httpx2.Timeout], httpx2.AsyncClient]
"""Makes the HTTP client of one MCP session from the server's headers and
timeout. The toolbox closes the client when the session ends."""


def _http_client(
    headers: dict[str, str], timeout: httpx2.Timeout
) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(headers=headers, timeout=timeout)


class McpToolbox(Toolbox):
    """The tools of MCP servers, reached over streamable HTTP (docs/specs/tools.md).

    Each listing and each call opens a session of its own to the server, and
    closes it before it returns (TOOLS-3): nothing stays open between calls, so
    the toolbox needs no closing and a cancelled turn leaves no session behind
    (ENG-5). Every request carries the server's `headers` and waits at most its
    `timeout` (TOOLS-4).

    Args:
        http_client_factory: Makes the HTTP client of each session, from the
            server's headers and timeout, which the client must send and keep.
            By default an `httpx2.AsyncClient` with them and nothing else. A
            test redirects the requests through it, and a caller can add a
            proxy or certificates.
    """

    def __init__(
        self, *, http_client_factory: HttpClientFactory = _http_client
    ) -> None:
        self._http_client_factory = http_client_factory

    async def tools(self, server: ToolServer) -> Sequence[ToolSpec]:
        """The server's tools, every page of its listing, in its order.

        Raises:
            TimeoutError: The server did not answer within its timeout.
            MCPError: The server answered the listing with an error.
        """
        try:
            async with self._session(server) as session:
                page = await session.list_tools()
                listed = list(page.tools)
                while page.next_cursor is not None:
                    following = PaginatedRequestParams(cursor=page.next_cursor)
                    page = await session.list_tools(params=following)
                    listed.extend(page.tools)
        except Exception as error:
            raise _failure(error, server) from None
        return [
            ToolSpec(tool.name, tool.description or "", tool.input_schema)
            for tool in listed
        ]

    async def call(
        self, server: ToolServer, name: str, arguments: Mapping[str, Any]
    ) -> ToolOutput:
        """What the tool answered: its text, and whether it reports an error
        (TOOLS-5).

        Raises:
            TimeoutError: The server did not answer within its timeout, which
                the engine reports as a timeout (TOOLS-6).
            MCPError: The server answered the call with an error rather than a
                result.
        """
        try:
            async with self._session(server) as session:
                result = await session.call_tool(name, dict(arguments))
        except Exception as error:
            raise _failure(error, server) from None
        return ToolOutput(_text(result), is_error=result.is_error)

    @asynccontextmanager
    async def _session(self, server: ToolServer) -> AsyncIterator[ClientSession]:
        """An initialised session to the server, closed with its HTTP client when
        the block ends, however it ends (TOOLS-3)."""
        timeout = httpx2.Timeout(server.timeout)
        http = self._http_client_factory(dict(server.headers), timeout)
        async with (
            http,
            streamable_http_client(server.url, http_client=http) as (read, write),
            _Session(read, write, read_timeout_seconds=server.timeout) as session,
        ):
            await session.initialize()
            yield session


class _Session(ClientSession):
    """The SDK's session, without its check of a result's structured content.

    The model is given a result's content, never its structured content
    (TOOLS-5), so the check has nothing to protect; and in a session that has
    not listed the tools, the SDK lists them again before every call's result
    to make it.
    """

    async def validate_tool_result(self, name: str, result: CallToolResult) -> None:
        return None


def _text(result: CallToolResult) -> str:
    """What the model sees of a result: its parts, one per line, a text part as
    its text and any other as its JSON, compact and with its keys sorted, so that
    every port writes it alike (TOOLS-5)."""
    return "\n".join(
        part.text
        if isinstance(part, TextContent)
        else json.dumps(
            part.model_dump(by_alias=True, mode="json", exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for part in result.content
    )


def _failure(error: Exception, server: ToolServer) -> Exception:
    """The error an exchange with the server failed with.

    The SDK raises it out of its task groups, wrapped in exception groups; this
    is the error itself, and a timeout of the SDK's or of the HTTP client's is
    a `TimeoutError`, so that every timeout reads the same to the model
    (TOOLS-6). Cancellation is no `Exception` and is never caught here.
    """
    leaves = _leaves(error)
    if any(_timed_out(leaf) for leaf in leaves):
        return TimeoutError(
            f"The MCP server {server.id!r} did not answer within "
            f"{server.timeout:g} seconds"
        )
    for leaf in leaves:
        if isinstance(leaf, MCPError):
            return leaf
    return leaves[0]


def _leaves(error: Exception) -> list[Exception]:
    if isinstance(error, ExceptionGroup):
        return [leaf for inner in error.exceptions for leaf in _leaves(inner)]
    return [error]


def _timed_out(error: Exception) -> bool:
    if isinstance(error, MCPError):
        return error.code == REQUEST_TIMEOUT
    return isinstance(error, httpx2.TimeoutException | TimeoutError)
