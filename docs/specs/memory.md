# Memory

Status: Draft

## Scope

What `Kataloop` keeps in its `Store` and how it uses it: the memory of a
checkpoint, the partial turn kept for resume, resume itself, fork and forget.
[engine.md](engine.md) is the contract (ENG-4, ENG-7 to ENG-10); this is how
the engine keeps it. `MemoryStore` keeps the documents in the process;
`kataloop[postgres]` will keep the same documents in PostgreSQL. How a turn
compacts the history it stores is in [context.md](context.md).

## Documents

Both are JSON objects. The store never reads them; the engine writes them and
reads them back.

A **checkpoint's memory**, kept once a turn finishes:

| Field | Value |
|---|---|
| `version` | `1` |
| `parent` | The id of the checkpoint the turn began from, or `null` for a first turn. |
| `prompt` | The turn's prompt. |
| `text` | The turn's answer, `Done.text`. |
| `messages` | The whole conversation up to and including the turn's final assistant message, its older part as the turn compacted it if it did (CTX-12), each message in uni-llm-client's JSON form ([messages.md](https://github.com/the-guish/uni-llm-client/blob/main/docs/specs/messages.md), Serialisation). |

A **partial turn**, the turn in progress as of its last saved round:

| Field | Value |
|---|---|
| `version` | `1` |
| `parent` | The id of the checkpoint the turn began from, or `null`. |
| `prompt` | The turn's prompt. |
| `messages` | The turn's own messages so far: its prompt as a user message, then each saved round's assistant message and, after `tool_use`, the user message of its results. |

A session has at most one partial turn.

## Invariants

- **MEM-1**: A turn from a checkpoint sends the checkpoint's `messages`, then
  its prompt. Each assistant message keeps its `vendor` content, so that it
  replays to its provider as it came (MSG-2, MSG-11), unless the turn compacts
  the history to keep it within the window (CTX-11).
- **MEM-2**: The engine mints a checkpoint's id, `uuid4().hex`, when the turn
  finishes. A store keeps a session's checkpoints in the order they were
  added; the latest is the one added last.
- **MEM-3**: Nothing of the caller's is stored: no system prompt, no agent
  definition, no tool, no model spec (ENG-10). A turn from a checkpoint runs
  with the agent and the model it is given.
- **MEM-4**: A round that does not end the turn (`tool_use`, `pause_turn`) is
  saved in the partial turn once its messages joined the conversation, before
  its results are yielded, so that a result yielded is never run again on
  resume. A turn that runs from its prompt first forgets the partial turn
  there was. The store keeps the checkpoint and forgets the partial turn in
  one write, before `Done` (ENG-4).
- **MEM-5**: With `resume`, after the refusals of ENG-2 (ENG-7):
  1. If the session's partial turn began from `checkpoint_id`, the turn goes
     on from its messages with the next model call. Its saved rounds are not
     yielded again and their tool calls do not run again. It is the saved
     turn that goes on: the prompt given is not compared with its prompt.
  2. Else, if the session's latest checkpoint began from `checkpoint_id`, that
     turn had finished: its `Done` is yielded again, with its text and its id,
     and nothing runs.
  3. Else, the prompt runs from the checkpoint, as without `resume`.
- **MEM-6**: `Done.usage` counts the model calls of the run that yields it, a
  summary call included (CTX-9): for a resumed turn, those after its saved
  rounds; for a `Done` yielded again, none. The rounds bound counts the same
  calls (TURN-7).
- **MEM-7**: A fork gives the target the source's checkpoints up to and
  including the one named, in their order and under their ids, and no partial
  turn (ENG-8). The checkpoint named is the target's latest; one added after
  it is not the target's (ENG-2). The store refuses a fork as `Store.copy`
  says, writing nothing.
- **MEM-8**: Forget deletes the session, its checkpoints and its partial turn
  (ENG-9).
- **MEM-9**: A document of another `version`, or not of the form above, raises
  `ValueError` when it is read.
- **MEM-10**: `MemoryStore` keeps each document as JSON text: a document JSON
  cannot hold is refused when it is written, and every read returns a copy.

## Non-goals

- Retention, or deleting checkpoints older than the latest: memory is deleted
  by forget alone (ENG-9).
- Sharing memory between engines of another kind.

## Open questions

- Whether a partial turn should keep the usage of its saved rounds, so that a
  resumed `Done` counts the whole turn.
- Whether resume should refuse a prompt that is not the saved turn's.
  robinauts' engine contract lists that refusal, and also says that the
  engine does not compare the questions.
- Whether a fork should take the checkpoints the named one descends from,
  rather than every one added before it.
