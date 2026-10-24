# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""The contract between kataloop and its callers; the spec is docs/specs/engine.md."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from uni_llm_client import Effort, Usage


class KataloopError(Exception):
    """Base class for the errors of the contract."""


class SessionExistsError(KataloopError):
    """`create` or `fork` named a session that exists."""


class SessionNotFoundError(KataloopError):
    """A session the engine does not have."""


class CheckpointNotFoundError(KataloopError):
    """A checkpoint the engine does not hold for that session (ENG-2)."""


class RoundsExceededError(KataloopError):
    """The turn made as many model calls as its timeout allows and needed another
    (ENG-13)."""


@dataclass(frozen=True, slots=True)
class ToolServer:
    """An MCP server an agent may use, with its secrets resolved by the caller."""

    id: str
    """Names the server to the caller; its tools are offered under their own
    names (ENG-11)."""

    url: str

    headers: Mapping[str, str] = field(default_factory=dict)
    """Sent with every request to the server, the credential among them."""

    timeout: float = 60.0
    """Seconds to wait for the server, per call."""

    exclude: tuple[str, ...] = ()
    """Tools of the server's the agent is not given, by the server's own names."""


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    system_prompt: str
    tool_servers: tuple[ToolServer, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """The model a turn runs on, with its limits."""

    id: str
    """A uni-llm-client model id, ``provider/model``."""

    timeout: float = 120.0
    """Seconds, per model call."""

    max_output_tokens: int | None = None

    context_window: int | None = None
    """Tokens. When ``None``, what the engine knows of the model, else a default
    (ENG-12)."""

    effort: Effort | str | None = None


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ReasoningDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool call, reported once its arguments are complete (ENG-3)."""

    call_id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What the model will see of a tool call; a failure is an error result."""

    call_id: str
    name: str
    output: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class Done:
    """The last event of a turn (ENG-3), once the memory holds the turn (ENG-4)."""

    text: str
    checkpoint_id: str
    usage: Usage


Event = TextDelta | ReasoningDelta | ToolCall | ToolResult | Done


class Engine(ABC):
    """Runs an agent's turns and remembers its conversations (docs/specs/engine.md)."""

    @abstractmethod
    async def setup(self) -> None:
        """Make the storage ready. Safe to repeat."""

    @abstractmethod
    async def create(self, session_id: UUID) -> None:
        """`SessionExistsError` if the session exists."""

    @abstractmethod
    async def exists(self, session_id: UUID) -> bool: ...

    @abstractmethod
    def stream(
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
        """Run a turn and yield what happens, `Done` last.

        Not a coroutine: everything, the refusals included, happens inside the
        iterator (ENG-1), an async generator that the caller may close to cancel
        the turn (ENG-5). With `resume`, the engine goes on with the session's
        latest turn if it began from `checkpoint_id`, else runs `prompt` from it
        (ENG-7). Past `timeout` seconds it raises `TimeoutError` (ENG-6).

        Raises:
            SessionNotFoundError: The session was not created.
            CheckpointNotFoundError: The checkpoint is not held for it (ENG-2).
            TimeoutError: The turn passed its deadline.
            RoundsExceededError: The turn needed more model calls than its
                timeout allows (ENG-13).
        """

    @abstractmethod
    async def fork(
        self, source_id: UUID, target_id: UUID, *, checkpoint_id: str
    ) -> None:
        """Make `target_id` from the source's memory at `checkpoint_id` (ENG-8).

        Raises:
            SessionNotFoundError: The source was not created.
            CheckpointNotFoundError: The checkpoint is not held for the source.
            SessionExistsError: The target exists.
        """

    @abstractmethod
    async def forget(self, session_id: UUID) -> None:
        """Delete everything kept for the session; nothing if it is gone (ENG-9)."""
