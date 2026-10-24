# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""What `McpToolbox` does on either major of the MCP SDK (docs/specs/tools.md).

The module of each major, `_mcp1` or `_mcp2`, opens its SDK's session over its
HTTP stack and reads the SDK's fields under their names; the rest is here,
written to what the two majors share.
"""

from __future__ import annotations

import json
from abc import abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, NamedTuple

from mcp.client.session import ClientSession
from mcp.types import (
    CallToolResult,
    ContentBlock,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
)

from kataloop_core import Toolbox, ToolOutput, ToolServer, ToolSpec


class Page(NamedTuple):
    """One page of a server's listing."""

    tools: list[ToolSpec]
    next_cursor: str | None


class SdkToolbox(Toolbox):
    """The `Toolbox` over sessions of the MCP SDK, whichever its major.

    Each listing and each call opens a session of its own to the server, and
    closes it before it returns (TOOLS-3): nothing stays open between calls, so
    the toolbox needs no closing and a cancelled turn leaves no session behind
    (ENG-5). Every request carries the server's `headers` and waits at most its
    `timeout` (TOOLS-4).
    """

    async def tools(self, server: ToolServer) -> Sequence[ToolSpec]:
        """The server's tools, every page of its listing, in its order.

        Raises:
            TimeoutError: The server did not answer within its timeout.
            MCPError: The server answered the listing with an error.
        """
        try:
            async with self._session(server) as session:
                page = self._page(await session.list_tools())
                listed = page.tools
                while page.next_cursor is not None:
                    following = PaginatedRequestParams(cursor=page.next_cursor)
                    page = self._page(await session.list_tools(params=following))
                    listed.extend(page.tools)
        except Exception as error:
            raise self._failure(error, server) from None
        return listed

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
            raise self._failure(error, server) from None
        return self._output(result)

    @abstractmethod
    def _session(self, server: ToolServer) -> AbstractAsyncContextManager[Session]:
        """An initialised session to the server, closed with its HTTP client when
        the block ends, however it ends (TOOLS-3)."""

    @abstractmethod
    def _page(self, listing: ListToolsResult) -> Page:
        """The tools of a page of the listing, and the cursor of the next."""

    @abstractmethod
    def _output(self, result: CallToolResult) -> ToolOutput:
        """What the model sees of a result: `text` of its content, and whether
        the server marks it `isError` (TOOLS-5)."""

    @abstractmethod
    def _timed_out(self, error: Exception) -> bool:
        """Whether the SDK or the HTTP client gave up waiting with this error."""

    @abstractmethod
    def _server_error(self, error: Exception) -> Exception | None:
        """The `MCPError` to raise if `error` is an error response of the server,
        under that name on either major (TOOLS-6, TOOLS-10), or None."""

    def _failure(self, error: Exception, server: ToolServer) -> Exception:
        """The error an exchange with the server failed with.

        The SDK raises it out of its task groups, wrapped in exception groups;
        this is the error itself, and a timeout of the SDK's or of the HTTP
        client's is a `TimeoutError`, so that every timeout reads the same to
        the model (TOOLS-6). Cancellation is no `Exception` and is never caught
        here.
        """
        leaves = _leaves(error)
        if any(
            isinstance(leaf, TimeoutError) or self._timed_out(leaf) for leaf in leaves
        ):
            return TimeoutError(
                f"The MCP server {server.id!r} did not answer within "
                f"{server.timeout:g} seconds"
            )
        for leaf in leaves:
            if (answered := self._server_error(leaf)) is not None:
                return answered
        return leaves[0]


class Session(ClientSession):
    """The SDK's session, without its check of a result's structured content.

    The model is given a result's content, never its structured content
    (TOOLS-5), so the check has nothing to protect; and in a session that has
    not listed the tools, the SDK lists them again before every call's result
    to make it. The check is `validate_tool_result` on mcp 2 and
    `_validate_tool_result` on mcp 1, and the session turns off both.
    """

    async def validate_tool_result(self, name: str, result: CallToolResult) -> None:
        return None

    async def _validate_tool_result(self, name: str, result: CallToolResult) -> None:
        return None


def text(content: Iterable[ContentBlock]) -> str:
    """What the model sees of a result's content: its parts, one per line, a text
    part as its text and any other as its JSON under MCP's names, compact and
    with its keys sorted, so that every port writes it alike (TOOLS-5)."""
    return "\n".join(
        part.text
        if isinstance(part, TextContent)
        else json.dumps(
            part.model_dump(by_alias=True, mode="json", exclude_none=True),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for part in content
    )


def _leaves(error: Exception) -> list[Exception]:
    if isinstance(error, ExceptionGroup):
        return [leaf for inner in error.exceptions for leaf in _leaves(inner)]
    return [error]
