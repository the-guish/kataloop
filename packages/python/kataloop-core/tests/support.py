# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""A fake Anthropic for the loop's tests, and the agent and tools they run.

The fake serves the Messages API's server-sent events in the shapes of
uni-llm-client's fixtures, built by `reply` from the content blocks the model
returns, and records the body of each request. The engine reaches it through a
real `AsyncClient` over `httpx2.MockTransport`, so that a test asserts what the
vendor receives.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx2

from kataloop_core import (
    AgentDefinition,
    Engine,
    Event,
    LocalTool,
    ModelSpec,
    ToolOutput,
    ToolServer,
    ToolSpec,
)

MODEL = ModelSpec("anthropic/test-model")
"""A model uni-llm-client does not know, so that its request is the plain one."""

PROMPT = "What is the weather in Paris?"

WEATHER = ToolServer("weather", "local", exclude=("secret",))
CLOCK = ToolServer("clock", "local", timeout=0.05)
AGENT = AgentDefinition("Answer briefly.", (WEATHER, CLOCK))

CITY = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
}
NOTHING: dict[str, Any] = {"type": "object", "properties": {}}

OFFERED = [
    {
        "name": "forecast",
        "description": "The forecast for a city.",
        "input_schema": CITY,
    },
    {"name": "alerts", "description": "Weather alerts.", "input_schema": CITY},
    {
        "name": "report",
        "description": "Today's report.",
        "input_schema": NOTHING,
    },
    {"name": "now", "description": "The time.", "input_schema": NOTHING},
    {"name": "stall", "description": "Never answers.", "input_schema": NOTHING},
]
"""The tools the agent's servers offer, as the vendor receives them."""


@dataclass
class Tools:
    """The tools of the agent's servers, recording each call they get."""

    calls: list[tuple[str, Mapping[str, Any]]] = field(default_factory=list)

    def servers(self) -> dict[str, list[tuple[ToolSpec, LocalTool]]]:
        return {
            "weather": [
                (ToolSpec("forecast", "The forecast for a city.", CITY), self.forecast),
                (ToolSpec("alerts", "Weather alerts.", CITY), self.alerts),
                (ToolSpec("report", "Today's report.", NOTHING), self.report),
                (ToolSpec("secret", "Excluded by the agent.", NOTHING), self.secret),
            ],
            "clock": [
                (ToolSpec("now", "The time.", NOTHING), self.now),
                (ToolSpec("stall", "Never answers.", NOTHING), self.stall),
            ],
        }

    async def forecast(self, arguments: Mapping[str, Any]) -> str:
        self.calls.append(("forecast", arguments))
        return f"Sunny in {arguments['city']}."

    async def alerts(self, arguments: Mapping[str, Any]) -> str:
        self.calls.append(("alerts", arguments))
        raise RuntimeError("the alerts service is down")

    async def report(self, arguments: Mapping[str, Any]) -> ToolOutput:
        self.calls.append(("report", arguments))
        return ToolOutput("No report today.", is_error=True)

    async def secret(self, arguments: Mapping[str, Any]) -> str:
        self.calls.append(("secret", arguments))
        return "The agent was not given this tool."

    async def now(self, arguments: Mapping[str, Any]) -> str:
        self.calls.append(("now", arguments))
        return "Noon."

    async def stall(self, arguments: Mapping[str, Any]) -> str:
        self.calls.append(("stall", arguments))
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


# The content blocks of a reply, as the vendor sends them whole.


def text(*pieces: str) -> dict[str, Any]:
    """A text block, streamed in `pieces`."""
    return {"type": "text", "text": "".join(pieces), "pieces": pieces}


def thinking(value: str, signature: str = "sig_01") -> dict[str, Any]:
    return {"type": "thinking", "thinking": value, "signature": signature}


def tool_use(id: str, name: str, **arguments: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": id, "name": name, "input": arguments}


def content(*blocks: dict[str, Any]) -> list[dict[str, Any]]:
    """The blocks as the vendor's message holds them, and as they replay."""
    return [{k: v for k, v in b.items() if k != "pieces"} for b in blocks]


@dataclass
class Reply:
    """A streamed response; with `hang_after`, the vendor sends that many events
    and then nothing more."""

    events: list[dict[str, Any]]
    hang_after: int | None = None


def reply(
    *blocks: dict[str, Any],
    stop_reason: str = "end_turn",
    input_tokens: int = 10,
    output_tokens: int = 5,
    hang_after: int | None = None,
) -> Reply:
    """The events of a streamed message of `blocks`, as Anthropic sends them."""
    events: list[dict[str, Any]] = [
        {
            "event": "message_start",
            "data": {
                "type": "message_start",
                "message": {
                    "id": "msg_01",
                    "type": "message",
                    "role": "assistant",
                    "model": "test-model",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": input_tokens, "output_tokens": 1},
                },
            },
        }
    ]
    for index, block in enumerate(blocks):
        events.append(_block_event("content_block_start", index, _start(block)))
        for delta in _deltas(block):
            events.append(_block_event("content_block_delta", index, delta))
        events.append(_block_event("content_block_stop", index, None))
    events.append(
        {
            "event": "message_delta",
            "data": {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": output_tokens},
            },
        }
    )
    events.append({"event": "message_stop", "data": {"type": "message_stop"}})
    return Reply(events, hang_after)


def _block_event(kind: str, index: int, payload: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"type": kind, "index": index}
    if kind == "content_block_start":
        data["content_block"] = payload
    elif kind == "content_block_delta":
        data["delta"] = payload
    return {"event": kind, "data": data}


def _start(block: dict[str, Any]) -> dict[str, Any]:
    match block["type"]:
        case "text":
            return {"type": "text", "text": ""}
        case "thinking":
            return {"type": "thinking", "thinking": "", "signature": ""}
        case _:
            return {**block, "input": {}}


def _deltas(block: dict[str, Any]) -> list[dict[str, Any]]:
    match block["type"]:
        case "text":
            return [{"type": "text_delta", "text": piece} for piece in block["pieces"]]
        case "thinking":
            return [
                {"type": "thinking_delta", "thinking": block["thinking"]},
                {"type": "signature_delta", "signature": block["signature"]},
            ]
        case _:
            arguments = json.dumps(block["input"])
            half = len(arguments) // 2
            return [
                {"type": "input_json_delta", "partial_json": arguments[:half]},
                {"type": "input_json_delta", "partial_json": arguments[half:]},
            ]


class EventStream(httpx2.AsyncByteStream):
    """The body of a streamed response, one event per chunk, that records whether
    it was closed."""

    def __init__(self, reply: Reply) -> None:
        self.closed = False
        self.ended = False
        self._reply = reply

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for index, event in enumerate(self._reply.events):
            if index == self._reply.hang_after:
                await asyncio.Event().wait()
            frame = f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
            yield frame.encode()
        self.ended = True

    async def aclose(self) -> None:
        self.closed = True


class FakeVendor:
    """Serves the replies it was given, in order, and records each request."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.timeouts: list[Any] = []
        self.streams: list[EventStream] = []
        self._replies: list[Reply] = []

    def serve(self, *replies: Reply) -> None:
        self._replies.extend(replies)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(json.loads(request.content))
        self.timeouts.append(request.extensions.get("timeout"))
        if not self._replies:
            raise AssertionError("The vendor got a request it has no reply for")
        stream = EventStream(self._replies.pop(0))
        self.streams.append(stream)
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, stream=stream
        )


async def run(
    engine: Engine,
    session_id: UUID,
    prompt: str = PROMPT,
    *,
    agent: AgentDefinition = AGENT,
    model: ModelSpec = MODEL,
    checkpoint_id: str | None = None,
    timeout: float = 30.0,
    resume: bool = False,
    received: list[Event] | None = None,
) -> list[Event]:
    """The events of a turn; each is also appended to `received` as it comes, so
    that a test sees those before an error."""
    events = [] if received is None else received
    turn = engine.stream(
        session_id,
        agent,
        prompt,
        model=model,
        checkpoint_id=checkpoint_id,
        timeout=timeout,
        resume=resume,
    )
    async for event in turn:
        events.append(event)
    return events
