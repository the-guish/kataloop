# Copyright 2026 The kataloop Authors
# SPDX-License-Identifier: Apache-2.0

"""Context management (docs/specs/context.md): the window, the estimate, the cut,
the exchanges, what is kept and what is summarised, and the turns that compact."""

from typing import Any
from uuid import UUID

import pytest
from uni_llm_client import (
    AsyncClient,
    Message,
    ReasoningBlock,
    ServerToolResultBlock,
    ServerToolUseBlock,
    TextBlock,
    Tool,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
    VendorContent,
)

from kataloop_core import (
    DEFAULT_CONTEXT_WINDOW,
    AgentDefinition,
    Done,
    Kataloop,
    MemoryStore,
    ModelSpec,
    RoundsExceededError,
    ToolResult,
)
from kataloop_core._context import (
    SUMMARY_MARKER,
    SUMMARY_PROMPT,
    Compaction,
    Fitted,
    characters,
    compaction,
    cut,
    exchanges,
    fit,
    is_summary,
    newest,
    replayed,
    summarised,
    summary_message,
    tokens,
    transcript,
    window_of,
)
from support import (
    MODEL,
    FakeVendor,
    content,
    message,
    reply,
    run,
    text,
    thinking,
    tool_use,
)

WINDOW = ModelSpec(MODEL.id, context_window=100)
"""Summarises past 70 tokens (280 characters), keeps 30 (120 characters), and
the summary call reads at most 40 (160 characters); a tool result is cut past 80
characters."""


def said(value: str) -> Message:
    """An assistant message of text, with the vendor's content."""
    return Message(
        "assistant",
        (TextBlock(value),),
        VendorContent("anthropic", [{"type": "text", "text": value}]),
    )


def called(id: str, name: str, **arguments: Any) -> Message:
    """An assistant message that calls a tool, with the vendor's content."""
    raw = {"type": "tool_use", "id": id, "name": name, "input": arguments}
    return Message(
        "assistant",
        (ToolUseBlock(id, name, arguments),),
        VendorContent("anthropic", [raw]),
    )


def answered(id: str, output: str) -> Message:
    return Message.tool_results(ToolResultBlock(id, output))


def user(value: str) -> dict[str, Any]:
    """A user message of text, as the vendor receives it."""
    return {"role": "user", "content": value}


E1 = (Message.user("a" * 60), said("A."))  # 62 characters
E2 = (Message.user("b" * 56), said("B."))  # 58
E3 = (Message.user("c" * 58), said("C."))  # 60


def test_the_summary_prompt_and_its_marker_are_fixed() -> None:
    # Every port sends these, and a fake model recognises them.
    assert SUMMARY_PROMPT == (
        "The user's message is a conversation between a user and you, the "
        "assistant. Summarise it densely for your own later use: you will go on "
        "with the conversation from your summary alone. Keep every fact, decision, "
        "name, number and open question. Answer with the summary and nothing else."
    )
    assert SUMMARY_MARKER == "[A summary of the earlier conversation]"


def test_the_window_is_the_specs_else_the_default() -> None:
    assert window_of(MODEL) == DEFAULT_CONTEXT_WINDOW == 128_000
    assert window_of(WINDOW) == 100


@pytest.mark.parametrize("window", [0, -100])
async def test_a_window_that_is_not_positive_is_refused(
    engine: Kataloop, vendor: FakeVendor, session: UUID, window: int
) -> None:
    with pytest.raises(ValueError, match="context window"):
        await run(engine, session, model=ModelSpec(MODEL.id, context_window=window))
    assert vendor.requests == []


def test_the_estimate_counts_characters_over_four_rounded_up() -> None:
    reasoned = Message(
        "assistant",
        (
            ReasoningBlock("Hmm."),
            TextBlock("Paris."),
            ToolUseBlock("toolu_01", "forecast", {"days": 2, "city": "Paris"}),
        ),
        # The vendor's content is not counted: the estimate needs no vendor.
        VendorContent("anthropic", [{"type": "thinking", "thinking": "x" * 1000}]),
    )
    results = Message.tool_results(ToolResultBlock("toolu_01", "Sunny."))
    searched = Message(
        "assistant",
        (
            ServerToolUseBlock("srv_01", "web_search", {"query": "Zürich"}),
            ServerToolResultBlock("srv_01"),
        ),
    )
    tool = Tool("forecast", "The forecast.", {"type": "object"})

    # 4 + 6, then the name and the input as compact JSON: {"city":"Paris","days":2}.
    assert characters(reasoned) == 4 + 6 + 8 + 25
    assert characters(results) == 6
    # {"query":"Zürich"}, its ü one character; the vendor's result counts nothing.
    assert characters(searched) == 10 + 18
    assert tokens() == 0
    assert tokens(system="Brief") == 2
    # The name, the description, and the schema as compact JSON: 38 characters.
    assert tokens(tools=[tool]) == 10
    assert tokens([reasoned, results], system="Brief", tools=[tool]) == 23


def test_a_result_past_a_fifth_of_the_window_is_cut() -> None:
    # A window of 10 tokens: a result takes at most 2 tokens, 8 characters.
    assert cut("12345678", 10) == "12345678"
    assert cut("123456789", 10) == "12345678\n[Cut: the result was 9 characters.]"
    long = "x" * 102_401
    assert cut(long, DEFAULT_CONTEXT_WINDOW) == (
        "x" * 102_400 + "\n[Cut: the result was 102401 characters.]"
    )


def test_an_exchange_runs_from_a_question_to_the_next() -> None:
    question, asked = Message.user("Weather?"), called("toolu_01", "forecast")
    result, answer = answered("toolu_01", "Sunny."), said("Sunny.")
    again, rain = Message.user("Tomorrow?"), said("Rain.")
    summary = summary_message("Earlier.")

    # A tool call and its results are never apart.
    assert exchanges([question, asked, result, answer, again, rain]) == [
        (question, asked, result, answer),
        (again, rain),
    ]
    assert exchanges([summary, again, rain]) == [(summary,), (again, rain)]
    assert exchanges([rain, again]) == [(rain,), (again,)]
    assert exchanges([]) == []


def test_the_newest_exchanges_that_fit_are_kept() -> None:
    a = (Message.user("a" * 40),)  # 10 tokens
    b = (Message.user("b" * 20), said("b" * 20))  # 10 tokens
    c = (Message.user("c" * 8),)  # 2 tokens

    assert newest([a, b, c], 22) == 0
    assert newest([a, b, c], 12) == 1
    assert newest([a, b, c], 11) == 2
    assert newest([a, b, c], 1) == 3
    # The newest in a row: one older that would fit stays out past one that does
    # not.
    assert newest([c, a, c], 5) == 2
    assert newest([], 10) == 0


def test_what_is_older_than_the_kept_exchanges_is_folded() -> None:
    # E2 and E3 take 118 characters of the 120 kept; E1 is folded.
    assert compaction([*E1, *E2, *E3], 100) == Compaction((), E1, (*E2, *E3))


def test_there_is_nothing_to_fold_but_an_earlier_summary() -> None:
    summary = summary_message("Earlier.")

    assert compaction([*E2, *E3], 100) is None
    assert compaction([summary, *E2, *E3], 100) is None
    assert compaction([], 100) is None


def test_what_is_summarised_is_its_transcript_within_the_bound() -> None:
    plan = compaction([*E1, *E2, *E3], 100)
    assert plan is not None

    assert summarised(plan, 100) == f"User: {'a' * 60}\n\nAssistant: A."


def test_past_the_bound_the_newest_part_is_summarised() -> None:
    big = (Message.user("y" * 200), said("Y."))
    plan = compaction([*big, *E2, *E3], 100)
    assert plan == Compaction((), big, (*E2, *E3))

    # 160 characters: the start of the transcript is cut.
    assert summarised(plan, 100) == f"{'y' * 145}\n\nAssistant: Y."


def test_an_earlier_summary_stays_whole_at_the_front_of_what_is_summarised() -> None:
    summary = summary_message("x" * 32)  # 72 characters
    e0 = (Message.user("z" * 40), said("Z."))
    plan = compaction([summary, *e0, *E1, *E2, *E3], 100)
    assert plan == Compaction((summary,), (*e0, *E1), (*E2, *E3))

    # 160 characters: the summary's 72, a blank line, then the newest 86.
    rest = f"User: {'z' * 40}\n\nAssistant: Z.\n\nUser: {'a' * 60}\n\nAssistant: A."
    assert summarised(plan, 100) == f"{summary.text}\n\n{rest[-86:]}"
    # A summary that fills the bound alone is read alone.
    filling = summary_message("x" * 200)
    plan = compaction([filling, *E1, *E2, *E3], 100)
    assert plan is not None
    assert summarised(plan, 100) == filling.text


def test_the_transcript_has_an_entry_per_block() -> None:
    messages = [
        summary_message("The user is in Lisbon."),
        Message.user("Weather?"),
        Message(
            "assistant",
            (
                ReasoningBlock("Paris, then."),
                TextBlock("Let me check."),
                ToolUseBlock("toolu_01", "forecast", {"days": 2, "city": "Paris"}),
                ToolUseBlock("toolu_02", "alerts", {"city": "Paris"}),
            ),
        ),
        Message.tool_results(
            ToolResultBlock("toolu_01", "Sunny."),
            ToolResultBlock("toolu_02", "Down.", is_error=True),
            ToolResultBlock("toolu_09", "Late."),
        ),
        Message(
            "assistant",
            (
                ServerToolUseBlock("srv_01", "web_search", {"query": "Paris"}),
                ServerToolResultBlock("srv_01"),
                TextBlock("Sunny."),
            ),
        ),
    ]

    assert transcript(messages) == (
        "[A summary of the earlier conversation]\nThe user is in Lisbon.\n\n"
        "User: Weather?\n\n"
        "Assistant: Let me check.\n\n"
        'Assistant called forecast with {"city":"Paris","days":2}\n\n'
        'Assistant called alerts with {"city":"Paris"}\n\n'
        "forecast answered: Sunny.\n\n"
        "alerts failed: Down.\n\n"
        "toolu_09 answered: Late.\n\n"
        'Assistant called web_search with {"query":"Paris"}\n\n'
        "Assistant: Sunny."
    )


def test_a_summary_message_begins_with_the_marker_line() -> None:
    summary = summary_message("The user is in Lisbon.")

    assert summary == Message.user(
        "[A summary of the earlier conversation]\nThe user is in Lisbon."
    )
    assert is_summary(summary)
    assert not is_summary(Message.user(SUMMARY_MARKER))
    assert not is_summary(said(f"{SUMMARY_MARKER}\nNo."))


def test_a_replayed_message_has_no_vendor_content() -> None:
    question, asked = Message.user("Weather?"), called("toolu_01", "forecast")

    assert replayed([question, asked]) == (
        question,
        Message("assistant", asked.content),
    )


async def test_under_the_threshold_the_history_goes_as_it_came(
    client: AsyncClient, vendor: FakeVendor
) -> None:
    history = (*E1, *E2, *E3)

    # 9 + 180 + 20 characters: 53 tokens of the 70.
    fitted = await fit(
        client, WINDOW, "Be brief.", [], history, [Message.user("d" * 20)]
    )

    assert fitted == Fitted(history)
    assert fitted.history[1].vendor is not None
    assert vendor.requests == []


async def test_past_the_threshold_the_older_exchanges_are_summarised(
    client: AsyncClient, vendor: FakeVendor
) -> None:
    vendor.serve(message(text("The user asked about a."), input_tokens=30))
    model = ModelSpec(
        MODEL.id, timeout=7.5, max_output_tokens=500, context_window=100, effort="high"
    )
    tool = Tool("now", "The time.", {"type": "object"})

    # 9 + 29 + 180 + 100 characters: 80 tokens of the 70.
    fitted = await fit(
        client, model, "Be brief.", [tool], (*E1, *E2, *E3), [Message.user("d" * 100)]
    )

    # The same model, without the tools or the effort, does not stream.
    assert vendor.requests == [
        {
            "model": "test-model",
            "max_tokens": 500,
            "system": SUMMARY_PROMPT,
            "messages": [user(f"User: {'a' * 60}\n\nAssistant: A.")],
        }
    ]
    assert vendor.timeouts == [{"connect": 7.5, "read": 7.5, "write": 7.5, "pool": 7.5}]
    summary = summary_message("The user asked about a.")
    assert fitted == Fitted(
        (summary, *replayed((*E2, *E3))), Usage(input_tokens=30, output_tokens=5)
    )


async def test_past_the_threshold_with_nothing_to_fold_nothing_changes(
    client: AsyncClient, vendor: FakeVendor
) -> None:
    question = [Message.user("q" * 1000)]

    # The question is never cut, nor what is kept (CTX-4).
    assert await fit(client, WINDOW, "", [], (), question) == Fitted(())
    fitted = await fit(client, WINDOW, "", [], (*E2, *E3), question)

    assert fitted == Fitted((*E2, *E3))
    assert fitted.history[1].vendor is not None
    assert vendor.requests == []


async def test_a_long_result_is_cut_for_the_model_the_events_and_the_memory(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    city = "x" * 100
    vendor.serve(
        reply(tool_use("toolu_01", "forecast", city=city), stop_reason="tool_use"),
        reply(text("Sunny.")),
    )

    events = await run(engine, session, model=WINDOW)

    shown = f"Sunny in {city}."[:80] + "\n[Cut: the result was 110 characters.]"
    assert ToolResult("toolu_01", "forecast", shown) in events
    sent = {"type": "tool_result", "tool_use_id": "toolu_01", "content": shown}
    assert vendor.requests[1]["messages"][-1] == {"role": "user", "content": [sent]}
    done = events[-1]
    assert isinstance(done, Done)
    memory = await store.checkpoint(session, done.checkpoint_id)
    assert memory is not None
    assert memory["messages"][2]["content"][0]["content"] == shown


AGENT = AgentDefinition("Answer briefly.")


async def two_turns(engine: Kataloop, vendor: FakeVendor, session: UUID) -> Done:
    """A turn of 156 characters, then one of 87 from it, in a window of 100."""
    vendor.serve(reply(text("First.")), reply(text("Second.")))
    *_, first = await run(engine, session, "a" * 150, agent=AGENT, model=WINDOW)
    assert isinstance(first, Done)
    *_, second = await run(
        engine,
        session,
        "b" * 80,
        agent=AGENT,
        model=WINDOW,
        checkpoint_id=first.checkpoint_id,
    )
    assert isinstance(second, Done)
    return second


async def test_a_turn_that_compacts_keeps_the_compacted_history(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    second = await two_turns(engine, vendor, session)
    blocks = (thinking("Short."), text("Third."))
    vendor.serve(
        message(text("Asked about a."), input_tokens=40, output_tokens=6),
        reply(*blocks, input_tokens=30, output_tokens=7),
    )

    # 15 + 156 + 87 + 40 characters: 75 tokens of the 70.
    *_, third = await run(
        engine,
        session,
        "c" * 40,
        agent=AGENT,
        model=WINDOW,
        checkpoint_id=second.checkpoint_id,
    )
    vendor.serve(reply(text("Fourth.")))
    assert isinstance(third, Done)
    await run(
        engine,
        session,
        "d" * 10,
        agent=AGENT,
        model=WINDOW,
        checkpoint_id=third.checkpoint_id,
    )

    summary = user(f"{SUMMARY_MARKER}\nAsked about a.")
    summary_call, compacted, after = vendor.requests[2:]
    assert summary_call == {
        "model": "test-model",
        "max_tokens": 16000,
        "system": SUMMARY_PROMPT,
        # 160 characters of the 175 of its transcript, the newest.
        "messages": [user(f"{'a' * 141}\n\nAssistant: First.")],
    }
    # The kept exchange replays from its blocks; the turn as it came.
    kept = [user("b" * 80), {"role": "assistant", "content": "Second."}]
    assert compacted["messages"] == [summary, *kept, user("c" * 40)]
    # The summary call counts (TURN-10).
    assert third.usage == Usage(input_tokens=70, output_tokens=13)
    # The next turn goes on from what the checkpoint kept, compacted once.
    assert after["messages"] == [
        summary,
        *kept,
        user("c" * 40),
        {"role": "assistant", "content": content(*blocks)},
        user("d" * 10),
    ]
    memory = await store.checkpoint(session, third.checkpoint_id)
    assert memory is not None
    assert [m["vendor"] is None for m in memory["messages"]] == [True] * 4 + [False]


async def test_the_summary_call_is_one_of_the_turns_calls(
    engine: Kataloop, store: MemoryStore, vendor: FakeVendor, session: UUID
) -> None:
    second = await two_turns(engine, vendor, session)
    vendor.serve(message(text("Asked about a.")))

    # A second: one model call, the summary's (ENG-13).
    with pytest.raises(RoundsExceededError):
        await run(
            engine,
            session,
            "c" * 40,
            agent=AGENT,
            model=WINDOW,
            checkpoint_id=second.checkpoint_id,
            timeout=1,
        )

    assert len(vendor.requests) == 3
    assert await store.latest_checkpoint(session) == second.checkpoint_id
