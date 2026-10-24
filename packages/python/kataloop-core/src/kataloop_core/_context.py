# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""Context management: what of the conversation a model call sends, so that it
stays within the model's window (ENG-12). The spec is docs/specs/context.md.

Every model call of a turn sends the history `fit` returns, then the turn's own
messages whole (CTX-4). The arithmetic is in pure functions; `fit` applies them
and is the one place that may call the model, to write a summary (CTX-9).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from uni_llm_client import (
    AsyncClient,
    ContentBlock,
    Message,
    ReasoningBlock,
    ServerToolUseBlock,
    TextBlock,
    Tool,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)

from kataloop_core._contract import ModelSpec

DEFAULT_CONTEXT_WINDOW = 128_000
"""Tokens: the window of a model whose spec gives none (CTX-1)."""

CHARS_PER_TOKEN = 4
"""The estimate of a token, in characters (CTX-2)."""

LARGEST_RESULT = 0.2
"""The share of the window one tool result may take, in characters; past it, the
rest is cut (CTX-3)."""

SUMMARIZE_AT = 0.7
"""The share of the window past which the history is compacted (CTX-5)."""

KEEP = 0.3
"""The share of the window the newest exchanges kept whole may take (CTX-7).
What the summary call reads may take the rest up to `SUMMARIZE_AT` (CTX-8)."""

SUMMARY_PROMPT = (
    "The user's message is a conversation between a user and you, the assistant. "
    "Summarise it densely for your own later use: you will go on with the "
    "conversation from your summary alone. Keep every fact, decision, name, number "
    "and open question. Answer with the summary and nothing else."
)
"""The system prompt of the summary call (CTX-9)."""

SUMMARY_MARKER = "[A summary of the earlier conversation]"
"""The first line of the summary message, by which a later compaction knows it
(CTX-10)."""

SEPARATOR = "\n\n"
"""Between two entries of a transcript (CTX-9)."""


@dataclass(frozen=True, slots=True)
class Fitted:
    """What `fit` returns."""

    history: tuple[Message, ...]
    """The history to send, before the turn's own messages."""

    usage: Usage | None = None
    """The usage of the summary call `fit` made, or None when it made none: the
    call is one of the turn's (CTX-9)."""


@dataclass(frozen=True, slots=True)
class Compaction:
    """How a history is compacted (CTX-7): `earlier`, then `older`, are replaced
    by one summary, and `kept` follows it."""

    earlier: tuple[Message, ...]
    """The summary message of an earlier compaction, at the front of the
    history, or nothing."""

    older: tuple[Message, ...]
    """The exchanges older than those kept, the earlier summary aside."""

    kept: tuple[Message, ...]
    """The newest exchanges, kept whole."""


async def fit(
    client: AsyncClient,
    model: ModelSpec,
    system: str,
    tools: Sequence[Tool],
    history: Sequence[Message],
    turn: Sequence[Message],
) -> Fitted:
    """The history a model call of the turn sends before `turn`, within the
    model's window (ENG-12).

    Under `SUMMARIZE_AT` of the window, the history as it came (CTX-5). Past it,
    the history compacted: the newest exchanges kept whole and replayed from
    their blocks (CTX-7, CTX-11), what is older folded into one summary by a call
    to the model (CTX-8, CTX-9). `turn` is never cut (CTX-4).
    """
    window = window_of(model)
    prompt = tokens((*history, *turn), system=system, tools=tools)
    if prompt <= int(window * SUMMARIZE_AT):
        return Fitted(tuple(history))
    plan = compaction(history, window)
    if plan is None:  # nothing older to fold: the turn is never cut
        return Fitted(tuple(history))
    response = await client.complete(
        model.id,
        [Message.user(summarised(plan, window))],
        system=SUMMARY_PROMPT,
        max_tokens=model.max_output_tokens,
        timeout=model.timeout,
    )
    summary = summary_message(response.text)
    return Fitted((summary, *replayed(plan.kept)), response.usage)


def window_of(model: ModelSpec) -> int:
    """The model's window, in tokens (CTX-1).

    Raises:
        ValueError: The spec's window is not a positive number of tokens.
    """
    window = model.context_window
    if window is None:
        return DEFAULT_CONTEXT_WINDOW
    if window <= 0:
        raise ValueError(f"The context window must be positive tokens, not {window!r}")
    return window


def tokens(
    messages: Sequence[Message] = (),
    *,
    system: str = "",
    tools: Sequence[Tool] = (),
) -> int:
    """The estimate of a prompt, in tokens: its characters over `CHARS_PER_TOKEN`,
    rounded up (CTX-2)."""
    size = len(system) + sum(map(_tool_characters, tools))
    size += sum(map(characters, messages))
    return -(-size // CHARS_PER_TOKEN)


def characters(message: Message) -> int:
    """The characters of a message that the estimate counts (CTX-2)."""
    return sum(map(_block_characters, message.content))


def cut(output: str, window: int) -> str:
    """A tool's output as the model sees it: past `LARGEST_RESULT` of the window,
    in characters, cut there and the cut noted (CTX-3)."""
    largest = int(window * LARGEST_RESULT) * CHARS_PER_TOKEN
    if len(output) <= largest:
        return output
    return f"{output[:largest]}\n[Cut: the result was {len(output)} characters.]"


def exchanges(messages: Sequence[Message]) -> list[tuple[Message, ...]]:
    """The messages, in exchanges: each starts at a user message that holds no
    tool result and runs to just before the next one, so that a tool call and its
    results are never apart (CTX-6)."""
    groups: list[list[Message]] = []
    for message in messages:
        if groups and not _opens(message):
            groups[-1].append(message)
        else:
            groups.append([message])
    return [tuple(group) for group in groups]


def newest(groups: Sequence[Sequence[Message]], budget: int) -> int:
    """Where the newest of `groups` that fit within `budget` tokens together
    begin: an index into `groups`, its length when not even the newest fits
    (CTX-7)."""
    room = budget * CHARS_PER_TOKEN
    start = len(groups)
    while start > 0:
        size = sum(map(characters, groups[start - 1]))
        if size > room:
            break
        room -= size
        start -= 1
    return start


def compaction(history: Sequence[Message], window: int) -> Compaction | None:
    """How `history` is compacted, or None when there is nothing older than the
    exchanges it keeps but an earlier summary (CTX-7)."""
    groups = exchanges(history)
    start = newest(groups, int(window * KEEP))
    older = tuple(message for group in groups[:start] for message in group)
    earlier = older[:1] if older and is_summary(older[0]) else ()
    older = older[len(earlier) :]
    if not older:
        return None
    kept = tuple(message for group in groups[start:] for message in group)
    return Compaction(earlier, older, kept)


def summarised(plan: Compaction, window: int) -> str:
    """What the summary call reads: the transcript of the earlier summary and of
    the older exchanges, bounded to `SUMMARIZE_AT` - `KEEP` of the window in
    characters. The earlier summary stays whole at its front; past the bound,
    the start of the rest is cut, so that its newest part is read (CTX-8)."""
    room = (int(window * SUMMARIZE_AT) - int(window * KEEP)) * CHARS_PER_TOKEN
    head = transcript(plan.earlier)
    if head:
        room -= len(head) + len(SEPARATOR)
    rest = transcript(plan.older)
    newest_part = min(max(room, 0), len(rest))
    rest = rest[len(rest) - newest_part :]
    return SEPARATOR.join(part for part in (head, rest) if part)


def transcript(messages: Sequence[Message]) -> str:
    """The messages as the text the summary call reads: an entry per block, in
    order, a blank line between entries (CTX-9)."""
    names = {
        block.id: block.name
        for message in messages
        for block in message.content
        if isinstance(block, ToolUseBlock)
    }
    entries: list[str] = []
    for message in messages:
        if is_summary(message):
            entries.append(message.text)
            continue
        for block in message.content:
            entry = _entry(message, block, names)
            if entry is not None:
                entries.append(entry)
    return SEPARATOR.join(entries)


def summary_message(summary: str) -> Message:
    """The user message that holds a summary in the history (CTX-10)."""
    return Message.user(f"{SUMMARY_MARKER}\n{summary}")


def is_summary(message: Message) -> bool:
    """Whether `message` is a summary message (CTX-10)."""
    return message.role == "user" and message.text.startswith(f"{SUMMARY_MARKER}\n")


def replayed(messages: Sequence[Message]) -> tuple[Message, ...]:
    """The messages without their vendor content, so that each replays from its
    blocks, reasoning left out (CTX-11)."""
    return tuple(replace(message, vendor=None) for message in messages)


def _opens(message: Message) -> bool:
    """Whether `message` begins an exchange (CTX-6)."""
    return message.role == "user" and not any(
        isinstance(block, ToolResultBlock) for block in message.content
    )


def _block_characters(block: ContentBlock) -> int:
    match block:
        case TextBlock(text=text) | ReasoningBlock(text=text):
            return len(text)
        case ToolResultBlock(content=text):
            return len(text)
        case (
            ToolUseBlock(name=name, input=arguments)
            | ServerToolUseBlock(name=name, input=arguments)
        ):
            return len(name) + len(_json(arguments))
    return 0  # a vendor's tool result: the vendor keeps what it said


def _tool_characters(tool: Tool) -> int:
    return len(tool.name) + len(tool.description) + len(_json(tool.input_schema))


def _entry(
    message: Message, block: ContentBlock, names: Mapping[str, str]
) -> str | None:
    """A block's entry in the transcript; None for one it leaves out (CTX-9)."""
    match block:
        case TextBlock(text=text):
            speaker = "User" if message.role == "user" else "Assistant"
            return f"{speaker}: {text}"
        case (
            ToolUseBlock(name=name, input=arguments)
            | ServerToolUseBlock(name=name, input=arguments)
        ):
            return f"Assistant called {name} with {_json(arguments)}"
        case ToolResultBlock(tool_use_id=call, content=text, is_error=is_error):
            outcome = "failed" if is_error else "answered"
            return f"{names.get(call, call)} {outcome}: {text}"
    return None  # reasoning, and a vendor's tool results


def _json(value: Mapping[str, Any]) -> str:
    """A JSON object as every port writes it: compact, its keys sorted, the
    characters beyond ASCII as they are (CTX-2)."""
    return json.dumps(
        dict(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
