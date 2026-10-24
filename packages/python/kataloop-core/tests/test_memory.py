# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""What a turn keeps, resume, fork and forget (docs/specs/memory.md)."""

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from uni_llm_client import IncompleteResponseError, Usage

from kataloop_core import (
    AgentDefinition,
    CheckpointNotFoundError,
    Done,
    Kataloop,
    MemoryStore,
    SessionExistsError,
    SessionNotFoundError,
    TextDelta,
)
from support import (
    AGENT,
    PROMPT,
    FakeVendor,
    Reply,
    Tools,
    content,
    reply,
    run,
    text,
    thinking,
    tool_use,
)

ASKED = (
    thinking("The user wants the weather."),
    text("Let me check."),
    tool_use("toolu_01", "forecast", city="Paris"),
)

# The turn's messages as a document holds them (MSG-9).
PROMPT_MESSAGE = {
    "role": "user",
    "content": [{"type": "text", "text": PROMPT}],
    "vendor": None,
}
ASKED_MESSAGE = {
    "role": "assistant",
    "content": [
        {"type": "reasoning", "text": "The user wants the weather.", "redacted": False},
        {"type": "text", "text": "Let me check."},
        {
            "type": "tool_use",
            "id": "toolu_01",
            "name": "forecast",
            "input": {"city": "Paris"},
        },
    ],
    "vendor": {"kind": "anthropic", "content": content(*ASKED)},
}
RESULT_MESSAGE = {
    "role": "user",
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_01",
            "content": "Sunny in Paris.",
            "is_error": False,
        }
    ],
    "vendor": None,
}


def asks_the_forecast() -> Reply:
    return reply(*ASKED, stop_reason="tool_use", input_tokens=50, output_tokens=42)


def cut() -> Reply:
    return reply(text("Sunny in"), stop_reason="max_tokens")


async def answer(
    engine: Kataloop,
    vendor: FakeVendor,
    session: UUID,
    prompt: str = PROMPT,
    *,
    says: str = "Sunny.",
    **options: Any,
) -> Done:
    """The `Done` of a turn whose model answers at once."""
    vendor.serve(reply(text(says)))
    *_, done = await run(engine, session, prompt, **options)
    assert isinstance(done, Done)
    return done


async def fail_after_a_round(
    engine: Kataloop, vendor: FakeVendor, session: UUID, **options: Any
) -> None:
    """A turn that saves a tool round, then fails."""
    vendor.serve(asks_the_forecast(), cut())
    with pytest.raises(IncompleteResponseError):
        await run(engine, session, **options)


def user(value: str) -> dict[str, Any]:
    """A user message of text, as the vendor receives it."""
    return {"role": "user", "content": value}


async def test_a_checkpoint_holds_the_conversation_and_nothing_of_the_callers(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    vendor.serve(asks_the_forecast(), reply(text("Sunny.")))

    *_, done = await run(engine, session)

    assert isinstance(done, Done)
    memory = await store.checkpoint(session, done.checkpoint_id)
    assert memory == {
        "version": 1,
        "parent": None,
        "prompt": PROMPT,
        "text": "Sunny.",
        "messages": [
            PROMPT_MESSAGE,
            ASKED_MESSAGE,
            RESULT_MESSAGE,
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Sunny."}],
                "vendor": {"kind": "anthropic", "content": content(text("Sunny."))},
            },
        ],
    }
    # No system prompt, no tool, no model (ENG-10, MEM-3).
    kept = json.dumps(memory)
    assert AGENT.system_prompt not in kept
    assert "The forecast for a city." not in kept
    assert "test-model" not in kept
    assert await store.latest_checkpoint(session) == done.checkpoint_id
    assert await store.partial(session) is None


async def test_a_turn_from_a_checkpoint_replays_its_memory(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    first = await answer(engine, vendor, session)
    other = AgentDefinition("Answer at length.", AGENT.tool_servers)

    second = await answer(
        engine,
        vendor,
        session,
        "And tomorrow?",
        agent=other,
        checkpoint_id=first.checkpoint_id,
    )
    third = await answer(engine, vendor, session, "Hello.")

    request = vendor.requests[1]
    # The agent is the one given, never one stored (MEM-3).
    assert request["system"] == "Answer at length."
    assert request["messages"] == [
        user(PROMPT),
        {"role": "assistant", "content": content(text("Sunny."))},
        user("And tomorrow?"),
    ]
    memory = await store.checkpoint(session, second.checkpoint_id)
    assert memory is not None
    assert memory["parent"] == first.checkpoint_id
    # Without a checkpoint, a turn starts from nothing.
    assert vendor.requests[2]["messages"] == [user("Hello.")]
    ids = {first.checkpoint_id, second.checkpoint_id, third.checkpoint_id}
    assert len(ids) == 3
    assert await store.latest_checkpoint(session) == third.checkpoint_id


async def test_a_failed_turn_keeps_no_checkpoint_but_its_saved_rounds(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    await fail_after_a_round(engine, vendor, session)

    assert await store.latest_checkpoint(session) is None
    assert await store.partial(session) == {
        "version": 1,
        "parent": None,
        "prompt": PROMPT,
        "messages": [PROMPT_MESSAGE, ASKED_MESSAGE, RESULT_MESSAGE],
    }


async def test_resume_goes_on_from_the_saved_rounds(
    engine: Kataloop,
    store: MemoryStore,
    vendor: FakeVendor,
    tools: Tools,
    session: UUID,
) -> None:
    first = await answer(engine, vendor, session, "Hello.", says="Hi.")
    await fail_after_a_round(engine, vendor, session, checkpoint_id=first.checkpoint_id)
    vendor.serve(reply(text("Sunny."), input_tokens=80, output_tokens=3))

    events = await run(
        engine,
        session,
        "a prompt the engine does not compare",
        checkpoint_id=first.checkpoint_id,
        resume=True,
    )

    *deltas, done = events
    # The saved round is neither told again nor run again.
    assert deltas == [TextDelta("Sunny.")]
    assert isinstance(done, Done)
    assert done.text == "Sunny."
    # The calls of this run alone (MEM-6).
    assert done.usage == Usage(input_tokens=80, output_tokens=3)
    assert tools.calls == [("forecast", {"city": "Paris"})]
    assert vendor.requests[-1]["messages"] == [
        user("Hello."),
        {"role": "assistant", "content": content(text("Hi."))},
        user(PROMPT),
        {"role": "assistant", "content": content(*ASKED)},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_01",
                    "content": "Sunny in Paris.",
                }
            ],
        },
    ]
    memory = await store.checkpoint(session, done.checkpoint_id)
    assert memory is not None
    # It is the saved turn that finished.
    assert (memory["parent"], memory["prompt"]) == (first.checkpoint_id, PROMPT)
    assert memory["messages"][2:5] == [PROMPT_MESSAGE, ASKED_MESSAGE, RESULT_MESSAGE]
    assert await store.partial(session) is None


async def test_resume_goes_on_from_the_round_it_saved_last(
    engine: Kataloop, vendor: FakeVendor, tools: Tools, session: UUID
) -> None:
    await fail_after_a_round(engine, vendor, session)
    vendor.serve(
        reply(tool_use("toolu_02", "now"), stop_reason="tool_use"),
        reply(text("Noon."), stop_reason="max_tokens"),
    )
    with pytest.raises(IncompleteResponseError):
        await run(engine, session, resume=True)
    vendor.serve(reply(text("Sunny at noon.")))

    events = await run(engine, session, resume=True)

    assert events[:-1] == [TextDelta("Sunny at noon.")]
    assert [name for name, _ in tools.calls] == ["forecast", "now"]
    assert len(vendor.requests[-1]["messages"]) == 5


async def test_resume_of_a_finished_turn_gives_its_done_again(
    engine: Kataloop, vendor: FakeVendor, session: UUID
) -> None:
    first = await answer(engine, vendor, session, says="Hi.")
    assert await run(engine, session, resume=True) == [
        Done("Hi.", first.checkpoint_id, Usage())
    ]
    second = await answer(engine, vendor, session, checkpoint_id=first.checkpoint_id)

    again = await run(engine, session, checkpoint_id=first.checkpoint_id, resume=True)

    assert again == [Done("Sunny.", second.checkpoint_id, Usage())]
    # Nothing ran.
    assert len(vendor.requests) == 2


async def test_resume_with_nothing_saved_from_the_checkpoint_runs_the_prompt(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    first = await answer(engine, vendor, session, says="Hi.")
    second = await answer(engine, vendor, session, checkpoint_id=first.checkpoint_id)
    # A branch from the first checkpoint, saved and never finished.
    await fail_after_a_round(engine, vendor, session, checkpoint_id=first.checkpoint_id)

    # Neither the saved rounds nor the latest checkpoint began from the second.
    done = await answer(
        engine,
        vendor,
        session,
        "Hello.",
        checkpoint_id=second.checkpoint_id,
        resume=True,
    )

    assert vendor.requests[-1]["messages"] == [
        user(PROMPT),
        {"role": "assistant", "content": content(text("Hi."))},
        user(PROMPT),
        {"role": "assistant", "content": content(text("Sunny."))},
        user("Hello."),
    ]
    memory = await store.checkpoint(session, done.checkpoint_id)
    assert memory is not None
    assert memory["parent"] == second.checkpoint_id
    assert await store.partial(session) is None


async def test_a_turn_from_its_prompt_forgets_the_saved_rounds(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    await fail_after_a_round(engine, vendor, session)
    vendor.serve(reply(text("Hel"), stop_reason="max_tokens"))

    with pytest.raises(IncompleteResponseError):
        await run(engine, session, "Hello.")

    # The latest turn saved no round, so resume runs the prompt.
    assert await store.partial(session) is None
    done = await answer(engine, vendor, session, resume=True)
    assert vendor.requests[-1]["messages"] == [user(PROMPT)]
    assert done.usage == Usage(input_tokens=10, output_tokens=5)


async def test_a_fork_has_the_memory_up_to_its_checkpoint(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    first = await answer(engine, vendor, session, "One.", says="1")
    second = await answer(
        engine, vendor, session, "Two.", says="2", checkpoint_id=first.checkpoint_id
    )
    third = await answer(
        engine, vendor, session, "Three.", says="3", checkpoint_id=second.checkpoint_id
    )
    await fail_after_a_round(engine, vendor, session, checkpoint_id=third.checkpoint_id)
    fork = uuid4()

    await engine.fork(session, fork, checkpoint_id=second.checkpoint_id)

    assert await engine.exists(fork)
    assert await store.latest_checkpoint(fork) == second.checkpoint_id
    assert await store.partial(fork) is None
    # Earlier checkpoints stay valid in the fork; later ones are not its own.
    assert await store.checkpoint(fork, first.checkpoint_id) is not None
    with pytest.raises(CheckpointNotFoundError):
        await run(engine, fork, checkpoint_id=third.checkpoint_id)
    forked = await answer(
        engine, vendor, fork, "Four.", checkpoint_id=second.checkpoint_id
    )
    assert [m["content"] for m in vendor.requests[-1]["messages"]] == [
        "One.",
        content(text("1")),
        "Two.",
        content(text("2")),
        "Four.",
    ]
    # From then on, the two are independent.
    assert await store.checkpoint(session, forked.checkpoint_id) is None
    assert await store.latest_checkpoint(session) == third.checkpoint_id
    assert await store.partial(session) is not None


async def test_a_fork_is_refused_writing_nothing(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    done = await answer(engine, vendor, session)
    other = uuid4()
    await engine.create(other)
    target = uuid4()

    with pytest.raises(SessionNotFoundError):
        await engine.fork(uuid4(), target, checkpoint_id=done.checkpoint_id)
    # A checkpoint of another session (ENG-2).
    with pytest.raises(CheckpointNotFoundError):
        await engine.fork(other, target, checkpoint_id=done.checkpoint_id)
    with pytest.raises(SessionExistsError):
        await engine.fork(session, other, checkpoint_id=done.checkpoint_id)

    assert not await engine.exists(target)
    assert await store.latest_checkpoint(other) is None


async def test_forget_deletes_everything_kept_for_the_session(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    done = await answer(engine, vendor, session)
    await fail_after_a_round(engine, vendor, session, checkpoint_id=done.checkpoint_id)

    await engine.forget(session)
    await engine.forget(session)  # nothing happens when there is nothing

    assert not await engine.exists(session)
    with pytest.raises(SessionNotFoundError):
        await run(engine, session)
    await engine.create(session)
    assert await store.checkpoint(session, done.checkpoint_id) is None
    assert await store.partial(session) is None


async def test_memory_of_another_version_is_refused(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    await store.add_checkpoint(session, "old", {"version": 0, "messages": []})

    with pytest.raises(ValueError, match="version 0"):
        await run(engine, session, checkpoint_id="old")
    assert vendor.requests == []
