# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""One turn of the loop (docs/specs/turn.md)."""

import asyncio
import re
from typing import Any
from uuid import UUID

import pytest
from uni_llm_client import AsyncClient, IncompleteResponseError, Usage

from kataloop_core import (
    AgentDefinition,
    Done,
    Event,
    Kataloop,
    LocalToolbox,
    MemoryStore,
    ModelSpec,
    ReasoningDelta,
    RoundsExceededError,
    TextDelta,
    ToolCall,
    ToolResult,
    ToolServer,
    ToolSpec,
)
from support import (
    AGENT,
    MODEL,
    OFFERED,
    PROMPT,
    FakeVendor,
    Tools,
    content,
    reply,
    run,
    text,
    thinking,
    tool_use,
)


def results_message(*results: dict[str, Any]) -> dict[str, Any]:
    return {"role": "user", "content": list(results)}


def result(tool_use_id: str, output: str, *, is_error: bool = False) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": output,
    }
    if is_error:
        raw["is_error"] = True
    return raw


async def test_a_turn_streams_the_answer_and_ends_with_done(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    vendor.serve(
        reply(
            thinking("Paris, then."),
            text("Paris is", " the capital of France."),
            input_tokens=14,
            output_tokens=12,
        )
    )

    events = await run(engine, session, "What is the capital of France?")

    *deltas, done = events
    assert deltas == [
        ReasoningDelta("Paris, then."),
        TextDelta("Paris is"),
        TextDelta(" the capital of France."),
    ]
    assert isinstance(done, Done)
    assert done.text == "Paris is the capital of France."
    assert re.fullmatch("[0-9a-f]{32}", done.checkpoint_id)
    assert done.usage == Usage(input_tokens=14, output_tokens=12)
    # ENG-4: the memory holds the turn when Done comes.
    assert await store.checkpoint(session, done.checkpoint_id) is not None
    assert vendor.requests == [
        {
            "model": "test-model",
            "max_tokens": 16000,
            "system": "Answer briefly.",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "tools": OFFERED,
            "stream": True,
        }
    ]


async def test_the_model_spec_reaches_every_call(
    engine: Kataloop, vendor: FakeVendor, session: UUID
) -> None:
    vendor.serve(reply(text("Done.")))
    model = ModelSpec(MODEL.id, timeout=7.5, max_output_tokens=1000, effort="high")

    await run(engine, session, model=model)

    (body,) = vendor.requests
    assert body["max_tokens"] == 1000
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {"effort": "high"}
    assert vendor.timeouts == [{"connect": 7.5, "read": 7.5, "write": 7.5, "pool": 7.5}]


async def test_a_tool_turn_takes_two_rounds(
    engine: Kataloop, vendor: FakeVendor, tools: Tools, session: UUID
) -> None:
    asked = (
        thinking("The user wants the weather."),
        text("Let me check."),
        tool_use("toolu_01", "weather_forecast", city="Paris"),
    )
    vendor.serve(
        reply(*asked, stop_reason="tool_use", input_tokens=50, output_tokens=42),
        reply(text("Sunny."), input_tokens=80, output_tokens=3),
    )

    events = await run(engine, session)

    assert events[:-1] == [
        ReasoningDelta("The user wants the weather."),
        TextDelta("Let me check."),
        ToolCall("toolu_01", "weather_forecast", {"city": "Paris"}),
        ToolResult("toolu_01", "weather_forecast", "Sunny in Paris."),
        TextDelta("Sunny."),
    ]
    done = events[-1]
    assert isinstance(done, Done)
    assert done == Done(
        "Sunny.", done.checkpoint_id, Usage(input_tokens=130, output_tokens=45)
    )
    assert tools.calls == [("forecast", {"city": "Paris"})]
    first, second = vendor.requests
    assert first["tools"] == second["tools"] == OFFERED
    # The assistant message replays as the vendor sent it, signature included
    # (MSG-2); the results follow in one user message.
    assert second["messages"] == [
        {"role": "user", "content": PROMPT},
        {"role": "assistant", "content": content(*asked)},
        results_message(result("toolu_01", "Sunny in Paris.")),
    ]


async def test_the_calls_of_a_round_run_together(
    client: AsyncClient, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    # Each call waits for the other: run one after the other, neither answers.
    both = asyncio.Barrier(2)

    async def slow(arguments: Any) -> str:
        async with asyncio.timeout(5):
            await both.wait()
        await asyncio.sleep(0.01)
        return "slow"

    async def fast(arguments: Any) -> str:
        async with asyncio.timeout(5):
            await both.wait()
        return "fast"

    toolbox = LocalToolbox(
        {
            "t": [
                (ToolSpec("slow", "Slow.", {"type": "object"}), slow),
                (ToolSpec("fast", "Fast.", {"type": "object"}), fast),
            ]
        }
    )
    engine = Kataloop(client, store, toolbox)
    agent = AgentDefinition("Answer briefly.", (ToolServer("t", "local"),))
    calls = (tool_use("toolu_01", "t_slow"), tool_use("toolu_02", "t_fast"))
    vendor.serve(reply(*calls, stop_reason="tool_use"), reply(text("Both done.")))

    events = await run(engine, session, agent=agent)

    # The results come in the order of the calls, not of their answers.
    assert events[:4] == [
        ToolCall("toolu_01", "t_slow", {}),
        ToolCall("toolu_02", "t_fast", {}),
        ToolResult("toolu_01", "t_slow", "slow"),
        ToolResult("toolu_02", "t_fast", "fast"),
    ]
    assert vendor.requests[1]["messages"][2] == results_message(
        result("toolu_01", "slow"), result("toolu_02", "fast")
    )


async def test_a_call_that_fails_gets_an_error_result_and_the_turn_goes_on(
    engine: Kataloop, vendor: FakeVendor, tools: Tools, session: UUID
) -> None:
    calls = (
        tool_use("toolu_01", "weather_missing"),
        tool_use("toolu_02", "weather_secret"),
        tool_use("toolu_03", "weather_alerts", city="Paris"),
        tool_use("toolu_04", "clock_stall"),
        tool_use("toolu_05", "weather_report"),
    )
    vendor.serve(reply(*calls, stop_reason="tool_use"), reply(text("No luck.")))

    events = await run(engine, session)

    expected = [
        ("toolu_01", "weather_missing", "There is no tool named 'weather_missing'."),
        # Excluded by the agent: never offered, never run (ENG-11).
        ("toolu_02", "weather_secret", "There is no tool named 'weather_secret'."),
        # The type of the error, not its words.
        ("toolu_03", "weather_alerts", "The tool call failed: RuntimeError."),
        ("toolu_04", "clock_stall", "The tool call timed out after 0.05 seconds."),
        # An error the tool reports itself is its own answer.
        ("toolu_05", "weather_report", "No report today."),
    ]
    assert [e for e in events if isinstance(e, ToolResult)] == [
        ToolResult(call_id, name, output, is_error=True)
        for call_id, name, output in expected
    ]
    assert isinstance(events[-1], Done)
    assert [name for name, _ in tools.calls] == ["alerts", "stall", "report"]
    assert vendor.requests[1]["messages"][2] == results_message(
        *(result(call_id, output, is_error=True) for call_id, _, output in expected)
    )


async def test_a_paused_turn_is_sent_back_and_goes_on(
    engine: Kataloop, vendor: FakeVendor, session: UUID
) -> None:
    vendor.serve(
        reply(text("Searching."), stop_reason="pause_turn"),
        reply(text("Found it.")),
    )

    events = await run(engine, session)

    assert events[:-1] == [TextDelta("Searching."), TextDelta("Found it.")]
    assert isinstance(events[-1], Done)
    assert events[-1].text == "Found it."
    assert vendor.requests[1]["messages"] == [
        {"role": "user", "content": PROMPT},
        {"role": "assistant", "content": content(text("Searching."))},
    ]


async def test_a_cut_answer_raises(
    engine: Kataloop, vendor: FakeVendor, session: UUID
) -> None:
    vendor.serve(reply(text("Paris is the"), stop_reason="max_tokens"))
    received: list[Event] = []

    with pytest.raises(IncompleteResponseError):
        await run(engine, session, received=received)

    assert received == [TextDelta("Paris is the")]


async def test_rounds_are_bounded_by_the_timeout(
    engine: Kataloop, vendor: FakeVendor, session: UUID
) -> None:
    again = reply(tool_use("toolu_01", "clock_now"), stop_reason="tool_use")
    vendor.serve(again, again)
    received: list[Event] = []

    # 1.5 seconds: at most two model calls (ENG-13).
    with pytest.raises(RoundsExceededError):
        await run(engine, session, timeout=1.5, received=received)

    assert len(vendor.requests) == 2
    assert [type(e) for e in received] == [ToolCall, ToolResult] * 2


async def test_the_deadline_ends_the_turn(
    client: AsyncClient, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    async def hang(arguments: Any) -> str:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    toolbox = LocalToolbox({"t": [(ToolSpec("hang", "Hangs.", {}), hang)]})
    engine = Kataloop(client, store, toolbox)
    agent = AgentDefinition("Answer briefly.", (ToolServer("t", "local"),))
    vendor.serve(reply(tool_use("toolu_01", "t_hang"), stop_reason="tool_use"))
    loop = asyncio.get_running_loop()
    start = loop.time()

    with pytest.raises(TimeoutError):
        await run(engine, session, agent=agent, timeout=0.1)

    assert loop.time() - start < 1


async def test_the_deadline_does_not_cut_the_callers_handling(
    engine: Kataloop, vendor: FakeVendor, session: UUID
) -> None:
    vendor.serve(reply(tool_use("toolu_01", "clock_now"), stop_reason="tool_use"))
    turn = engine.stream(
        session, AGENT, PROMPT, model=MODEL, checkpoint_id=None, timeout=0.1
    )

    assert await anext(turn) == ToolCall("toolu_01", "clock_now", {})
    # Past the deadline while the event is with the caller: nothing interrupts it.
    await asyncio.sleep(0.2)
    # The turn ends at its next await.
    with pytest.raises(TimeoutError):
        await anext(turn)


@pytest.mark.parametrize("how", ["closed", "cancelled"])
async def test_a_cancelled_turn_closes_the_models_stream(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID, how: str
) -> None:
    # The vendor sends the first text and then nothing more.
    vendor.serve(reply(text("Paris"), text("never sent"), hang_after=4))
    turn = engine.stream(
        session, AGENT, PROMPT, model=MODEL, checkpoint_id=None, timeout=30
    )
    assert await anext(turn) == TextDelta("Paris")

    if how == "closed":
        await turn.aclose()  # type: ignore[attr-defined]
    else:
        waiting = asyncio.ensure_future(anext(turn))
        await asyncio.sleep(0.01)
        waiting.cancel()
        # Let through, never swallowed (ENG-5).
        with pytest.raises(asyncio.CancelledError):
            await waiting

    (stream,) = vendor.streams
    assert stream.closed
    assert not stream.ended
    assert await store.partial(session) is None
