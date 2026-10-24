# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""The `Store` in the process."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from kataloop_core._contract import (
    CheckpointNotFoundError,
    SessionExistsError,
    SessionNotFoundError,
)
from kataloop_core._ports import Store


@dataclass(slots=True)
class _Session:
    checkpoints: dict[str, str] = field(default_factory=dict)
    """Each checkpoint's memory as JSON text, in the order they were added."""

    partial: str | None = None
    """The turn in progress as JSON text, if a round of it was saved."""


class MemoryStore(Store):
    """Memory that lasts as long as the store: for tests, and for callers that
    need no more.

    Documents are kept as JSON text, so that one a database could not hold is
    refused here too, and what a read returns is a copy.
    """

    def __init__(self) -> None:
        self._sessions: dict[UUID, _Session] = {}

    async def setup(self) -> None:
        """Nothing to make ready."""

    async def create(self, session_id: UUID) -> None:
        if session_id in self._sessions:
            raise SessionExistsError(str(session_id))
        self._sessions[session_id] = _Session()

    async def exists(self, session_id: UUID) -> bool:
        return session_id in self._sessions

    async def delete(self, session_id: UUID) -> None:
        self._sessions.pop(session_id, None)

    async def checkpoint(
        self, session_id: UUID, checkpoint_id: str
    ) -> Mapping[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None or checkpoint_id not in session.checkpoints:
            return None
        return _load(session.checkpoints[checkpoint_id])

    async def add_checkpoint(
        self, session_id: UUID, checkpoint_id: str, memory: Mapping[str, Any]
    ) -> None:
        self._session(session_id).checkpoints[checkpoint_id] = _dump(memory)

    async def partial(self, session_id: UUID) -> Mapping[str, Any] | None:
        session = self._sessions.get(session_id)
        if session is None or session.partial is None:
            return None
        return _load(session.partial)

    async def save_partial(self, session_id: UUID, state: Mapping[str, Any]) -> None:
        self._session(session_id).partial = _dump(state)

    async def clear_partial(self, session_id: UUID) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.partial = None

    async def copy(
        self, source_id: UUID, target_id: UUID, *, checkpoint_id: str
    ) -> None:
        source = self._session(source_id)
        if checkpoint_id not in source.checkpoints:
            raise CheckpointNotFoundError(checkpoint_id)
        if target_id in self._sessions:
            raise SessionExistsError(str(target_id))
        ids = list(source.checkpoints)
        kept = ids[: ids.index(checkpoint_id) + 1]
        self._sessions[target_id] = _Session({i: source.checkpoints[i] for i in kept})

    def _session(self, session_id: UUID) -> _Session:
        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(str(session_id))
        return session


def _dump(document: Mapping[str, Any]) -> str:
    """`document` as JSON text; `TypeError` or `ValueError` for what JSON cannot
    hold."""
    return json.dumps(document, allow_nan=False)


def _load(text: str) -> Mapping[str, Any]:
    document: Mapping[str, Any] = json.loads(text)
    return document
