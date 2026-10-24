# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""The documents the engine keeps in its `Store`, as specified in
docs/specs/memory.md, made and read without I/O.

Messages are in uni-llm-client's JSON form, so that an assistant message replays
to its provider as it came (MSG-2, MSG-11). Nothing of the caller's is kept: no
system prompt, no agent, no model (ENG-10, MEM-3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from uni_llm_client import Message

VERSION = 1
"""The form of the documents; one of another version is refused (MEM-9)."""


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """The memory of a finished turn (MEM-1)."""

    parent: str | None
    """The checkpoint the turn began from; None for a first turn."""

    prompt: str
    text: str
    """The turn's answer, `Done.text`."""

    messages: tuple[Message, ...]
    """The whole conversation, up to and including the turn's final assistant
    message."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "parent": self.parent,
            "prompt": self.prompt,
            "text": self.text,
            "messages": _dicts(self.messages),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Checkpoint:
        """Raises:
        ValueError: `data` is not a checkpoint's memory of this version."""
        data = _document(data, "checkpoint", ("parent", "prompt", "text", "messages"))
        return cls(
            _parent(data["parent"]),
            _string(data["prompt"], "prompt"),
            _string(data["text"], "text"),
            _messages(data["messages"]),
        )


@dataclass(frozen=True, slots=True)
class PartialTurn:
    """A turn in progress, as of its last saved round (MEM-4)."""

    parent: str | None
    """The checkpoint the turn began from; None for a first turn."""

    prompt: str
    messages: tuple[Message, ...]
    """The turn's own messages: its prompt, then each saved round's."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "parent": self.parent,
            "prompt": self.prompt,
            "messages": _dicts(self.messages),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PartialTurn:
        """Raises:
        ValueError: `data` is not a partial turn of this version."""
        data = _document(data, "partial turn", ("parent", "prompt", "messages"))
        return cls(
            _parent(data["parent"]),
            _string(data["prompt"], "prompt"),
            _messages(data["messages"]),
        )


def _dicts(messages: Sequence[Message]) -> list[dict[str, Any]]:
    return [message.to_dict() for message in messages]


def _document(
    data: Mapping[str, Any], what: str, fields: Sequence[str]
) -> Mapping[str, Any]:
    if data.get("version") != VERSION:
        raise ValueError(f"A {what} of version {data.get('version')!r}")
    for name in fields:
        if name not in data:
            raise ValueError(f"A {what} without {name!r}")
    return data


def _parent(value: Any) -> str | None:
    return None if value is None else _string(value, "parent")


def _string(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"The memory's {what} must be a string")
    return value


def _messages(value: Any) -> tuple[Message, ...]:
    if not isinstance(value, list):
        raise ValueError("The memory's messages must be an array")
    return tuple(Message.from_dict(message) for message in value)
