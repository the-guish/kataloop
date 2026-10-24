# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""Runs every case against every implementation listed in implementations.json.

The mock vendor and the mock MCP server record each request they receive and
serve the responses a case gives them. Each implementation's test server sends
its vendor requests and its MCP requests there, keeping their ``Host`` header.
"""

import asyncio
import json
import os
import re
import select
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from mcp.server import Server, ServerRequestContext
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INTERNAL_ERROR,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
)

Params = PaginatedRequestParams | CallToolRequestParams | None

HERE = Path(__file__).parent
REPO = HERE.parent
IMPLEMENTATIONS: dict[str, dict[str, Any]] = json.loads(
    (HERE / "implementations.json").read_text()
)
STARTUP_TIMEOUT = 120.0  # The first `uv run` may install the environment.

# Calls to 127.0.0.1 must not go through a proxy from the environment.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass
class VendorCall:
    method: str
    url: str
    headers: dict[str, str]
    json: Any


class MockVendor:
    """Records the requests it receives and serves the responses it is given."""

    def __init__(self) -> None:
        self.calls: list[VendorCall] = []
        self._responses: list[dict[str, Any]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}"

    def serve(self, responses: list[dict[str, Any]]) -> None:
        self.calls.clear()
        self._responses = list(responses)

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        vendor = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                headers = {k.lower(): v for k, v in self.headers.items()}
                vendor.calls.append(
                    VendorCall(
                        method=self.command,
                        # Implementations keep the vendor's Host header and path.
                        url=f"https://{headers.get('host')}{self.path}",
                        headers=headers,
                        json=json.loads(body) if body else None,
                    )
                )
                response = vendor.next_response()
                # A response can wait, as a slow vendor does, so that a turn
                # reaches its deadline.
                time.sleep(response.get("delay", 0))
                if response.get("disconnect"):
                    # Close the connection without a response, as a network fault.
                    self.close_connection = True
                    return
                content_type, reply = encoded(response)
                try:
                    self.send_response(response["status"])
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(reply)))
                    for name, value in response.get("headers", {}).items():
                        self.send_header(name, value)
                    self.end_headers()
                    self.wfile.write(reply)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # The client stopped waiting for a delayed response.

            def log_message(self, format: str, *args: Any) -> None:
                pass

        return Handler

    def next_response(self) -> dict[str, Any]:
        if self._responses:
            return self._responses.pop(0)
        return {"status": 500, "body": {"error": "no response left"}}


def encoded(response: dict[str, Any]) -> tuple[str, bytes]:
    """The content type and body of a vendor response payload."""
    if "events" in response:
        return "text/event-stream", sse(response["events"])
    return "application/json", json.dumps(response["body"]).encode()


def sse(events: list[dict[str, Any]]) -> bytes:
    """Server-sent events: each has a `data`, an optional `event`, or a `comment`."""
    frames = []
    for event in events:
        if "comment" in event:
            frames.append(f": {event['comment']}\n\n")
            continue
        data = event["data"]
        text = data if isinstance(data, str) else json.dumps(data)
        name = f"event: {event['event']}\n" if "event" in event else ""
        frames.append(f"{name}data: {text}\n\n")
    return "".join(frames).encode()


class MockMcp:
    """An MCP server, the SDK's low-level one over streamable HTTP, scripted step by
    step.

    It answers every ``tools/list`` and ``tools/call`` it receives with the
    response of the first exchange it was given whose request has the same
    method, URL and params, and records each of them. The tool servers of a case
    are told apart by their URLs, whose host the implementations keep.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._exchanges: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self._lock = threading.Lock()
        server = Server(
            "kataloop-tests",
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )
        app = server.streamable_http_app(
            stateless_http=True,
            # The requests keep the Host header of the tool server's URL.
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            ),
        )
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        config = uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=1)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, kwargs={"sockets": [self._socket]}, daemon=True
        )
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("The mock MCP server did not start")
            time.sleep(0.01)

    @property
    def url(self) -> str:
        host, port = self._socket.getsockname()[:2]
        return f"http://{host!s}:{port}"

    def serve(self, exchanges: list[tuple[dict[str, Any], dict[str, Any]]]) -> None:
        """Answer with these (request, response) pairs, each once."""
        with self._lock:
            self.calls.clear()
            self._exchanges = list(exchanges)

    def close(self) -> None:
        self._server.should_exit = True
        self._thread.join(10)

    async def _list_tools(
        self, ctx: ServerRequestContext[Any, Any], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        result = await self._answer(ctx, "tools/list", params)
        return ListToolsResult.model_validate(result)

    async def _call_tool(
        self, ctx: ServerRequestContext[Any, Any], params: CallToolRequestParams
    ) -> CallToolResult:
        result = await self._answer(ctx, "tools/call", params)
        return CallToolResult.model_validate(result)

    async def _answer(
        self,
        ctx: ServerRequestContext[Any, Any],
        method: str,
        params: Params,
    ) -> dict[str, Any]:
        request = ctx.request
        assert request is not None, "the request comes over HTTP"
        headers = {k.lower(): v for k, v in request.headers.items()}
        call = {
            "method": method,
            "url": f"https://{headers.get('host')}{request.url.path}",
            "headers": headers,
            "params": params_json(params),
        }
        with self._lock:
            self.calls.append(call)
            response = self._take(call)
        if response is None:
            raise MCPError(INTERNAL_ERROR, "No response left for this request")
        # A response can wait, as a slow tool does, so that a call times out.
        await asyncio.sleep(response.get("delay", 0))
        if "error" in response:
            error = response["error"]
            raise MCPError(error["code"], error["message"])
        result: dict[str, Any] = response["result"]
        return result

    def _take(self, call: dict[str, Any]) -> dict[str, Any] | None:
        for index, (request, response) in enumerate(self._exchanges):
            if same_request(request, call):
                del self._exchanges[index]
                return response
        return None


def params_json(params: Params) -> dict[str, Any]:
    """The request's params in MCP's JSON form, without `_meta`, which carries
    what a client's SDK adds of its own."""
    if params is None:
        return {}
    data = params.model_dump(by_alias=True, mode="json", exclude_none=True)
    data.pop("_meta", None)
    return data


def same_request(expected: dict[str, Any], call: dict[str, Any]) -> bool:
    return all(expected[key] == call[key] for key in ("method", "url", "params"))


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--impl",
        action="append",
        choices=sorted(IMPLEMENTATIONS),
        help="Implementation to test; repeat for several. Default: all.",
    )
    parser.addoption(
        "--package",
        action="append",
        choices=sorted({spec["package"] for spec in IMPLEMENTATIONS.values()}),
        help="Test every implementation of a package; repeat for several.",
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "implementation" in metafunc.fixturenames:
        names = metafunc.config.getoption("impl") or []
        for package in metafunc.config.getoption("package") or []:
            names += [n for n, s in IMPLEMENTATIONS.items() if s["package"] == package]
        names = sorted(set(names)) or sorted(IMPLEMENTATIONS)
        metafunc.parametrize("implementation", names, indirect=True, scope="session")


@pytest.fixture(scope="session")
def mock_vendor() -> Iterator[MockVendor]:
    vendor = MockVendor()
    yield vendor
    vendor.close()


@pytest.fixture
def vendor(mock_vendor: MockVendor) -> MockVendor:
    mock_vendor.serve([])
    return mock_vendor


@pytest.fixture(scope="session")
def mock_mcp() -> Iterator[MockMcp]:
    mcp = MockMcp()
    yield mcp
    mcp.close()


@pytest.fixture
def mcp(mock_mcp: MockMcp) -> MockMcp:
    mock_mcp.serve([])
    return mock_mcp


@pytest.fixture(scope="session")
def implementation(
    request: pytest.FixtureRequest, mock_vendor: MockVendor, mock_mcp: MockMcp
) -> Iterator[str]:
    """Start the implementation's test server and return its URL."""
    spec = IMPLEMENTATIONS[request.param]
    # Real API keys stay out of reach: the cases pass the keys they need. The
    # server runs in its own environment, not in this one, with the variables
    # its spec sets.
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.endswith("_API_KEY") and k != "VIRTUAL_ENV"
    }
    env.update(spec.get("env", {}))
    process = subprocess.Popen(
        [*spec["command"], "--vendor-url", mock_vendor.url, "--mcp-url", mock_mcp.url],
        cwd=REPO / spec["cwd"],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    try:
        ready, _, _ = select.select([process.stdout], [], [], STARTUP_TIMEOUT)
        line = process.stdout.readline() if ready else ""
        match = re.fullmatch(r"listening on (\S+)\n", line)
        if not match:
            pytest.fail(f"{request.param} did not start; first line: {line!r}")
        yield match[1]
    finally:
        process.terminate()
        process.wait(timeout=10)


def call(server_url: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """POST `args` to the test server's `/name` and return its reply."""
    request = urllib.request.Request(
        f"{server_url}/{name}",
        data=json.dumps(args).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with _opener.open(request) as response:
            reply: dict[str, Any] = json.load(response)
    except urllib.error.HTTPError as error:
        pytest.fail(f"The test server failed:\n{error.read().decode()}")
    return reply
