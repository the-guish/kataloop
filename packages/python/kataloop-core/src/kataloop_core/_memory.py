# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""The documents the engine keeps in its `Store`, made and read without I/O.

A checkpoint's memory holds the conversation up to the end of a finished turn, in
uni-llm-client's JSON form, so that every assistant message replays to its
provider as it came (MSG-2, MSG-11). It holds nothing of the caller's: no system
prompt, no agent, no model (ENG-10).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from uni_llm_client import Message

VERSION = 1
"""The form of the documents below; one of another version is refused."""


def checkpoint_memory(
    *, parent: str | None, prompt: str, text: str, messages: Sequence[Message]
) -> dict[str, Any]:
    """The memory of a finished turn: the whole conversation up to and including
    its final assistant message, the checkpoint it began from, its prompt and its
    answer."""
    return {
        "version": VERSION,
        "parent": parent,
        "prompt": prompt,
        "text": text,
        "messages": [message.to_dict() for message in messages],
    }


def messages_of(memory: Mapping[str, Any]) -> list[Message]:
    """The conversation a checkpoint's memory holds.

    Raises:
        ValueError: `memory` is not a document of this version.
    """
    return _messages(_checked(memory)["messages"])


def _checked(document: Mapping[str, Any]) -> Mapping[str, Any]:
    if document.get("version") != VERSION:
        raise ValueError(f"A memory of version {document.get('version')!r}")
    return document


def _messages(data: Any) -> list[Message]:
    if not isinstance(data, list):
        raise ValueError("The memory's messages must be an array")
    return [Message.from_dict(message) for message in data]
