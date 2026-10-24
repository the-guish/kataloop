# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""An MCP server of mcp 2's in the process, and the toolbox that reaches it
(test_mcp_toolbox.py)."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from mcp.server import Server, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
)

from kataloop import McpToolbox

Answer = Callable[[str, dict[str, Any], str | None], Awaitable[dict[str, Any]]]
"""The server's answer to a request, from its method, its params and the
credential it came with: the `result`, or the JSON-RPC `error`, in MCP's JSON
form."""

ServerError = MCPError
"""What the SDK raises for an error response of the server."""

ConnectError = httpx2.ConnectError
"""The error of a server out of reach."""


@asynccontextmanager
async def serving(answer: Answer) -> AsyncIterator[McpToolbox]:
    """A toolbox whose every request reaches the server in the process."""

    async def answered(
        ctx: ServerRequestContext[Any, Any],
        method: str,
        params: PaginatedRequestParams | CallToolRequestParams | None,
    ) -> dict[str, Any]:
        assert ctx.request is not None
        sent = (
            {}
            if params is None
            else params.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        response = await answer(method, sent, ctx.request.headers.get("authorization"))
        if "error" in response:
            raise MCPError(response["error"]["code"], response["error"]["message"])
        result: dict[str, Any] = response["result"]
        return result

    async def list_tools(
        ctx: ServerRequestContext[Any, Any], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult.model_validate(await answered(ctx, "tools/list", params))

    async def call_tool(
        ctx: ServerRequestContext[Any, Any], params: CallToolRequestParams
    ) -> CallToolResult:
        return CallToolResult.model_validate(await answered(ctx, "tools/call", params))

    server = Server("tests", on_list_tools=list_tools, on_call_tool=call_tool)
    app = server.streamable_http_app(
        stateless_http=True,
        # The requests keep the host of the server's URL.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )

    def http_client(
        headers: dict[str, str], timeout: httpx2.Timeout
    ) -> httpx2.AsyncClient:
        transport = httpx2.ASGITransport(app=app)
        return httpx2.AsyncClient(headers=headers, timeout=timeout, transport=transport)

    async with server.session_manager.run():
        yield McpToolbox(http_client_factory=http_client)


def out_of_reach() -> McpToolbox:
    """A toolbox whose every connection is refused."""

    def refused(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    return _mocked(refused)


def answering_status(status: int) -> McpToolbox:
    """A toolbox whose every request the server answers with an HTTP `status`."""
    return _mocked(lambda request: httpx2.Response(status))


def _mocked(handler: Callable[[httpx2.Request], httpx2.Response]) -> McpToolbox:
    def http_client(
        headers: dict[str, str], timeout: httpx2.Timeout
    ) -> httpx2.AsyncClient:
        transport = httpx2.MockTransport(handler)
        return httpx2.AsyncClient(headers=headers, timeout=timeout, transport=transport)

    return McpToolbox(http_client_factory=http_client)
