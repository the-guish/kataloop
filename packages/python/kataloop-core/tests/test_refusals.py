# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""What a turn refuses, before anything is sent or written (ENG-1, ENG-2)."""

import math
from uuid import UUID, uuid4

import pytest
from uni_llm_client import AsyncClient

from kataloop_core import (
    AgentDefinition,
    CheckpointNotFoundError,
    Done,
    Kataloop,
    LocalToolbox,
    MemoryStore,
    SessionExistsError,
    SessionNotFoundError,
    ToolServer,
    ToolSpec,
)
from support import AGENT, MODEL, PROMPT, FakeVendor, reply, run, text


async def test_a_turn_runs_nothing_before_its_first_iteration(
    engine: Kataloop, vendor: FakeVendor
) -> None:
    turn = engine.stream(
        uuid4(), AGENT, PROMPT, model=MODEL, checkpoint_id=None, timeout=30
    )

    # The refusal comes from the iterator (ENG-1).
    with pytest.raises(SessionNotFoundError):
        await anext(turn)
    assert vendor.requests == []


async def test_a_session_is_created_once(engine: Kataloop, session: UUID) -> None:
    with pytest.raises(SessionExistsError):
        await engine.create(session)
    assert await engine.exists(session)
    assert not await engine.exists(uuid4())


async def test_a_checkpoint_the_session_does_not_hold_is_refused(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    other = uuid4()
    await engine.create(other)
    vendor.serve(reply(text("Paris.")))
    (*_, done) = await run(engine, other)
    assert isinstance(done, Done)

    for checkpoint_id in ["0" * 32, done.checkpoint_id]:
        with pytest.raises(CheckpointNotFoundError):
            await run(engine, session, checkpoint_id=checkpoint_id)

    assert len(vendor.requests) == 1
    assert await store.partial(session) is None


@pytest.mark.parametrize("timeout", [0, -1, math.inf, math.nan])
async def test_a_timeout_that_is_not_positive_seconds_is_refused(
    engine: Kataloop, vendor: FakeVendor, session: UUID, timeout: float
) -> None:
    with pytest.raises(ValueError, match="timeout"):
        await run(engine, session, timeout=timeout)
    assert vendor.requests == []


async def test_two_tools_of_one_name_are_refused(
    client: AsyncClient, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    async def tool(arguments: object) -> str:
        return ""

    toolbox = LocalToolbox(
        {
            "a": [(ToolSpec("b_c", "One.", {}), tool)],
            "a_b": [(ToolSpec("c", "Another.", {}), tool)],
        }
    )
    engine = Kataloop(client, store, toolbox)
    servers = (ToolServer("a", "local"), ToolServer("a_b", "local"))
    agent = AgentDefinition("Answer briefly.", servers)

    with pytest.raises(ValueError, match="'a_b_c'"):
        await run(engine, session, agent=agent)
    assert vendor.requests == []
