# Context

Status: Draft

## Scope

How `Kataloop` keeps a conversation within its model's window (ENG-12 of
[engine.md](engine.md), the contract): the window, the estimate of a prompt,
the cut of a large tool result, and the compaction of the older history into
one summary. It applies before every model call of a turn
([turn.md](turn.md), TURN-3), and the history it compacts is what the turn
stores ([memory.md](memory.md)).

In the Python port it is `fit`, in `kataloop_core/_context.py`, its arithmetic
in pure functions:

```python
async def fit(client: AsyncClient, model: ModelSpec, system: str,
              tools: Sequence[Tool], history: Sequence[Message],
              turn: Sequence[Message]) -> Fitted
```

`history` is the conversation the turn goes on from and `turn` the turn's own
messages so far. `Fitted` holds the history to send before `turn`, and the
usage of the summary call `fit` made, or none when it made none.

## Words

- **Window**: what a model call may send, in tokens.
- **History**: the messages of the checkpoint a turn goes on from, before the
  turn's own.
- **Exchange**: a question and what answers it, as CTX-6 cuts the history.
- **Compaction**: the older part of the history replaced by one summary.

## Values

| Name | Value | Meaning |
|---|---|---|
| `DEFAULT_CONTEXT_WINDOW` | `128_000` | The window, in tokens, of a model spec that gives none. Exported. |
| `CHARS_PER_TOKEN` | `4` | Characters per token, for the estimate. |
| `LARGEST_RESULT` | `0.2` | The share of the window one tool result may take. |
| `SUMMARIZE_AT` | `0.7` | The share of the window past which the history is compacted. |
| `KEEP` | `0.3` | The share of the window the newest exchanges kept whole may take. |

For a window of W tokens the engine works in whole numbers, each share
truncated as a double converts to an integer: a tool result takes at most
`int(W × 0.2) × 4` characters, the history is compacted past `int(W × 0.7)`
tokens, the exchanges kept take at most `int(W × 0.3)` tokens, and what is
summarised at most `int(W × 0.7) − int(W × 0.3)` tokens. With W = 300: 240
characters, 210, 90 and 120 tokens.

## Invariants

- **CTX-1**: The window is `ModelSpec.context_window`, else
  `DEFAULT_CONTEXT_WINDOW`. A window that is not a positive number of tokens
  raises `ValueError` from the iterator before anything is read or sent, as a
  timeout does (TURN-1).
- **CTX-2**: Tokens are estimated, the same way in every port, with no vendor:
  a prompt's characters over `CHARS_PER_TOKEN`, rounded up. Its characters are
  those of the system prompt; of each tool, its name, its description and its
  input schema as JSON; and of each block of each message, a text's or a
  reasoning's text, a tool call's name and its input as JSON (a vendor's tool
  call alike), a tool result's content. A vendor's tool result counts nothing,
  and a message's vendor content is never read. JSON is compact, without
  spaces, its keys sorted, characters beyond ASCII as themselves. Characters
  are Unicode code points.
- **CTX-3**: A tool result longer than `int(W × LARGEST_RESULT) ×
  CHARS_PER_TOKEN` characters is cut there when the call answers, and
  `\n[Cut: the result was N characters.]` is appended, N its length before the
  cut. An error result is cut alike. The cut result is what the model sees,
  what the `ToolResult` event carries and what the memory keeps.
- **CTX-4**: The question being answered is never cut (ENG-12): only the
  history is compacted. The turn's own messages, its prompt first, reach the
  model whole whatever their size; a turn that passes the window on its own
  fails at the vendor.
- **CTX-5**: Before each model call of a turn, the first and every later one,
  the whole prompt is estimated: the system prompt, the tools, the history and
  the turn so far. At most `int(W × SUMMARIZE_AT)` tokens, the history is sent
  as it came. Past it, the history is compacted (CTX-7 to CTX-11).
- **CTX-6**: An exchange starts at a user message that holds no tool result and
  runs to just before the next one; a history that starts otherwise has its
  first exchange start at its first message. An assistant's tool call and its
  results are therefore never apart, and neither are a paused turn's messages.
  A summary message (CTX-10), a user message, starts an exchange.
- **CTX-7**: Compaction keeps the newest whole exchanges of the history whose
  estimate, together, is at most `int(W × KEEP)` tokens: counted from the
  newest, they stop at the first that does not fit. What is older is replaced
  by one summary (CTX-9, CTX-10): a summary message at the front of the
  history, the earlier summary, and the older exchanges after it. With no
  older exchange, nothing is compacted and the history is sent as it came,
  however large (CTX-4).
- **CTX-8**: What is summarised is bounded to `int(W × SUMMARIZE_AT) − int(W ×
  KEEP)` tokens, so that the summary call fits the window too: the text it
  reads (CTX-9) is at most that many times `CHARS_PER_TOKEN` characters. The
  earlier summary's entry stays whole at its front; past the bound, the start
  of the older exchanges' transcript is cut, so that their newest part is
  summarised and what is before it left out.
- **CTX-9**: The summary is written by one call to the turn's model,
  `client.complete(model.id, [Message.user(text)], system=SUMMARY_PROMPT,
  max_tokens=model.max_output_tokens, timeout=model.timeout)`: no tools, no
  effort, not streamed. `text` is the transcript of the earlier summary and of
  the older exchanges, bounded (CTX-8): an entry per block, in order, entries
  apart by a blank line (`\n\n`).

  | Block | Entry |
  |---|---|
  | A summary message | Its text, as it is. |
  | A user message's text | `User: TEXT` |
  | An assistant message's text | `Assistant: TEXT` |
  | A tool call, or a vendor's | `Assistant called NAME with INPUT`, the input as JSON (CTX-2). |
  | A tool result | `NAME answered: CONTENT`, or `NAME failed: CONTENT` for an error result. NAME is that of the call with its id among the messages summarised, else the id. |
  | Reasoning, a vendor's tool result | No entry. |

  `SUMMARY_PROMPT` is, exactly:

  > The user's message is a conversation between a user and you, the
  > assistant. Summarise it densely for your own later use: you will go on
  > with the conversation from your summary alone. Keep every fact, decision,
  > name, number and open question. Answer with the summary and nothing else.

  The summary is the response's text, whatever its stop reason. The call is
  one of the turn's model calls: it counts toward the bound on them, the call
  past which raises `RoundsExceededError` instead of being sent (TURN-7); its
  usage is summed into `Done.usage` (TURN-10); it runs under the deadline
  (TURN-8). It yields no event, and its errors end the turn as a round's do.
- **CTX-10**: The summary enters the history as one user message, its text
  `SUMMARY_MARKER`, a line break, then the summary. `SUMMARY_MARKER` is the
  line `[A summary of the earlier conversation]`. The compacted history is
  that message, then the kept exchanges. A user message at the front of a
  history whose text begins with that line is an earlier summary: a later
  compaction folds it (CTX-7) and keeps it whole (CTX-8).
- **CTX-11**: A compacted history replays without the vendor's content, the
  preserved-thinking rule: each kept assistant message is sent from its blocks,
  `vendor` dropped and so its reasoning left out (MSG-2), because current
  Anthropic models bind a thinking block to the exact prefix that produced it
  and refuse it after an edited one. A history that was not compacted replays
  as it came, vendor content included (MEM-1). The turn's own messages always
  keep theirs.
- **CTX-12**: The history a turn compacted is the turn's from then on: its
  later calls are fitted from it, and nothing is older than its kept
  exchanges but the summary, so a turn writes at most one summary. The
  checkpoint written at the end of the turn holds the summary and the kept
  exchanges in place of the history the turn began from, so that the next
  turn goes on from them and compaction happens once, not on every later
  turn. The partial turn holds the turn's own messages and is unaffected: a
  resumed turn fits the history of its checkpoint again (MEM-5).

## Non-goals

- Prompt caching. Cache breakpoints wait for uni-llm-client to place them
  ([the plan](../plan.md)); until then nothing is cached on purpose, and a
  compaction changes the prefix once, after which it holds still.
- Counting tokens with a vendor's tokenizer or its counting endpoint: the
  estimate needs none (CTX-2).
- A table of models' windows: the window is the spec's or the default until
  uni-llm-client knows its models' windows ([the plan](../plan.md),
  Deferred).
- Cutting the turn's own messages, or an assistant message (CTX-4).

## Open questions

- A compaction in the middle of a turn, after a tool round, sends the turn's
  own assistant messages with their vendor content after a prefix that
  changed. Whether Anthropic refuses their thinking blocks then, as it refuses
  an edited history's, is untested; compacting before a turn's first call
  alone would avoid it, at the cost of a turn that grows past the window.
- Four characters per token underestimates code and text in scripts other
  than Latin. A vendor's count would be exact, at the cost of a request.
- A first prompt that begins with the marker line is taken for a summary by
  a later compaction.
