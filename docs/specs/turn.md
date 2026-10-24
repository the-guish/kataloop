# Turn

Status: Draft

## Scope

How `Kataloop`, the engine kataloop ships, runs a turn of `Engine.stream`
([engine.md](engine.md), the contract): its rounds, the tools it offers and
runs, what each stop reason does, the bounds of a turn, and what `Done`
carries. What a turn reads from memory and keeps there, and resume, come with
the memory in the process (step 3 of [the plan](../plan.md)).

```python
Kataloop(client: uni_llm_client.AsyncClient, store: Store, toolbox: Toolbox)
```

The client comes configured with the providers the model ids name, and is the
only way the engine reaches a vendor; the engine never closes it. The store
keeps the memory, and the toolbox reaches the agent's tool servers: in the
core, `MemoryStore` and `LocalToolbox`, tools of the process's own.

## A turn

The conversation is the checkpoint's messages, then the prompt as a user
message. The agent's tools are listed once. Then rounds follow, each a model
call and the tool calls it asked for, until the model ends the turn:

1. The model call streams; its text, its reasoning and each complete tool call
   are yielded as they come.
2. Its stop reason says what follows: the answer, the tool calls, or another
   call.

## Invariants

- **TURN-1**: `timeout` is a positive, finite number of seconds; otherwise
  `ValueError`, from the iterator, before anything is read or sent. The
  deadline is set once, `timeout` seconds after the first iteration.
- **TURN-2**: The tools offered are each server's tools, in the agent's order
  of servers and the toolbox's order of tools, without those its `exclude`
  names, as `<server id>_<tool>` with the tool's description and input schema
  (ENG-11). They are listed once per turn. Two tools offered under one name
  raise `ValueError` before the first model call.
- **TURN-3**: A round's model call is `client.stream(model.id, fit(messages,
  model), system=agent.system_prompt, tools=offered, effort=model.effort,
  max_tokens=model.max_output_tokens, timeout=model.timeout)`. `fit` is the
  one place context management (ENG-12) applies; until it does, it returns the
  messages as they are. `model.timeout` bounds each read and write of the
  exchange (PROV-8); the deadline bounds the whole.
- **TURN-4**: Each text and reasoning delta of the model's stream is yielded as
  `TextDelta` and `ReasoningDelta` as it arrives. Each tool call is yielded as
  `ToolCall(id, name, input)` once the stream completes it (`ToolUseEnd`),
  under the name the model used (ENG-3).
- **TURN-5**: What follows a model call is its stop reason's:

  | Stop reason | What follows |
  |---|---|
  | `end_turn` | The turn ends with `Done` (TURN-10). |
  | `tool_use` | The calls run (TURN-6); the assistant message, then one user message of their results, join the conversation, and the next round begins. |
  | `pause_turn` | The assistant message joins the conversation and the next round sends it back, so that the vendor goes on. Nothing more is yielded. |
  | `max_tokens` | `IncompleteResponseError`: a cut answer is not an answer. |

- **TURN-6**: Every tool call of a round runs, all of them together, each
  bounded by its server's `timeout`, and each gets a result (ENG-11). A name
  the turn did not offer, a call that raises and a call past its server's
  timeout each get an error result that says so in one sentence; a raised
  error is named by its type alone, since its words were not written for the
  model. An error a tool reports itself (`ToolOutput.is_error`) is passed on as
  it is. Once every call has answered, the results are yielded as
  `ToolResult`s in the order of the calls, and sent back as `ToolResultBlock`s
  in that order.
- **TURN-7**: A turn makes at most `ceil(timeout / 1 s)` model calls (ENG-13),
  `pause_turn` rounds included. The call past them raises
  `RoundsExceededError` instead of being sent.
- **TURN-8**: Every await of the turn is bounded by the deadline: the store's,
  the toolbox's, each read of the model's stream, and the tool calls of a
  round. Past it the turn raises `TimeoutError` (ENG-6). Nothing is awaited
  while an event is with the caller, so the deadline never interrupts the
  caller's handling of an event; the time that handling takes still counts,
  and the turn ends at its next await.
- **TURN-9**: The model's stream is read under `contextlib.aclosing`, so that
  closing the turn's iterator, cancelling its task, or an error closes the
  vendor's response (STREAM-6). The turn never catches `CancelledError` or
  `GeneratorExit` (ENG-5); tool calls running when it is cancelled are
  cancelled with it.
- **TURN-10**: When the model ends the turn, the store holds the turn's
  checkpoint before `Done` is yielded (ENG-4). `Done.text` is the text of the
  final assistant message, `Done.checkpoint_id` the new checkpoint's id, and
  `Done.usage` the sum of the usage of the turn's model calls. A turn that
  raises or is cancelled adds no checkpoint.

## Non-goals

- Yielding a tool's result before the round's other calls have answered.
- Retrying: uni-llm-client retries a model call that may pass
  ([retries.md](https://github.com/the-guish/uni-llm-client/blob/main/docs/specs/retries.md));
  the caller retries a turn.
- The vendor's own tools, such as web search: the engine offers none.
  `pause_turn` is honoured for a vendor that pauses anyway.
- Choosing the tool (`tool_choice`), or forbidding parallel calls.

## Open questions

- Whether a tool server's session should open with the turn and close with
  it, which the `Toolbox` port would then expose; the MCP toolbox (step 5 of
  [the plan](../plan.md)) decides.
- Whether `Engine.stream` should be typed as an `AsyncGenerator`, so that a
  caller closes it without a cast; uni-llm-client's `stream` has the same
  question (STREAM-6).
