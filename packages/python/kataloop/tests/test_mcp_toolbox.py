# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""`McpToolbox` against an MCP server of the SDK's, in the process
(docs/specs/tools.md), on the major the environment holds: `serving_mcp1` or
`serving_mcp2` serves the same answers on each. The HTTP tests in `tests` at
the root cover it through the engine."""

import asyncio
from importlib.metadata import version
from typing import Any

import pytest

from kataloop import McpHttpClient, McpToolbox, ToolOutput, ToolServer, ToolSpec
from kataloop._mcp_toolbox import MCP_2

if MCP_2:
    from serving_mcp2 import (
        ConnectError,
        ServerError,
        answering_status,
        out_of_reach,
        serving,
    )
else:
    from serving_mcp1 import (
        ConnectError,
        ServerError,
        answering_status,
        out_of_reach,
        serving,
    )

CITY = {"type": "object", "properties": {"city": {"type": "string"}}}
NOTHING = {"type": "object"}
INTERNAL_ERROR = -32603
SERVER = ToolServer(
    "weather",
    "https://tools.example.com/mcp",
    headers={"authorization": "Bearer tool-key"},
    timeout=5,
)


class Tools:
    """The server's answers, in MCP's JSON form, recording each request with the
    credential it came with."""

    def __init__(self) -> None:
        self.received: list[tuple[str, str | None]] = []

    async def answer(
        self, method: str, params: dict[str, Any], authorization: str | None
    ) -> dict[str, Any]:
        self.received.append((method, authorization))
        match method, params:
            case "tools/list", {"cursor": "2"}:
                last = {"name": "report", "inputSchema": NOTHING}
                return {"result": {"tools": [last]}}
            case "tools/list", _:
                forecast = {
                    "name": "forecast",
                    "description": "The forecast.",
                    "inputSchema": CITY,
                }
                return {"result": {"tools": [forecast], "nextCursor": "2"}}
            case "tools/call", {"name": "forecast", "arguments": {"city": city}}:
                parts = [
                    {"type": "text", "text": f"Sunny in {city}."},
                    {"type": "text", "text": "Warm."},
                    {"type": "image", "data": "iVBO", "mimeType": "image/png"},
                ]
                return {"result": {"content": parts}}
            case "tools/call", {"name": "report"}:
                report = {"type": "text", "text": "No report today."}
                return {"result": {"content": [report], "isError": True}}
            case "tools/call", {"name": "slow"}:
                await asyncio.sleep(30)
        return {"error": {"code": INTERNAL_ERROR, "message": "the tool is down"}}


def test_it_runs_on_the_major_the_environment_holds() -> None:
    major = version("mcp").partition(".")[0]
    stack = {"1": "httpx", "2": "httpx2"}[major]

    assert McpToolbox.__module__ == f"kataloop._mcp{major}"
    assert McpHttpClient.__module__.partition(".")[0] == stack


async def test_it_lists_every_page_of_a_servers_tools() -> None:
    tools = Tools()
    async with serving(tools.answer) as toolbox:
        listed = await toolbox.tools(SERVER)

    assert listed == [
        ToolSpec("forecast", "The forecast.", CITY),
        ToolSpec("report", "", NOTHING),
    ]
    # Every request carries the server's headers.
    assert tools.received == [("tools/list", "Bearer tool-key")] * 2


async def test_a_call_gives_the_results_content_as_text() -> None:
    tools = Tools()
    async with serving(tools.answer) as toolbox:
        answer = await toolbox.call(SERVER, "forecast", {"city": "Paris"})
        reported = await toolbox.call(SERVER, "report", {})

    image = '{"data":"iVBO","mimeType":"image/png","type":"image"}'
    assert answer == ToolOutput(f"Sunny in Paris.\nWarm.\n{image}")
    assert reported == ToolOutput("No report today.", is_error=True)
    # A call is a call, and no listing comes with it.
    assert tools.received == [("tools/call", "Bearer tool-key")] * 2


async def test_a_failure_raises_and_a_timeout_reads_as_one() -> None:
    async with serving(Tools().answer) as toolbox:
        with pytest.raises(ServerError, match="the tool is down") as failed:
            await toolbox.call(SERVER, "broken", {})
        slow = ToolServer("slow", SERVER.url, timeout=0.1)
        with pytest.raises(TimeoutError, match=r"'slow' did not answer within 0\.1 "):
            await toolbox.call(slow, "slow", {})

    # The engine names the error to the model by its type, alike on each major.
    assert type(failed.value).__name__ == "MCPError"


async def test_a_server_out_of_reach_raises_the_transports_error() -> None:
    with pytest.raises(ConnectError):
        await out_of_reach().tools(SERVER)


async def test_an_http_error_status_is_an_error_response_of_the_server() -> None:
    with pytest.raises(ServerError) as failed:
        await answering_status(401).call(SERVER, "forecast", {"city": "Paris"})

    assert type(failed.value).__name__ == "MCPError"
