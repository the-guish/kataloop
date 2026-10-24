# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""The `Store` in the process (MEM-2, MEM-7, MEM-8, MEM-10)."""

import math
from uuid import uuid4

import pytest

from kataloop_core import (
    CheckpointNotFoundError,
    MemoryStore,
    SessionExistsError,
    SessionNotFoundError,
)


async def test_it_keeps_checkpoints_in_the_order_they_were_added() -> None:
    store = MemoryStore()
    await store.setup()
    await store.setup()  # safe to repeat
    session = uuid4()
    await store.create(session)
    assert await store.latest_checkpoint(session) is None

    for checkpoint_id in ["b", "a", "c"]:
        await store.add_checkpoint(session, checkpoint_id, {"id": checkpoint_id})

    assert await store.latest_checkpoint(session) == "c"
    assert await store.checkpoint(session, "a") == {"id": "a"}
    assert await store.checkpoint(session, "d") is None
    assert await store.checkpoint(uuid4(), "a") is None
    assert await store.latest_checkpoint(uuid4()) is None


async def test_a_checkpoint_forgets_the_turn_in_progress() -> None:
    store = MemoryStore()
    session = uuid4()
    await store.create(session)
    await store.save_partial(session, {"round": 1})
    await store.save_partial(session, {"round": 2})
    assert await store.partial(session) == {"round": 2}

    await store.add_checkpoint(session, "a", {})

    assert await store.partial(session) is None
    await store.clear_partial(session)
    await store.clear_partial(uuid4())


async def test_what_it_keeps_is_json_and_every_read_a_copy() -> None:
    store = MemoryStore()
    session = uuid4()
    await store.create(session)
    memory = {"messages": [{"text": "Hi."}]}
    await store.add_checkpoint(session, "a", memory)
    memory["messages"].append({"text": "changed"})

    read = await store.checkpoint(session, "a")
    assert read is not None
    assert read == {"messages": [{"text": "Hi."}]}
    read["messages"].append({"text": "changed"})
    assert await store.checkpoint(session, "a") == {"messages": [{"text": "Hi."}]}

    with pytest.raises(TypeError):
        await store.add_checkpoint(session, "b", {"when": {1, 2}})
    with pytest.raises(ValueError):
        await store.save_partial(session, {"score": math.nan})
    assert await store.checkpoint(session, "b") is None
    assert await store.partial(session) is None


async def test_a_session_that_is_gone_takes_no_write() -> None:
    store = MemoryStore()

    with pytest.raises(SessionNotFoundError):
        await store.add_checkpoint(uuid4(), "a", {})
    with pytest.raises(SessionNotFoundError):
        await store.save_partial(uuid4(), {})


async def test_a_copy_takes_the_checkpoints_up_to_the_one_named() -> None:
    store = MemoryStore()
    source, target = uuid4(), uuid4()
    await store.create(source)
    for checkpoint_id in ["a", "b", "c"]:
        await store.add_checkpoint(source, checkpoint_id, {"id": checkpoint_id})
    await store.save_partial(source, {"round": 1})

    await store.copy(source, target, checkpoint_id="b")

    assert await store.latest_checkpoint(target) == "b"
    assert await store.checkpoint(target, "a") == {"id": "a"}
    assert await store.checkpoint(target, "c") is None
    assert await store.partial(target) is None
    # The source is as it was.
    assert await store.latest_checkpoint(source) == "c"
    assert await store.partial(source) == {"round": 1}


async def test_a_copy_is_refused_writing_nothing() -> None:
    store = MemoryStore()
    source, other, target = uuid4(), uuid4(), uuid4()
    await store.create(source)
    await store.create(other)
    await store.add_checkpoint(source, "a", {})

    with pytest.raises(SessionNotFoundError):
        await store.copy(target, other, checkpoint_id="a")
    with pytest.raises(CheckpointNotFoundError):
        await store.copy(source, target, checkpoint_id="b")
    with pytest.raises(SessionExistsError):
        await store.copy(source, other, checkpoint_id="a")

    assert not await store.exists(target)
    assert await store.latest_checkpoint(other) is None


async def test_delete_forgets_the_session_and_everything_it_held() -> None:
    store = MemoryStore()
    session = uuid4()
    await store.create(session)
    await store.add_checkpoint(session, "a", {})
    await store.save_partial(session, {})

    await store.delete(session)
    await store.delete(session)

    assert not await store.exists(session)
    await store.create(session)
    assert await store.checkpoint(session, "a") is None
    assert await store.partial(session) is None
