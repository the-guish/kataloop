# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""The seams between the core and what needs a dependency (docs/specs/principles.md).

Draft: the methods settle with their first implementations (docs/plan.md).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from kataloop_core._contract import ToolServer


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool as its server describes it; the engine prefixes the name (ENG-11)."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    """A JSON Schema object describing the arguments."""


@dataclass(frozen=True, slots=True)
class ToolOutput:
    """What a tool answered, as the model will see it."""

    text: str
    is_error: bool = False


class Toolbox(ABC):
    """How the engine reaches an agent's tools.

    The core's `LocalToolbox` calls tools of the process's own; `kataloop` reaches
    MCP servers.
    """

    @abstractmethod
    async def tools(self, server: ToolServer) -> Sequence[ToolSpec]:
        """The tools `server` offers, by the server's own names.

        The engine leaves out those `server.exclude` names (ENG-11).
        """

    @abstractmethod
    async def call(
        self, server: ToolServer, name: str, arguments: Mapping[str, Any]
    ) -> ToolOutput:
        """Run the tool `name`, by the server's own name, with the call's arguments.

        A failure the tool reports itself is an output with `is_error`. A failure
        raised here becomes an error result too, and so does a call that outlasts
        `server.timeout`: the engine bounds it (ENG-11, docs/specs/turn.md).
        """


class Store(ABC):
    """Where the engine keeps its memory: the sessions, their checkpoints, and the
    rounds of a turn in progress.

    A checkpoint's memory and a partial turn are JSON documents the store never
    reads (docs/specs/memory.md). A store keeps a session's checkpoints in the
    order they were added. The core keeps them in the process (`MemoryStore`);
    `kataloop[postgres]` keeps them in PostgreSQL.
    """

    @abstractmethod
    async def setup(self) -> None:
        """Make the storage ready. Safe to repeat."""

    @abstractmethod
    async def create(self, session_id: UUID) -> None:
        """`SessionExistsError` if the session exists."""

    @abstractmethod
    async def exists(self, session_id: UUID) -> bool: ...

    @abstractmethod
    async def delete(self, session_id: UUID) -> None:
        """Delete the session with everything held for it; nothing if it is gone."""

    @abstractmethod
    async def checkpoint(
        self, session_id: UUID, checkpoint_id: str
    ) -> Mapping[str, Any] | None:
        """The memory at the checkpoint, or None when the session does not hold it."""

    @abstractmethod
    async def latest_checkpoint(self, session_id: UUID) -> str | None:
        """The id of the checkpoint added last, or None when the session holds none
        or is gone (MEM-2)."""

    @abstractmethod
    async def add_checkpoint(
        self, session_id: UUID, checkpoint_id: str, memory: Mapping[str, Any]
    ) -> None:
        """Keep the memory of a finished turn under a new id, and forget the turn
        in progress, in one write (ENG-4, MEM-4).

        `SessionNotFoundError` if the session is gone.
        """

    @abstractmethod
    async def partial(self, session_id: UUID) -> Mapping[str, Any] | None:
        """The turn in progress, as last saved, for resume (ENG-7); None when there
        is none or the session is gone."""

    @abstractmethod
    async def save_partial(self, session_id: UUID, state: Mapping[str, Any]) -> None:
        """Replace the turn in progress with `state`.

        `SessionNotFoundError` if the session is gone.
        """

    @abstractmethod
    async def clear_partial(self, session_id: UUID) -> None:
        """Forget the turn in progress; nothing if there is none."""

    @abstractmethod
    async def copy(
        self, source_id: UUID, target_id: UUID, *, checkpoint_id: str
    ) -> None:
        """Make `target_id` with the source's checkpoints up to and including
        `checkpoint_id`, in their order, and no turn in progress (ENG-8).

        Nothing is written when it raises.

        Raises:
            SessionNotFoundError: The source does not exist.
            CheckpointNotFoundError: The source does not hold the checkpoint.
            SessionExistsError: The target exists.
        """
