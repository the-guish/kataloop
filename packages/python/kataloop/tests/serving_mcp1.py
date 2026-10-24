# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""An MCP server of mcp 1's in the process, and the toolbox that reaches it
(test_mcp_toolbox.py)."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import McpError
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    ErrorData,
    ListToolsRequest,
    ListToolsResult,
    PaginatedRequestParams,
    ServerResult,
)
from starlette.types import Receive, Scope, Send

from kataloop import McpToolbox

Answer = Callable[[str, dict[str, Any], str | None], Awaitable[dict[str, Any]]]
"""The server's answer to a request, from its method, its params and the
credential it came with: the `result`, or the JSON-RPC `error`, in MCP's JSON
form."""

ServerError = McpError
"""What the SDK raises for an error response of the server."""

ConnectError = httpx.ConnectError
"""The error of a server out of reach."""


@asynccontextmanager
async def serving(answer: Answer) -> AsyncIterator[McpToolbox]:
    """A toolbox whose every request reaches the server in the process."""
    server: Server[Any, Any] = Server("tests")

    async def answered(
        method: str, params: PaginatedRequestParams | CallToolRequestParams | None
    ) -> dict[str, Any]:
        request = server.request_context.request
        assert request is not None
        sent = (
            {}
            if params is None
            else params.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        response = await answer(method, sent, request.headers.get("authorization"))
        if "error" in response:
            raise McpError(ErrorData.model_validate(response["error"]))
        result: dict[str, Any] = response["result"]
        return result

    async def list_tools(request: ListToolsRequest) -> ServerResult:
        result = await answered("tools/list", request.params)
        return ServerResult(ListToolsResult.model_validate(result))

    async def call_tool(request: CallToolRequest) -> ServerResult:
        result = await answered("tools/call", request.params)
        return ServerResult(CallToolResult.model_validate(result))

    # The handlers themselves: the SDK's decorators would turn an error into a
    # result that reports it, and the server is to answer with the error.
    server.request_handlers[ListToolsRequest] = list_tools
    server.request_handlers[CallToolRequest] = call_tool
    manager = StreamableHTTPSessionManager(
        server,
        stateless=True,
        # The requests keep the host of the server's URL.
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await manager.handle_request(scope, receive, send)

    def http_client(
        headers: dict[str, str], timeout: httpx.Timeout
    ) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(headers=headers, timeout=timeout, transport=transport)

    async with manager.run():
        yield McpToolbox(http_client_factory=http_client)


def out_of_reach() -> McpToolbox:
    """A toolbox whose every connection is refused."""

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    return _mocked(refused)


def answering_status(status: int) -> McpToolbox:
    """A toolbox whose every request the server answers with an HTTP `status`."""
    return _mocked(lambda request: httpx.Response(status))


def _mocked(handler: Callable[[httpx.Request], httpx.Response]) -> McpToolbox:
    def http_client(
        headers: dict[str, str], timeout: httpx.Timeout
    ) -> httpx.AsyncClient:
        transport = httpx.MockTransport(handler)
        return httpx.AsyncClient(headers=headers, timeout=timeout, transport=transport)

    return McpToolbox(http_client_factory=http_client)
