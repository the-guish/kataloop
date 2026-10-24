# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""Serves the engine over HTTP for the language-agnostic tests in the repository root.

Run ``python tests/server.py --vendor-url URL --mcp-url URL``. Every vendor
request goes to the vendor URL and every MCP request to the MCP URL, each
keeping its path and ``Host`` header. The protocol, and the JSON forms of the
arguments, events and errors, are in ``tests/README.md`` at the repository root.

The server keeps one `Kataloop` for its lifetime, over a `MemoryStore` and an
`McpToolbox`, so that a case's steps share sessions and checkpoints. A turn runs
on a uni-llm-client client of its own, made from the turn's arguments as
uni-llm-client's test server makes one per call: the engine keeps nothing but
its store (ENG-10), so the `Kataloop` over that client, the same store and the
same toolbox is the same engine. Every operation runs on one event loop, in a
thread of its own.
"""

import argparse
import asyncio
import dataclasses
import json
import threading
import traceback
from collections.abc import Coroutine
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID

import httpx2
from uni_llm_client import (
    AsyncClient,
    AuthenticationError,
    IncompleteResponseError,
    ProviderConfig,
    ProviderError,
    RateLimitError,
    RefusalError,
    TransportError,
)

from kataloop import (
    AgentDefinition,
    CheckpointNotFoundError,
    Done,
    Event,
    Kataloop,
    McpToolbox,
    MemoryStore,
    ModelSpec,
    ReasoningDelta,
    RoundsExceededError,
    SessionExistsError,
    SessionNotFoundError,
    TextDelta,
    ToolCall,
    ToolResult,
    ToolServer,
)

OPERATIONS = ("setup", "create", "exists", "stream", "fork", "forget")

EVENT_TYPES: dict[type[Event], str] = {
    TextDelta: "text_delta",
    ReasoningDelta: "reasoning_delta",
    ToolCall: "tool_call",
    ToolResult: "tool_result",
    Done: "done",
}

# Most specific first: the contract's errors, then uni-llm-client's, whose
# subclasses of ProviderError come before it.
ERROR_TYPES: list[tuple[type[Exception], str]] = [
    (SessionExistsError, "session_exists"),
    (SessionNotFoundError, "session_not_found"),
    (CheckpointNotFoundError, "checkpoint_not_found"),
    (RoundsExceededError, "rounds_exceeded"),
    (TimeoutError, "timeout"),
    (ValueError, "invalid_argument"),
    (AuthenticationError, "authentication"),
    (RateLimitError, "rate_limit"),
    (RefusalError, "refusal"),
    (IncompleteResponseError, "incomplete_response"),
    (TransportError, "transport"),
    (ProviderError, "provider"),
]


class RedirectTransport(httpx2.AsyncHTTPTransport):
    """Sends every request to `target`, keeping its path, query and headers, the
    ``Host`` header among them."""

    def __init__(self, target: httpx2.URL) -> None:
        super().__init__()
        self.target = target

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        request.url = request.url.copy_with(
            scheme=self.target.scheme, host=self.target.host, port=self.target.port
        )
        return await super().handle_async_request(request)


def tool_server(data: dict[str, Any]) -> ToolServer:
    return ToolServer(**{**data, "exclude": tuple(data.get("exclude", ()))})


def agent_definition(data: dict[str, Any]) -> AgentDefinition:
    servers = tuple(tool_server(server) for server in data.get("tool_servers", ()))
    return AgentDefinition(data["system_prompt"], servers)


def event_json(event: Event) -> dict[str, Any]:
    """The event's JSON form: its type and every field, defaults included."""
    return {"type": EVENT_TYPES[type(event)], **dataclasses.asdict(event)}


def error_json(error: Exception) -> dict[str, Any]:
    """The reply's `error` for an error of the contract or of uni-llm-client; any
    other error is raised again."""
    for cls, name in ERROR_TYPES:
        if isinstance(error, cls):
            return {"type": name, "message": str(error)}
    raise error


class Service:
    """The engine's operations, over the server's one store and toolbox."""

    def __init__(self, vendor_url: httpx2.URL, mcp_url: httpx2.URL) -> None:
        self.vendor_url = vendor_url
        self.store = MemoryStore()
        self.toolbox = McpToolbox(
            http_client_factory=lambda headers, timeout: httpx2.AsyncClient(
                headers=headers,
                timeout=timeout,
                transport=RedirectTransport(mcp_url),
                # A proxy from the environment would bypass the transport.
                trust_env=False,
            )
        )
        # Its client is never used: the operations other than a turn never reach
        # a vendor.
        self.engine = Kataloop(AsyncClient(), self.store, self.toolbox)
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def run(self, operation: str, args: dict[str, Any]) -> dict[str, Any]:
        """The reply to an operation, run on the server's event loop."""
        if operation == "stream":
            return self._on_loop(self.stream(args))
        try:
            return self._on_loop(self.call(operation, args))
        except Exception as error:
            return {"error": error_json(error)}

    def _on_loop(self, work: Coroutine[Any, Any, dict[str, Any]]) -> dict[str, Any]:
        return asyncio.run_coroutine_threadsafe(work, self.loop).result()

    async def call(self, operation: str, args: dict[str, Any]) -> dict[str, Any]:
        match operation:
            case "setup":
                await self.engine.setup()
            case "create":
                await self.engine.create(UUID(args["session_id"]))
            case "exists":
                return {"exists": await self.engine.exists(UUID(args["session_id"]))}
            case "fork":
                await self.engine.fork(
                    UUID(args["source_id"]),
                    UUID(args["target_id"]),
                    checkpoint_id=args["checkpoint_id"],
                )
            case "forget":
                await self.engine.forget(UUID(args["session_id"]))
        return {}

    async def stream(self, args: dict[str, Any]) -> dict[str, Any]:
        """The events of a whole turn, and the error that ended it, if one did."""
        events: list[dict[str, Any]] = []
        http_client = httpx2.AsyncClient(
            transport=RedirectTransport(self.vendor_url), trust_env=False
        )
        try:
            client = AsyncClient(http_client=http_client, **client_kwargs(args))
        except Exception as error:
            # A refused configuration is an error like any other.
            await http_client.aclose()
            return {"events": events, "error": error_json(error)}
        async with client:
            engine = Kataloop(client, self.store, self.toolbox)
            try:
                turn = engine.stream(
                    UUID(args["session_id"]),
                    agent_definition(args["agent"]),
                    args["prompt"],
                    model=ModelSpec(**args["model"]),
                    checkpoint_id=args.get("checkpoint_id"),
                    timeout=args["timeout"],
                    resume=args.get("resume", False),
                )
                async for event in turn:
                    events.append(event_json(event))
            except Exception as error:
                return {"events": events, "error": error_json(error)}
        return {"events": events}


def client_kwargs(args: dict[str, Any]) -> dict[str, Any]:
    """The arguments of the turn's client: `api_keys`, `providers`, and
    `max_retries` when given."""
    providers = args.get("providers") or {}
    kwargs: dict[str, Any] = {
        "api_keys": args.get("api_keys"),
        "providers": {
            name: ProviderConfig(**config) for name, config in providers.items()
        },
    }
    if "max_retries" in args:
        kwargs["max_retries"] = args["max_retries"]
    return kwargs


def make_handler(service: Service) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            operation = self.path.removeprefix("/")
            if operation not in OPERATIONS:
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            args = json.loads(self.rfile.read(length))
            status = 200
            try:
                reply = service.run(operation, args)
            except Exception:
                # A bug in this server or the engine: show it to the runner.
                status, reply = 500, {"traceback": traceback.format_exc()}
            body = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-url", required=True)
    parser.add_argument("--mcp-url", required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    service = Service(httpx2.URL(args.vendor_url), httpx2.URL(args.mcp_url))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service))
    host, port = server.server_address[:2]
    print(f"listening on http://{host!s}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
