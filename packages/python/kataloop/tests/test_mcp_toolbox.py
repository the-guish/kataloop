# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""`McpToolbox` against an MCP server of the SDK's, in the process
(docs/specs/tools.md). The HTTP tests in `tests` at the root cover it through
the engine."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
from mcp.server import Server, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INTERNAL_ERROR,
    CallToolRequestParams,
    CallToolResult,
    ContentBlock,
    ImageContent,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from kataloop import McpToolbox, ToolOutput, ToolServer, ToolSpec

CITY = {"type": "object", "properties": {"city": {"type": "string"}}}
NOTHING = {"type": "object"}
SERVER = ToolServer(
    "weather",
    "https://tools.example.com/mcp",
    headers={"authorization": "Bearer tool-key"},
    timeout=5,
)


class Tools:
    """The handlers of the server, recording each request with the credential it
    came with."""

    def __init__(self) -> None:
        self.received: list[tuple[str, str | None]] = []

    def _record(self, ctx: ServerRequestContext[Any, Any], method: str) -> None:
        assert ctx.request is not None
        self.received.append((method, ctx.request.headers.get("authorization")))

    async def list_tools(
        self, ctx: ServerRequestContext[Any, Any], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        self._record(ctx, "tools/list")
        if params is None or params.cursor is None:
            forecast = Tool(
                name="forecast", description="The forecast.", input_schema=CITY
            )
            return ListToolsResult(tools=[forecast], next_cursor="2")
        return ListToolsResult(tools=[Tool(name="report", input_schema=NOTHING)])

    async def call_tool(
        self, ctx: ServerRequestContext[Any, Any], params: CallToolRequestParams
    ) -> CallToolResult:
        self._record(ctx, "tools/call")
        match params.name, params.arguments:
            case "forecast", {"city": city}:
                parts: list[ContentBlock] = [
                    TextContent(text=f"Sunny in {city}."),
                    TextContent(text="Warm."),
                    ImageContent(data="iVBO", mime_type="image/png"),
                ]
                return CallToolResult(content=parts)
            case "report", _:
                return CallToolResult(
                    content=[TextContent(text="No report today.")], is_error=True
                )
            case "slow", _:
                await asyncio.sleep(30)
        raise MCPError(INTERNAL_ERROR, "the tool is down")


@asynccontextmanager
async def serving(tools: Tools) -> AsyncIterator[McpToolbox]:
    """A toolbox whose every request reaches the server in the process."""
    server = Server(
        "tests", on_list_tools=tools.list_tools, on_call_tool=tools.call_tool
    )
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


async def test_it_lists_every_page_of_a_servers_tools() -> None:
    tools = Tools()
    async with serving(tools) as toolbox:
        listed = await toolbox.tools(SERVER)

    assert listed == [
        ToolSpec("forecast", "The forecast.", CITY),
        ToolSpec("report", "", NOTHING),
    ]
    # Every request carries the server's headers.
    assert tools.received == [("tools/list", "Bearer tool-key")] * 2


async def test_a_call_gives_the_results_content_as_text() -> None:
    tools = Tools()
    async with serving(tools) as toolbox:
        answer = await toolbox.call(SERVER, "forecast", {"city": "Paris"})
        reported = await toolbox.call(SERVER, "report", {})

    image = '{"data":"iVBO","mimeType":"image/png","type":"image"}'
    assert answer == ToolOutput(f"Sunny in Paris.\nWarm.\n{image}")
    assert reported == ToolOutput("No report today.", is_error=True)
    # A call is a call, and no listing comes with it.
    assert tools.received == [("tools/call", "Bearer tool-key")] * 2


async def test_a_failure_raises_and_a_timeout_reads_as_one() -> None:
    tools = Tools()
    async with serving(tools) as toolbox:
        with pytest.raises(MCPError, match="the tool is down"):
            await toolbox.call(SERVER, "broken", {})
        slow = ToolServer("slow", SERVER.url, timeout=0.1)
        with pytest.raises(TimeoutError, match=r"'slow' did not answer within 0\.1 "):
            await toolbox.call(slow, "slow", {})


async def test_a_server_out_of_reach_raises_the_transports_error() -> None:
    def unreachable(handler: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=handler)

    def http_client(
        headers: dict[str, str], timeout: httpx2.Timeout
    ) -> httpx2.AsyncClient:
        transport = httpx2.MockTransport(unreachable)
        return httpx2.AsyncClient(headers=headers, timeout=timeout, transport=transport)

    toolbox = McpToolbox(http_client_factory=http_client)

    with pytest.raises(httpx2.ConnectError):
        await toolbox.tools(SERVER)
