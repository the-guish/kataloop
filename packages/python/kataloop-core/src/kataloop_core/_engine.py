# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""The engine kataloop ships: the loop of docs/specs/turn.md over a `Store` and a
`Toolbox`."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Sequence
from contextlib import aclosing
from typing import cast
from uuid import UUID, uuid4

import uni_llm_client as llm

from kataloop_core._context import cut, fit, window_of
from kataloop_core._contract import (
    AgentDefinition,
    CheckpointNotFoundError,
    Done,
    Engine,
    Event,
    ModelSpec,
    ReasoningDelta,
    RoundsExceededError,
    SessionNotFoundError,
    TextDelta,
    ToolCall,
    ToolResult,
    ToolServer,
)
from kataloop_core._memory import Checkpoint, PartialTurn
from kataloop_core._ports import Store, Toolbox, ToolOutput, ToolSpec

FASTEST_MODEL_CALL = 1.0
"""Seconds: a turn makes at most one model call per second of its timeout
(ENG-13). Real rounds are slower; a loop faster than that is runaway."""


class Kataloop(Engine):
    """The agent loop: turns run on `client`, memory kept in `store`, tools reached
    through `toolbox` (docs/specs/engine.md, docs/specs/turn.md).

    Args:
        client: A uni-llm-client client with the providers the model ids name. The
            engine never configures it and never closes it.
        store: Where the memory is kept, such as a `MemoryStore`.
        toolbox: How the agents' tool servers are reached, such as a
            `LocalToolbox`.
    """

    def __init__(self, client: llm.AsyncClient, store: Store, toolbox: Toolbox) -> None:
        self._client = client
        self._store = store
        self._toolbox = toolbox

    async def setup(self) -> None:
        await self._store.setup()

    async def create(self, session_id: UUID) -> None:
        await self._store.create(session_id)

    async def exists(self, session_id: UUID) -> bool:
        return await self._store.exists(session_id)

    async def stream(
        self,
        session_id: UUID,
        agent: AgentDefinition,
        prompt: str,
        *,
        model: ModelSpec,
        checkpoint_id: str | None,
        timeout: float,
        resume: bool = False,
    ) -> AsyncGenerator[Event, None]:
        # An async generator: nothing runs before the first iteration (ENG-1).
        if not (math.isfinite(timeout) and timeout > 0):  # TURN-1
            raise ValueError(f"The timeout must be positive seconds, not {timeout!r}")
        window = window_of(model)  # CTX-1, refused as the timeout is
        # Set once; every await below is bounded by it (ENG-6, TURN-8).
        deadline = asyncio.get_running_loop().time() + timeout
        most_calls = math.ceil(timeout / FASTEST_MODEL_CALL)  # ENG-13, TURN-7

        history = await _within(deadline, self._history(session_id, checkpoint_id))
        turn: list[llm.Message] | None = None
        if resume:  # ENG-7, MEM-5
            resumed = await _within(deadline, self._resumed(session_id, checkpoint_id))
            if isinstance(resumed, Done):
                yield resumed
                return
            if resumed is not None:
                prompt, turn = resumed.prompt, list(resumed.messages)
        if turn is None:
            # A turn from its prompt forgets the rounds of the one before (MEM-4).
            await _within(deadline, self._store.clear_partial(session_id))
            turn = [llm.Message.user(prompt)]
        servers = agent.tool_servers
        listed = [await _within(deadline, self._toolbox.tools(s)) for s in servers]
        routes, tools = _offered(servers, listed)

        usage = llm.Usage()
        calls = 0
        while True:
            _bound(calls, most_calls)
            # The history within the window, the turn whole (ENG-12, TURN-3). A
            # summary call is one of the turn's calls, of its usage and under its
            # deadline (CTX-9); the history it compacts is the turn's from then on,
            # and what its checkpoint keeps (CTX-12).
            fitted = await _within(
                deadline,
                fit(self._client, model, agent.system_prompt, tools, history, turn),
            )
            history = fitted.history
            if fitted.usage is not None:
                usage = _sum(usage, fitted.usage)
                calls += 1
                _bound(calls, most_calls)
            calls += 1
            response: llm.Response | None = None
            stream = self._client.stream(
                model.id,
                [*history, *turn],
                system=agent.system_prompt,
                tools=tools,
                effort=model.effort,
                max_tokens=model.max_output_tokens,
                timeout=model.timeout,
            )
            # Closing the turn, cancelling it or an error closes the vendor's
            # response (ENG-5, TURN-9). Nothing is awaited while an event is with
            # the caller, so the deadline bounds the run alone (ENG-6, TURN-8).
            async with aclosing(_closable(stream)) as events:
                while True:
                    async with asyncio.timeout_at(deadline):
                        event = await anext(events, None)
                    match event:
                        case None:
                            break
                        case llm.TextDelta(text=delta):
                            yield TextDelta(delta)  # TURN-4
                        case llm.ReasoningDelta(text=delta):
                            yield ReasoningDelta(delta)
                        case llm.ToolUseEnd(block=block):
                            # Once its arguments are complete (ENG-3, TURN-4).
                            yield ToolCall(block.id, block.name, block.input)
                        case llm.Completed(response=response):
                            pass
            if response is None:  # STREAM-3 promises it; never half a round
                raise llm.IncompleteResponseError("The stream ended without a response")
            usage = _sum(usage, response.usage)
            turn.append(response.message)

            uses = response.message.tool_uses
            match response.stop_reason:  # TURN-5
                case llm.StopReason.END_TURN:
                    break
                case llm.StopReason.TOOL_USE if not uses:
                    # No call to run: the turn ends as with end_turn.
                    break
                case llm.StopReason.MAX_TOKENS:
                    # A cut answer is not an answer.
                    raise llm.IncompleteResponseError(
                        "The model's output limit cut the turn short"
                    )
                case llm.StopReason.TOOL_USE:
                    results = await _within(deadline, self._run(routes, uses, window))
                    turn.append(llm.Message.tool_results(*results))
                case llm.StopReason.PAUSE_TURN:
                    # The vendor's own loop paused: sent back, it goes on.
                    uses, results = (), []
            # Saved before its results are told, so that a result told never runs
            # again on resume (ENG-7, MEM-4).
            partial = PartialTurn(checkpoint_id, prompt, tuple(turn)).to_dict()
            await _within(deadline, self._store.save_partial(session_id, partial))
            for use, result in zip(uses, results, strict=True):
                yield ToolResult(use.id, use.name, result.content, result.is_error)

        text = turn[-1].text  # the final assistant message's
        new_id = uuid4().hex
        # The history as the turn compacted it, if it did, so that the next turn
        # need not compact it again (CTX-12).
        memory = Checkpoint(checkpoint_id, prompt, text, (*history, *turn)).to_dict()
        # The memory holds the turn, and no longer its rounds, before Done is
        # yielded (ENG-4, TURN-10, MEM-4).
        await _within(deadline, self._store.add_checkpoint(session_id, new_id, memory))
        yield Done(text, new_id, usage)

    async def fork(
        self, source_id: UUID, target_id: UUID, *, checkpoint_id: str
    ) -> None:
        # The store refuses, writing nothing (ENG-2, ENG-8).
        await self._store.copy(source_id, target_id, checkpoint_id=checkpoint_id)

    async def forget(self, session_id: UUID) -> None:
        await self._store.delete(session_id)  # ENG-9

    async def _history(
        self, session_id: UUID, checkpoint_id: str | None
    ) -> tuple[llm.Message, ...]:
        """The conversation the turn goes on from, after the refusals of ENG-2."""
        if not await self._store.exists(session_id):
            raise SessionNotFoundError(str(session_id))
        if checkpoint_id is None:
            return ()
        memory = await self._store.checkpoint(session_id, checkpoint_id)
        if memory is None:
            raise CheckpointNotFoundError(checkpoint_id)
        return Checkpoint.from_dict(memory).messages  # MEM-1

    async def _resumed(
        self, session_id: UUID, checkpoint_id: str | None
    ) -> PartialTurn | Done | None:
        """What a resumed turn goes on with (MEM-5): the partial turn begun from
        the checkpoint; else the `Done` of the turn that finished from it, with no
        usage (MEM-6); else nothing, and the prompt runs."""
        state = await self._store.partial(session_id)
        if state is not None:
            partial = PartialTurn.from_dict(state)
            if partial.parent == checkpoint_id:
                return partial
        latest = await self._store.latest_checkpoint(session_id)
        if latest is None:
            return None
        memory = await self._store.checkpoint(session_id, latest)
        if memory is None:
            return None
        finished = Checkpoint.from_dict(memory)
        if finished.parent != checkpoint_id:
            return None
        return Done(finished.text, latest, llm.Usage())

    async def _run(
        self,
        routes: dict[str, ToolServer],
        uses: Sequence[llm.ToolUseBlock],
        window: int,
    ) -> list[llm.ToolResultBlock]:
        """The results of a round's tool calls, in their order: every call runs,
        all together, and each gets a result (ENG-11, TURN-6), cut past a share
        of the window, as the model, the events and the memory see it (CTX-3)."""
        outputs = await asyncio.gather(*(self._call(routes, use) for use in uses))
        return [
            llm.ToolResultBlock(use.id, cut(output.text, window), output.is_error)
            for use, output in zip(uses, outputs, strict=True)
        ]

    async def _call(
        self, routes: dict[str, ToolServer], use: llm.ToolUseBlock
    ) -> ToolOutput:
        """What the model is told of one tool call: the tool's answer, or its
        failure as an error result (ENG-11, TURN-6)."""
        server = routes.get(use.name)
        if server is None:
            return ToolOutput(f"There is no tool named {use.name!r}.", is_error=True)
        timeout = server.timeout
        try:
            async with asyncio.timeout(timeout):
                return await self._toolbox.call(server, use.name, use.input)
        except TimeoutError:
            return ToolOutput(f"Timed out after {timeout:g} seconds.", is_error=True)
        # CancelledError is no Exception: it is let through (ENG-5, TURN-9).
        except Exception as error:
            return ToolOutput(
                f"The tool call failed: {type(error).__name__}.", is_error=True
            )


def _offered(
    servers: Sequence[ToolServer], listed: Sequence[Sequence[ToolSpec]]
) -> tuple[dict[str, ToolServer], list[llm.Tool]]:
    """The tools the model is offered, under their servers' own names, without
    those each server excludes, and where each lives (ENG-11, TURN-2)."""
    routes: dict[str, ToolServer] = {}
    tools: list[llm.Tool] = []
    for server, specs in zip(servers, listed, strict=True):
        for spec in specs:
            if spec.name in server.exclude:
                continue
            if spec.name in routes:
                raise ValueError(
                    f"Two tools are named {spec.name!r}: servers "
                    f"{routes[spec.name].id!r} and {server.id!r}"
                )
            routes[spec.name] = server
            tools.append(llm.Tool(spec.name, spec.description, spec.input_schema))
    return routes, tools


def _bound(calls: int, most_calls: int) -> None:
    """Refuses the model call past the turn's bound, instead of sending it
    (ENG-13, TURN-7)."""
    if calls == most_calls:
        raise RoundsExceededError(f"No answer after {calls} model calls")


async def _within[T](deadline: float, awaitable: Awaitable[T]) -> T:
    """`awaitable`, awaited under the turn's deadline (ENG-6, TURN-8)."""
    async with asyncio.timeout_at(deadline):
        return await awaitable


def _closable[T](events: AsyncIterator[T]) -> AsyncGenerator[T, None]:
    """The model's stream, which uni-llm-client types as an iterator, as the async
    generator it is, for `aclosing` (STREAM-6)."""
    return cast(AsyncGenerator[T, None], events)


def _sum(a: llm.Usage, b: llm.Usage) -> llm.Usage:
    return llm.Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cached_input_tokens=a.cached_input_tokens + b.cached_input_tokens,
        reasoning_tokens=a.reasoning_tokens + b.reasoning_tokens,
    )
