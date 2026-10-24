# Engine

Status: Draft

## Scope

The contract between kataloop and its callers: the operations of an engine,
the values that cross them, the events of a turn, and what each side promises.
robinauts' engine contract is the model for it, so that its adapter is a
translation of names and nothing more.

`Kataloop` is the engine kataloop ships. How it runs a turn is in
[turn.md](turn.md), how it keeps the memory, resume included, in
[memory.md](memory.md), how it offers the tools and reaches MCP servers in
[tools.md](tools.md), and how it keeps a conversation within the model's
window in [context.md](context.md); all keep this contract.

## Words

- **Session**: the engine's memory of one conversation, under an id the caller
  chose.
- **Turn**: one question and everything the agent does to answer it: model
  calls, tool calls, and the final answer.
- **Round**: one model call of a turn and the tool calls it asked for.
- **Checkpoint**: the memory as it was at the end of a finished turn. The
  engine names each one with an id. The caller keeps the id and never looks
  inside.
- **Agent definition**: the system prompt and the tool servers an agent may
  use.
- **Model spec**: the model to run on, as uni-llm-client names it, with its
  limits.

## Operations

```python
class Engine(ABC):
    async def setup(self) -> None
    async def create(self, session_id: UUID) -> None
    async def exists(self, session_id: UUID) -> bool
    def stream(self, session_id: UUID, agent: AgentDefinition, prompt: str, *,
               model: ModelSpec, checkpoint_id: str | None, timeout: float,
               resume: bool = False) -> AsyncGenerator[Event, None]
    async def fork(self, source_id: UUID, target_id: UUID, *, checkpoint_id: str) -> None
    async def forget(self, session_id: UUID) -> None
```

## Values

| Value | Fields |
|---|---|
| `ToolServer` | `id`, `url`, `headers`, `timeout` (seconds, default 60), `exclude` (tool names not offered) |
| `AgentDefinition` | `system_prompt`, `tool_servers` |
| `ModelSpec` | `id` (a uni-llm-client model id, `provider/model`), `timeout` (seconds, default 120: the most a model call waits to connect and for each read and write, not a bound on the whole call, which the turn's `timeout` bounds), `max_output_tokens`, `context_window` (tokens, positive), `effort` |

## Events

| Event | Fields | When |
|---|---|---|
| `TextDelta` | `text` | A piece of the answer's text. |
| `ReasoningDelta` | `text` | A piece of the model's reasoning, when the model exposes it. |
| `ToolCall` | `call_id`, `name`, `arguments` | A tool call, once its arguments are complete. |
| `ToolResult` | `call_id`, `name`, `output`, `is_error` | The call's result, as the model will see it; a failure is an error result. |
| `Done` | `text`, `checkpoint_id`, `usage` | The final answer, the new checkpoint, and the tokens the turn used. Last, once. |

## Invariants

- **ENG-1**: `stream` is not a coroutine: nothing runs before the first
  iteration, and the refusals below are raised from the iterator. It is an
  async generator, typed as one, so that a caller closes it with `aclose`.
- **ENG-2**: A turn or a fork on a session the engine does not have raises
  `SessionNotFoundError`. A checkpoint id the engine does not hold for that
  session, including one of another session or of a turn that did not finish,
  raises `CheckpointNotFoundError`. Nothing is written in either case.
- **ENG-3**: Events come in the order things happen. A tool call is reported
  once its arguments are complete, and its result once the tool answered or
  failed. `Done` comes last, exactly once, and only after every call reported
  has its result.
- **ENG-4**: When `Done` is yielded, the memory already holds the turn under
  the new checkpoint: a turn that finished is remembered even if the caller
  then fails to store the answer.
- **ENG-5**: A turn that raises, or that is cancelled, adds no checkpoint, and
  the next turn does not remember what it said. Cancellation is let through,
  never swallowed, and what the turn opened is released: the model's stream,
  the tool sessions.
- **ENG-6**: Past `timeout` seconds the engine ends the turn by raising
  `TimeoutError`. The deadline bounds the run, not the caller's handling of
  the events.
- **ENG-7**: With `resume`, if the session's latest turn began from
  `checkpoint_id` and the engine saved rounds of it, the engine goes on from
  the last saved round without repeating its tool calls, and a turn that had
  finished yields its `Done` again. Otherwise `prompt` runs from the
  checkpoint. A tool call that started after the last saved round runs again:
  tools are called at least once.
- **ENG-8**: `fork` gives the target the memory as it was at the checkpoint and
  nothing after it; the source's earlier checkpoints stay valid in the fork.
  From then on the two sessions are independent. A target that exists raises
  `SessionExistsError`.
- **ENG-9**: `forget` deletes everything the engine keeps for the session, and
  nothing happens when there is nothing. It is the only way memory is deleted.
- **ENG-10**: The engine stores the memory and nothing else: no agent
  definition, no model spec, no record of the caller's. The caller passes the
  agent and the model at every turn.
- **ENG-11**: Tools are the union of the agent's servers' tools, each under
  its server's own name, without the names a server's `exclude` lists. A name
  two of the agent's servers offer is the caller's configuration error,
  `ValueError` before the first model call; `exclude` resolves it. Every tool
  call of a round runs, parallel calls together, and every call gets a result:
  the tool's answer, or its failure as an error result. The turn goes on
  ([tools.md](tools.md)).
- **ENG-12**: The engine keeps the history within the model's window by its
  own means, summarising or trimming older exchanges, and never cuts the
  question it is answering. A tool result longer than a fifth of the window is
  cut. The window is `ModelSpec.context_window`, else what the engine knows of
  the model, else a default ([context.md](context.md)).
- **ENG-13**: A round is bounded: a turn makes at most one model call per
  second of its `timeout`, so that a loop that never answers ends before the
  deadline does.
- **ENG-14**: Events carry no ids of the caller's, no timestamps and no
  provenance. The caller adds those.
- **ENG-15**: The engine never writes a key, a secret, a prompt or an answer to
  a log, and sends nothing to a tracing or telemetry service.

## Errors

| Error | Raised when |
|---|---|
| `SessionExistsError` | `create` or `fork` names a session that exists. |
| `SessionNotFoundError` | A turn, a fork or a lookup names a session the engine does not have. |
| `CheckpointNotFoundError` | A checkpoint the engine does not hold for that session. |
| `TimeoutError` | The turn passed its deadline (ENG-6). |
| `RoundsExceededError` | The turn needed more model calls than its `timeout` allows (ENG-13). |
| `ValueError` | A `timeout` that is not a positive number of seconds, a `context_window` that is not a positive number of tokens (ENG-12), or a tool name two of the agent's servers offer (ENG-11). |
| uni-llm-client's errors | The model provider failed, refused, or could not be reached; `IncompleteResponseError` when the output limit cut the answer short. |

## What the caller promises

- Create a session before its first turn, and forget it when the conversation
  is deleted.
- Pass the agent definition and the model at every turn, with their secrets
  resolved: the tool servers' headers built, the provider configured in the
  uni-llm-client client the engine was given.
- Store the checkpoint id `Done` carries and pass it back for the next turn and
  for a fork. Hand the engine only its own checkpoint ids.
- Run one turn at a time per session.
- Cancel a turn by closing the iterator, within a bound of its choosing.

## Mapping to robinauts

| robinauts | kataloop |
|---|---|
| `AgentEngine` | `Engine` |
| `AgentDefinition(system_prompt, tools)` | `AgentDefinition(system_prompt, tool_servers)`, the servers resolved from its settings |
| `ModelConfig` + `ModelProviderConfig` | `ModelSpec` + a `ProviderConfig` of uni-llm-client |
| `stream(..., model=id, timeout_seconds=...)` | `stream(..., model=ModelSpec, timeout=...)` |
| `TextDelta`, `ReasoningDelta`, `ToolCall`, `ToolResult` | The same names and fields |
| `Done(text, checkpoint_id)` | `Done(text, checkpoint_id, usage)` |
| `kinds()` | The kinds uni-llm-client speaks |
| `StorageKind` | A `Store`: in the process, or PostgreSQL in `kataloop[postgres]` |

## Non-goals

- Deciding when a turn runs, retrying it, or scheduling it.
- A transcript people read, exports, retention, access control.
- Creating a session on the engine's own.
- Knowing where a conversation stands: the caller names the checkpoint.

## Open questions

- A `prompt` that is more than text: attachments, documents.
- Whether `Done.usage` should sum the turn's calls or list them.
